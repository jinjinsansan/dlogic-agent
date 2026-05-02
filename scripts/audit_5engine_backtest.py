#!/usr/bin/env python3
"""5基合議バックテスト — NLogic追加による エッジ増分 を検証.

手順:
1. VPS backend の /api/v2/predictions/newspaper を NLogic 対応版にデプロイ
2. PCKEIBA から NAR/JRA の出走データを読み、VPS API で 5基予想を取得
3. 4基合議 vs 5基合議 の回収率を比較
4. NLogic 単独の精度も計測

前提:
- PCKEIBA (PostgreSQL) がローカルで稼働中
- VPS backend (port 8000) が NLogic 対応済み
- Supabase env は VPS から SSH 取得 or ローカル .env.local

Usage:
    python scripts/audit_5engine_backtest.py --race-type nar --since 20260301 --until 20260430
    python scripts/audit_5engine_backtest.py --race-type jra --since 20260301 --until 20260430
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations

import psycopg2
import requests

random.seed(42)

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")

PCKEIBA_CONFIG = {
    "host": "127.0.0.1", "port": 5432, "database": "pckeiba",
    "user": "postgres", "password": "postgres",
}

DLOGIC_API_URL = os.getenv("DLOGIC_API_URL", "http://220.158.24.157:8000")

NAR_VENUES = {
    '83': '帯広', '30': '門別', '35': '盛岡', '36': '水沢',
    '45': '浦和', '43': '船橋', '42': '大井', '44': '川崎',
    '46': '金沢', '47': '笠松', '48': '名古屋',
    '50': '園田', '51': '姫路', '54': '高知', '55': '佐賀',
}
JRA_VENUES = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟',
    '05': '東京', '06': '中山', '07': '中京', '08': '京都',
    '09': '阪神', '10': '小倉',
}
NANKAN_CODES = {'42', '43', '44', '45'}
REGION_GROUPS = [{'35', '36'}, {'46', '47', '48'}, {'50', '51'}, {'54', '55'}, {'30', '83'}]

SCHEDULE_PATHS = [
    os.path.join(PROJECT_DIR, 'data', 'nar_schedule_master_2020_2026.json'),
    r'E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json',
]

ENGINES_4 = ("dlogic", "ilogic", "viewlogic", "metalogic")
ENGINES_5 = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")

GOLDEN_STRONG_VENUES_V4 = {"川崎", "船橋", "大井", "浦和", "門別", "笠松"}


def load_schedule():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    return None


def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule:
        return code
    days = schedule['schedule_data'].get(nen + md, [])
    if not days:
        return code
    if len(days) == 1:
        return days[0]
    if code in days:
        return code
    if code in NANKAN_CODES:
        n = [c for c in days if c in NANKAN_CODES]
        if len(n) == 1:
            return n[0]
    for g in REGION_GROUPS:
        if code in g:
            cands = [c for c in days if c in g]
            if len(cands) == 1:
                return cands[0]
            break
    return code


def safe_int(v):
    if v is None:
        return 0
    s = str(v).strip()
    try:
        return int(s) if s else 0
    except (ValueError, TypeError):
        return 0


def parse_horses(s):
    s = (s or '').strip()
    if not s or s == '00':
        return ()
    if len(s) % 2 != 0:
        return ()
    out = []
    for i in range(0, len(s), 2):
        try:
            out.append(int(s[i:i + 2]))
        except ValueError:
            return ()
    return tuple(out)


def load_races_from_pckeiba(race_type, since, until, schedule):
    """Load race entries + results from PCKEIBA."""
    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    table_se = 'nvd_se' if race_type == 'nar' else 'jvd_se'
    table_hr = 'nvd_hr' if race_type == 'nar' else 'jvd_hr'
    venue_map = NAR_VENUES if race_type == 'nar' else JRA_VENUES

    since_nen, since_md = since[:4], since[4:]
    until_nen, until_md = until[:4], until[4:]

    # Load results (payouts)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b
        FROM {table_hr}
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
    """, (since, until))

    results = {}
    for nen, md, code, bango, ta, tb in cur.fetchall():
        if race_type == 'nar':
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = venue_map.get(cc)
        else:
            venue = venue_map.get(code)
        if not venue:
            continue
        try:
            rno = int(bango)
        except (ValueError, TypeError):
            continue
        wh = parse_horses(ta)
        wp = safe_int(tb)
        if not wh or wp == 0:
            continue
        date_str = f"{nen}-{md[:2]}-{md[2:4]}"
        key = (date_str, venue, rno)
        results[key] = {'winner': wh[0], 'payout': wp}
    cur.close()

    # Load entries (horse name, jockey, umaban, etc.)
    cur = conn.cursor("se_stream")
    cur.itersize = 50000

    # Try to find available columns
    test_cur = conn.cursor()
    test_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table_se,))
    available_cols = {r[0] for r in test_cur.fetchall()}
    test_cur.close()

    horse_col = None
    for c in ['bamei', 'umamei', 'horse_name']:
        if c in available_cols:
            horse_col = c
            break

    jockey_col = None
    for c in ['kishumei_ryakusho', 'kishu_mei', 'kishumei']:
        if c in available_cols:
            jockey_col = c
            break

    post_col = None
    for c in ['wakuban', 'waku_bango']:
        if c in available_cols:
            post_col = c
            break

    dist_col = None
    for c in ['kyori', 'distance']:
        if c in available_cols:
            dist_col = c
            break

    ninki_col = 'tansho_ninkijun' if 'tansho_ninkijun' in available_cols else None

    select_cols = [
        'kaisai_nen', 'kaisai_tsukihi', 'keibajo_code', 'race_bango',
        'umaban', 'kakutei_chakujun',
    ]
    if horse_col:
        select_cols.append(horse_col)
    if jockey_col:
        select_cols.append(jockey_col)
    if post_col:
        select_cols.append(post_col)
    if dist_col:
        select_cols.append(dist_col)
    if ninki_col:
        select_cols.append(ninki_col)

    cur.execute(f"""
        SELECT {', '.join(select_cols)}
        FROM {table_se}
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
        ORDER BY kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, umaban
    """, (since, until))

    races = defaultdict(lambda: {'entries': [], 'meta': {}})
    for row in cur:
        idx = 0
        nen = row[idx]; idx += 1
        md = row[idx]; idx += 1
        code = row[idx]; idx += 1
        bango = row[idx]; idx += 1
        umaban = row[idx]; idx += 1
        chaku = row[idx]; idx += 1

        horse_name = row[idx] if horse_col else None; idx += (1 if horse_col else 0)
        jockey = row[idx] if jockey_col else None; idx += (1 if jockey_col else 0)
        post = row[idx] if post_col else None; idx += (1 if post_col else 0)
        dist = row[idx] if dist_col else None; idx += (1 if dist_col else 0)
        ninki = row[idx] if ninki_col else None; idx += (1 if ninki_col else 0)

        if race_type == 'nar':
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = venue_map.get(cc)
        else:
            venue = venue_map.get(code)
        if not venue:
            continue
        try:
            rno = int(bango)
            hno = int(str(umaban).strip())
        except (ValueError, TypeError):
            continue

        date_str = f"{nen}-{md[:2]}-{md[2:4]}"
        key = (date_str, venue, rno)

        hn = (str(horse_name).strip() if horse_name else f"#{hno}")
        jk = (str(jockey).strip() if jockey else "")
        pn = safe_int(post) or hno
        d = safe_int(dist)
        pop = safe_int(ninki)
        fin = safe_int(chaku)

        races[key]['entries'].append({
            'horse_no': hno, 'horse_name': hn, 'jockey': jk,
            'post_no': pn, 'finish': fin, 'pop': pop,
        })
        races[key]['meta'] = {
            'date': date_str, 'venue': venue, 'race_no': rno,
            'distance': d, 'race_type': race_type,
        }

    cur.close()
    conn.close()

    # Merge results
    merged = []
    for key, race in races.items():
        res = results.get(key)
        if not res:
            continue
        if len(race['entries']) < 5:
            continue
        race['result'] = res
        merged.append(race)

    logger.info(f"Loaded {len(merged)} races with results ({race_type} {since}-{until})")
    return merged


def get_predictions_from_api(race):
    """Call VPS prediction API for 5-engine predictions."""
    meta = race['meta']
    entries = sorted(race['entries'], key=lambda x: x['horse_no'])

    payload = {
        "race_id": f"{meta['date'].replace('-', '')}-{meta['venue']}-{meta['race_no']}",
        "horses": [e['horse_name'] for e in entries],
        "horse_numbers": [e['horse_no'] for e in entries],
        "venue": meta['venue'],
        "race_number": meta['race_no'],
        "jockeys": [e['jockey'] for e in entries],
        "posts": [e['post_no'] for e in entries],
        "distance": f"{meta['distance']}m" if meta['distance'] else "",
        "track_condition": "良",
    }

    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}/api/v2/predictions/newspaper",
            json=payload, timeout=90,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        return None

    out = {}
    for eng in ENGINES_5:
        raw = body.get(eng)
        if isinstance(raw, list) and raw:
            out[eng] = [int(x) for x in raw if x][:5]
    return out


def evaluate_consensus(preds, winner, payout, pop, venue, weekday, engines):
    """Evaluate a consensus bet using the given engine set."""
    top1_counts = Counter()
    top3_union = Counter()
    for eng in engines:
        picks = preds.get(eng)
        if not picks:
            continue
        if picks:
            top1_counts[picks[0]] += 1
        for h in picks[:3]:
            top3_union[h] += 1

    if not top1_counts:
        return None

    cons_horse, cons_count = top1_counts.most_common(1)[0]
    won = (cons_horse == winner)
    pay = payout if won else 0

    return {
        'cons_horse': cons_horse,
        'cons_count': cons_count,
        'total_engines': len([e for e in engines if e in preds]),
        'won': won,
        'payout': pay,
        'pop': pop.get(cons_horse),
        'venue': venue,
        'weekday': weekday,
    }


def bootstrap_ci(profits, n_resamples=10000):
    if not profits or len(profits) < 30:
        return None, None
    n = len(profits)
    means = []
    for _ in range(n_resamples):
        sample = [profits[random.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(n_resamples * 0.025)]
    hi = means[int(n_resamples * 0.975)]
    return (1 + lo / 100) * 100, (1 + hi / 100) * 100


def aggregate(results_list, label):
    n = len(results_list)
    if n == 0:
        return {'label': label, 'n': 0}
    inv = n * 100
    pay = sum(r['payout'] for r in results_list)
    hits = sum(1 for r in results_list if r['won'])
    recov = pay / inv * 100 if inv > 0 else 0
    profits = [r['payout'] - 100 for r in results_list]
    ci_lo, ci_hi = bootstrap_ci(profits)
    return {
        'label': label, 'n': n, 'inv': inv, 'pay': pay,
        'profit': pay - inv, 'hits': hits,
        'hit_pct': hits / n * 100,
        'recov': recov,
        'ci_lo': ci_lo, 'ci_hi': ci_hi,
    }


def fmt(d):
    if d['n'] == 0:
        return f"{d['label']}: 0件"
    ci = f" CI[{d['ci_lo']:.0f}%-{d['ci_hi']:.0f}%]" if d.get('ci_lo') else ""
    return (f"{d['label']}: n={d['n']} 的中={d['hits']}({d['hit_pct']:.1f}%) "
            f"回収率={d['recov']:.1f}%{ci} 利益={d['profit']:+,}円")


def run_backtest(race_type, since, until):
    schedule = load_schedule()
    races = load_races_from_pckeiba(race_type, since, until, schedule)

    results_4eng = []
    results_5eng = []
    results_nlogic_solo = []
    nlogic_available = 0
    api_errors = 0
    processed = 0

    for i, race in enumerate(races):
        if i % 100 == 0:
            logger.info(f"Processing {i}/{len(races)} ...")

        meta = race['meta']
        winner = race['result']['winner']
        payout = race['result']['payout']
        weekday_idx = datetime.strptime(meta['date'], '%Y-%m-%d').weekday()
        weekday = ['月', '火', '水', '木', '金', '土', '日'][weekday_idx]

        # Build pop map
        pop_map = {}
        for e in race['entries']:
            if e.get('pop'):
                pop_map[e['horse_no']] = e['pop']

        preds = get_predictions_from_api(race)
        if not preds:
            api_errors += 1
            continue
        processed += 1

        # 4-engine consensus
        ev4 = evaluate_consensus(preds, winner, payout, pop_map, meta['venue'], weekday, ENGINES_4)
        if ev4 and ev4['cons_count'] >= 2:
            results_4eng.append(ev4)

        # 5-engine consensus (only if nlogic returned)
        if 'nlogic' in preds and preds['nlogic']:
            nlogic_available += 1
            ev5 = evaluate_consensus(preds, winner, payout, pop_map, meta['venue'], weekday, ENGINES_5)
            if ev5 and ev5['cons_count'] >= 2:
                results_5eng.append(ev5)

            # NLogic solo
            nl_picks = preds['nlogic']
            if nl_picks:
                nl_won = (nl_picks[0] == winner)
                results_nlogic_solo.append({
                    'cons_horse': nl_picks[0],
                    'cons_count': 1,
                    'won': nl_won,
                    'payout': payout if nl_won else 0,
                    'pop': pop_map.get(nl_picks[0]),
                    'venue': meta['venue'],
                    'weekday': weekday,
                })

        # Rate limit
        if processed % 50 == 0:
            time.sleep(0.5)

    logger.info(f"Processed: {processed}, API errors: {api_errors}, NLogic available: {nlogic_available}")

    # === Report ===
    lines = [
        f"# 5基合議バックテスト — NLogic追加エッジ検証\n",
        f"**期間**: {since} ~ {until}\n",
        f"**race_type**: {race_type}\n",
        f"**処理レース数**: {processed} (API失敗: {api_errors})\n",
        f"**NLogic予測取得**: {nlogic_available}/{processed}\n",
        f"**生成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"\n---\n\n",
    ]

    # Overall comparison
    lines.append("## 1. 全体比較 (2-5エンジン一致, 単勝¥100)\n\n")
    for label, data in [
        ("4基合議 (D/I/V/M)", results_4eng),
        ("5基合議 (D/I/V/M/N)", results_5eng),
        ("NLogic単独", results_nlogic_solo),
    ]:
        d = aggregate(data, label)
        lines.append(f"- {fmt(d)}\n")

    # Consensus level breakdown
    lines.append("\n## 2. 合議度別比較\n\n")
    lines.append("### 4基合議\n")
    lines.append("| 合議度 | n | 的中率 | 回収率 |\n|---|---|---|---|\n")
    for cnt in [2, 3, 4]:
        sub = [r for r in results_4eng if r['cons_count'] == cnt]
        if sub:
            d = aggregate(sub, f"{cnt}/4")
            lines.append(f"| {cnt}/4 | {d['n']} | {d['hit_pct']:.1f}% | {d['recov']:.1f}% |\n")

    lines.append("\n### 5基合議\n")
    lines.append("| 合議度 | n | 的中率 | 回収率 |\n|---|---|---|---|\n")
    for cnt in [2, 3, 4, 5]:
        sub = [r for r in results_5eng if r['cons_count'] == cnt]
        if sub:
            d = aggregate(sub, f"{cnt}/5")
            lines.append(f"| {cnt}/5 | {d['n']} | {d['hit_pct']:.1f}% | {d['recov']:.1f}% |\n")

    # Venue breakdown
    lines.append("\n## 3. 会場別 (2+一致)\n\n")
    lines.append("| 会場 | 4基n | 4基回収 | 5基n | 5基回収 | 差分 |\n")
    lines.append("|---|---|---|---|---|---|\n")
    venues = sorted(set(r['venue'] for r in results_4eng + results_5eng))
    for v in venues:
        sub4 = [r for r in results_4eng if r['venue'] == v]
        sub5 = [r for r in results_5eng if r['venue'] == v]
        if len(sub4) < 20:
            continue
        d4 = aggregate(sub4, v)
        d5 = aggregate(sub5, v)
        diff = d5['recov'] - d4['recov'] if d5['n'] > 0 else 0
        diff_str = f"{diff:+.1f}pt" if d5['n'] > 0 else "N/A"
        lines.append(f"| {v} | {d4['n']} | {d4['recov']:.1f}% | {d5['n']} | {d5['recov']:.1f}% | {diff_str} |\n")

    # Layer 1 specific (NAR only)
    if race_type == 'nar':
        lines.append("\n## 4. Layer 1 条件 (強会場v4 + 6人気 + 2-3一致)\n\n")
        l1_4 = [r for r in results_4eng
                if r['venue'] in GOLDEN_STRONG_VENUES_V4
                and r.get('pop') == 6
                and 2 <= r['cons_count'] <= 3
                and r['weekday'] in ('月', '火', '水', '木', '金')]
        l1_5 = [r for r in results_5eng
                if r['venue'] in GOLDEN_STRONG_VENUES_V4
                and r.get('pop') == 6
                and 2 <= r['cons_count'] <= 3
                and r['weekday'] in ('月', '火', '水', '木', '金')]
        lines.append(f"- {fmt(aggregate(l1_4, 'Layer1 4基'))}\n")
        lines.append(f"- {fmt(aggregate(l1_5, 'Layer1 5基'))}\n")

    # NLogic correlation with existing engines
    lines.append("\n## 5. NLogic と既存エンジンの相関\n\n")
    lines.append("NLogic top1 が各エンジン top1 と一致する割合:\n\n")
    agree_counts = {eng: 0 for eng in ENGINES_4}
    total_compare = 0
    # We need to re-process to check correlation — use stored predictions
    # (This section is best populated during the main loop; placeholder for now)
    lines.append("*(バックテスト実行後に自動計算されます)*\n")

    # Write report
    out_path = os.path.join(DOCS_DIR, f"audit_5engine_backtest_{race_type}_{datetime.now().strftime('%Y%m%d')}.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    logger.info(f"Report → {out_path}")

    # Console summary
    print("\n" + "=" * 60)
    print("=== 5基合議バックテスト結果サマリ ===")
    print("=" * 60)
    print(fmt(aggregate(results_4eng, "4基合議全体")))
    print(fmt(aggregate(results_5eng, "5基合議全体")))
    print(fmt(aggregate(results_nlogic_solo, "NLogic単独")))
    if race_type == 'nar':
        print(fmt(aggregate(l1_4, "Layer1 4基")))
        print(fmt(aggregate(l1_5, "Layer1 5基")))
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="5基合議バックテスト")
    parser.add_argument("--race-type", choices=["nar", "jra"], default="nar")
    parser.add_argument("--since", default="20260301", help="YYYYMMDD")
    parser.add_argument("--until", default="20260430", help="YYYYMMDD")
    args = parser.parse_args()
    run_backtest(args.race_type, args.since, args.until)


if __name__ == '__main__':
    main()
