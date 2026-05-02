#!/usr/bin/env python3
"""5基合議バックテスト Step 2: VPS で predictions API を叩いて 5基合議を評価.

Step 1 で生成した JSON を読み、各レースに対して
  http://localhost:8000/api/v2/predictions/newspaper
を呼び出して 5 エンジン (dlogic/ilogic/viewlogic/metalogic/nlogic) の
top1/top3 を取得、4基合議 vs 5基合議の回収率を比較する。

VPS 上で実行:
    cd /opt/dlogic/linebot
    source venv/bin/activate
    python scripts/audit_5eng_step2_predict.py \\
        --input data/5eng_races_nar_20260301_20260430.json

出力: docs/audit_5engine_backtest_{race_type}_{YYYYMMDD}.md
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

import requests

random.seed(42)

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")

DLOGIC_API_URL = os.getenv("DLOGIC_API_URL", "http://localhost:8000")

ENGINES_4 = ("dlogic", "ilogic", "viewlogic", "metalogic")
ENGINES_5 = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")

GOLDEN_STRONG_VENUES_V4 = {"川崎", "船橋", "大井", "浦和", "門別", "笠松"}


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------
def get_predictions(payload):
    """Call backend /api/v2/predictions/newspaper for 5-engine predictions."""
    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}/api/v2/predictions/newspaper",
            json=payload, timeout=90,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        return None, str(e)

    out = {}
    for eng in ENGINES_5:
        raw = body.get(eng)
        if isinstance(raw, list) and raw:
            try:
                out[eng] = [int(x) for x in raw if x][:5]
            except (ValueError, TypeError):
                continue
    return out, None


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------
def evaluate_consensus(preds, winner, payout, pop_map, venue, weekday, engines):
    """Evaluate a consensus bet using the given engine set."""
    top1_counts = Counter()
    for eng in engines:
        picks = preds.get(eng)
        if not picks:
            continue
        top1_counts[picks[0]] += 1

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
        'pop': pop_map.get(str(cons_horse)),
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
        return {'label': label, 'n': 0, 'inv': 0, 'pay': 0, 'profit': 0,
                'hits': 0, 'hit_pct': 0, 'recov': 0, 'ci_lo': None, 'ci_hi': None}
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def run_backtest(records, race_type, since, until):
    results_4eng = []
    results_5eng = []
    results_nlogic_solo = []
    nlogic_available = 0
    api_errors = 0
    processed = 0

    # NLogic と既存エンジンの相関集計
    agree_with_dlogic = 0
    agree_with_ilogic = 0
    agree_with_viewlogic = 0
    agree_with_metalogic = 0
    agree_total = 0

    total = len(records)

    for i, rec in enumerate(records):
        if i % 100 == 0:
            logger.info(f"Processing {i}/{total} ...")

        meta = rec['meta']
        result = rec['result']
        pop_map = rec['pop_map']
        winner = result['winner']
        payout = result['payout']
        weekday = meta.get('weekday', '?')

        preds, err = get_predictions(rec['payload'])
        if not preds:
            api_errors += 1
            if api_errors <= 5:
                logger.warning(f"API error #{api_errors}: {err}")
            continue
        processed += 1

        # 4-engine consensus
        ev4 = evaluate_consensus(preds, winner, payout, pop_map, meta['venue'], weekday, ENGINES_4)
        if ev4 and ev4['cons_count'] >= 2:
            results_4eng.append(ev4)

        # 5-engine consensus + NLogic solo + 相関
        if 'nlogic' in preds and preds['nlogic']:
            nlogic_available += 1

            ev5 = evaluate_consensus(preds, winner, payout, pop_map, meta['venue'], weekday, ENGINES_5)
            if ev5 and ev5['cons_count'] >= 2:
                results_5eng.append(ev5)

            nl_top1 = preds['nlogic'][0]
            nl_won = (nl_top1 == winner)
            results_nlogic_solo.append({
                'cons_horse': nl_top1,
                'cons_count': 1,
                'won': nl_won,
                'payout': payout if nl_won else 0,
                'pop': pop_map.get(str(nl_top1)),
                'venue': meta['venue'],
                'weekday': weekday,
            })

            # 相関 (NLogic top1 が他エンジン top1 と一致するか)
            agree_total += 1
            for eng, counter in [
                ('dlogic', 'agree_with_dlogic'),
                ('ilogic', 'agree_with_ilogic'),
                ('viewlogic', 'agree_with_viewlogic'),
                ('metalogic', 'agree_with_metalogic'),
            ]:
                if eng in preds and preds[eng] and preds[eng][0] == nl_top1:
                    if eng == 'dlogic': agree_with_dlogic += 1
                    elif eng == 'ilogic': agree_with_ilogic += 1
                    elif eng == 'viewlogic': agree_with_viewlogic += 1
                    elif eng == 'metalogic': agree_with_metalogic += 1

        # rate limit
        if processed % 50 == 0 and processed > 0:
            time.sleep(0.5)

    logger.info(
        f"Processed: {processed}, API errors: {api_errors}, "
        f"NLogic available: {nlogic_available}"
    )

    # === Report ===
    lines = [
        "# 5基合議バックテスト — NLogic追加エッジ検証\n",
        "\n",
        f"**期間**: {since} ~ {until}\n",
        f"**race_type**: {race_type}\n",
        f"**処理レース数**: {processed} (API失敗: {api_errors})\n",
        f"**NLogic予測取得**: {nlogic_available}/{processed}\n",
        f"**生成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        "\n---\n\n",
    ]

    # 1. 全体比較
    lines.append("## 1. 全体比較 (2+エンジン一致, 単勝¥100)\n\n")
    for label, data in [
        ("4基合議 (D/I/V/M)", results_4eng),
        ("5基合議 (D/I/V/M/N)", results_5eng),
        ("NLogic単独", results_nlogic_solo),
    ]:
        d = aggregate(data, label)
        lines.append(f"- {fmt(d)}\n")

    # 2. 合議度別
    lines.append("\n## 2. 合議度別比較\n\n")
    lines.append("### 4基合議\n\n")
    lines.append("| 合議度 | n | 的中率 | 回収率 |\n|---|---|---|---|\n")
    for cnt in [2, 3, 4]:
        sub = [r for r in results_4eng if r['cons_count'] == cnt]
        if sub:
            d = aggregate(sub, f"{cnt}/4")
            lines.append(f"| {cnt}/4 | {d['n']} | {d['hit_pct']:.1f}% | {d['recov']:.1f}% |\n")

    lines.append("\n### 5基合議\n\n")
    lines.append("| 合議度 | n | 的中率 | 回収率 |\n|---|---|---|---|\n")
    for cnt in [2, 3, 4, 5]:
        sub = [r for r in results_5eng if r['cons_count'] == cnt]
        if sub:
            d = aggregate(sub, f"{cnt}/5")
            lines.append(f"| {cnt}/5 | {d['n']} | {d['hit_pct']:.1f}% | {d['recov']:.1f}% |\n")

    # 3. 会場別
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
        lines.append(
            f"| {v} | {d4['n']} | {d4['recov']:.1f}% | "
            f"{d5['n']} | {d5['recov']:.1f}% | {diff_str} |\n"
        )

    # 4. Layer 1 条件 (NAR のみ)
    if race_type == 'nar':
        lines.append("\n## 4. Layer 1 条件 (強会場v4 + 6人気 + 2-3一致 + 月-金)\n\n")
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

    # 5. NLogic と既存エンジンの top1 一致率
    lines.append("\n## 5. NLogic と既存エンジンの top1 一致率\n\n")
    if agree_total > 0:
        lines.append("| 比較対象 | 一致 | 一致率 |\n|---|---|---|\n")
        for label, count in [
            ("Dlogic", agree_with_dlogic),
            ("Ilogic", agree_with_ilogic),
            ("ViewLogic", agree_with_viewlogic),
            ("MetaLogic", agree_with_metalogic),
        ]:
            pct = count / agree_total * 100
            lines.append(f"| NLogic vs {label} | {count}/{agree_total} | {pct:.1f}% |\n")
        lines.append("\n*一致率が高いエンジンほど NLogic と類似。低いほど独立した観点を提供。*\n")
    else:
        lines.append("*NLogic 予測なし*\n")

    # Write report
    out_path = os.path.join(
        DOCS_DIR, f"audit_5engine_backtest_{race_type}_{datetime.now().strftime('%Y%m%d')}.md"
    )
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    logger.info(f"Report → {out_path}")

    # Console summary
    print("\n" + "=" * 60)
    print("=== 5基合議バックテスト結果サマリ ===")
    print("=" * 60)
    print(fmt(aggregate(results_4eng, "4基合議全体 (2+一致)")))
    print(fmt(aggregate(results_5eng, "5基合議全体 (2+一致)")))
    print(fmt(aggregate(results_nlogic_solo, "NLogic単独")))
    if race_type == 'nar':
        print(fmt(aggregate(l1_4, "Layer1 4基 (強会場+6人気+2-3一致+月-金)")))
        print(fmt(aggregate(l1_5, "Layer1 5基 (強会場+6人気+2-3一致+月-金)")))
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="5基合議バックテスト Step 2: VPS API → レポート")
    parser.add_argument("--input", required=True, help="Step 1 が出力した JSON path")
    parser.add_argument("--race-type", default=None, help="auto-detect from JSON if omitted")
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error(f"Input not found: {args.input}")
        sys.exit(1)

    logger.info(f"Loading {args.input} ...")
    with open(args.input, encoding="utf-8") as f:
        records = json.load(f)
    logger.info(f"Loaded {len(records)} race records")

    if not records:
        logger.error("Empty input")
        sys.exit(1)

    # Auto-detect race_type / since / until from filename or records
    race_type = args.race_type
    if not race_type:
        race_type = records[0]['meta'].get('race_type', 'nar')

    fname = os.path.basename(args.input)
    since = args.since or (fname.split('_')[3] if len(fname.split('_')) >= 5 else 'unknown')
    until = args.until or (fname.split('_')[4].replace('.json', '') if len(fname.split('_')) >= 5 else 'unknown')

    run_backtest(records, race_type, since, until)


if __name__ == "__main__":
    main()
