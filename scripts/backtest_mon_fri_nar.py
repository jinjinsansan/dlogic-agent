#!/usr/bin/env python3
"""月/金 NAR 単独バックテスト — Layer X 候補探索.

目的: 火水木 Layer 1 と並ぶ素材が月単独/金単独に存在するか検証.
基準: n>=80 AND CI下限>=110% AND 月別>=100% (Layer 1 同等)

データソース:
  - Supabase engine_hit_rates (clean filter: created_at <= race_date)
  - VPS PCKEIBA postgres (NAR payouts + popularity)

期間:
  - 1年: 2025-04-27 〜 2026-04-26
  - clean 2ヶ月: 2026-03-01 〜 2026-04-30 (比較用)

出力:
  - docs/weekday_mon_fri_backtest_20260503.md
  - stdout summary

実行: VPS上 (psycopg2 で localhost:5432 PCKEIBA に接続)
  cd /opt/dlogic/linebot && source venv/bin/activate
  python scripts/backtest_mon_fri_nar.py
"""
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, date

import psycopg2
from supabase import create_client


# ============================================================
# Setup
# ============================================================
def load_env_from_vps():
    """Load SUPABASE keys. Try local .env.local first (when run on VPS),
    then fall back to SSH (when run from dev machine)."""
    if os.environ.get('SUPABASE_URL') and os.environ.get('SUPABASE_SERVICE_ROLE_KEY'):
        return
    # Try local .env.local (works when running on VPS)
    for p in ['/opt/dlogic/linebot/.env.local', '.env.local']:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        if k.strip() in ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY'):
                            os.environ.setdefault(k.strip(), v.strip())
            if os.environ.get('SUPABASE_URL'):
                return
    # Fall back to SSH (when running from local dev)
    try:
        out = subprocess.check_output(
            ['ssh', 'root@220.158.24.157',
             'grep -E "^(SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=" /opt/dlogic/linebot/.env.local'],
            text=True, timeout=10,
        )
        for line in out.strip().split('\n'):
            k, v = line.split('=', 1)
            os.environ[k] = v
    except Exception as e:
        print(f"[WARN] could not fetch SUPABASE env: {e}", file=sys.stderr)


load_env_from_vps()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])

# Constants
GOLDEN_STRONG_VENUES_V4 = {"川崎", "船橋", "大井", "浦和", "門別", "笠松"}
GOLDEN_SOUTH_NANKAN = {"川崎", "船橋", "大井", "浦和"}
OLD_STRONG5 = {"園田", "水沢", "高知", "笠松", "金沢"}  # Layer 1 (火水木) と同じ

NAR_VENUES = {'83': '帯広', '30': '門別', '35': '盛岡', '36': '水沢', '45': '浦和', '43': '船橋',
              '42': '大井', '44': '川崎', '46': '金沢', '47': '笠松', '48': '名古屋', '50': '園田',
              '51': '姫路', '54': '高知', '55': '佐賀'}
NANKAN_CODES = {'42', '43', '44', '45'}
REGION_GROUPS = [{'35', '36'}, {'46', '47', '48'}, {'50', '51'}, {'54', '55'}, {'30', '83'}]

PERIOD_1Y = ('2025-04-27', '2026-04-26')
PERIOD_CLEAN = ('2026-03-01', '2026-04-30')


def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule:
        return code
    rd = nen + md
    days = schedule['schedule_data'].get(rd, [])
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
    except Exception:
        return 0


# ============================================================
# Data loaders
# ============================================================
def fetch_engine_hit_rates(gte, lte):
    rows, off = [], 0
    while True:
        res = sb.table('engine_hit_rates') \
            .select('date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at') \
            .gte('date', gte).lte('date', lte) \
            .range(off, off + 999).execute()
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < 1000:
            break
        off += 1000
    return rows


def filter_clean(rows):
    """Drop rows where created_at > race_date (leakage)."""
    out = []
    for r in rows:
        try:
            rd = datetime.strptime(r['date'], '%Y-%m-%d').date()
            cd = datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date()
            if (cd - rd).days <= 0:
                out.append(r)
        except Exception:
            continue
    return out


def load_pckeiba_payouts(year_min='2025'):
    """Load NAR payouts + popularity from VPS PCKEIBA postgres."""
    schedule = None
    for p in ['/opt/dlogic/linebot/data/nar_schedule_master_2020_2026.json',
              'data/nar_schedule_master_2020_2026.json']:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                schedule = json.load(f)
            break

    conn = psycopg2.connect(host='127.0.0.1', port=5432, database='pckeiba',
                            user='postgres', password='postgres')
    cur = conn.cursor()
    cur.execute("SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, "
                "haraimodoshi_tansho_1a, haraimodoshi_tansho_1b "
                f"FROM nvd_hr WHERE kaisai_nen >= '{year_min}'")
    races_pck = {}
    for nen, md, code, bango, ta, tb in cur.fetchall():
        cc = correct_nar_venue(nen, md, code, schedule)
        venue = NAR_VENUES.get(cc)
        if not venue:
            continue
        try:
            rno = int(bango)
        except Exception:
            continue
        winner_str = (ta or '').strip()
        payout = safe_int(tb)
        if not winner_str or winner_str == '00' or payout == 0:
            continue
        try:
            winner = int(winner_str)
        except Exception:
            continue
        date_str = nen + '-' + md[:2] + '-' + md[2:4]
        races_pck[(date_str, venue, rno)] = {'winner': winner, 'payout': payout, 'horses': {}}

    cur2 = conn.cursor("se_cur")
    cur2.itersize = 50000
    cur2.execute("SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, "
                 "umaban, tansho_ninkijun "
                 f"FROM nvd_se WHERE kaisai_nen >= '{year_min}'")
    for nen, md, code, bango, umaban, ninki in cur2:
        cc = correct_nar_venue(nen, md, code, schedule)
        venue = NAR_VENUES.get(cc)
        if not venue:
            continue
        try:
            rno = int(bango)
            h = int(str(umaban).strip())
            pop = int(str(ninki).strip())
        except Exception:
            continue
        date_str = nen + '-' + md[:2] + '-' + md[2:4]
        race = races_pck.get((date_str, venue, rno))
        if race:
            race['horses'][h] = pop
    cur2.close()
    cur.close()
    conn.close()
    return races_pck


# ============================================================
# Evaluation
# ============================================================
def build_evaluated(engine_rows_clean, races_pck):
    by_race = defaultdict(dict)
    race_meta = {}
    for r in engine_rows_clean:
        rid = r['race_id']
        by_race[rid][r['engine']] = (r['top1_horse'], r['top3_horses'] or [])
        race_meta[rid] = (r['date'], r['venue'], r['race_number'], r['race_type'])

    evaluated = []
    for rid, picks in by_race.items():
        if rid not in race_meta:
            continue
        date_iso, venue, rno, rtype = race_meta[rid]
        if rtype != 'nar':
            continue
        pck = races_pck.get((date_iso, venue, rno))
        if not pck:
            continue
        top1_counts = Counter()
        for engine, p in picks.items():
            t1 = p[0]
            if t1:
                top1_counts[t1] += 1
        if not top1_counts:
            continue
        cons_horse, cons_count = top1_counts.most_common(1)[0]
        if cons_count < 2:
            continue
        pop = pck['horses'].get(cons_horse)
        if not pop:
            continue
        try:
            wd = datetime.strptime(date_iso, '%Y-%m-%d').weekday()
        except ValueError:
            continue
        evaluated.append({
            'date': date_iso,
            'venue': venue,
            'race_no': rno,
            'cons_horse': cons_horse,
            'cons_count': cons_count,
            'pop': pop,
            'weekday': wd,  # 0=月..6=日
            'won': pck['winner'] == cons_horse,
            'payout': pck['payout'] if pck['winner'] == cons_horse else 0,
            'total_horses': len(pck['horses']),
        })
    return evaluated


# ============================================================
# Statistics
# ============================================================
def bootstrap_recovery_ci(payouts, n_iter=1000, ci=0.95, seed=42):
    """Return (lo%, hi%) for recovery rate via Bootstrap.

    Each entry in payouts is the per-race outcome payout (0 if lost).
    Investment is 100 yen per race.
    """
    n = len(payouts)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        s = sum(payouts[rng.randint(0, n - 1)] for _ in range(n))
        means.append(s / n)
    means.sort()
    lo_idx = int(n_iter * (1 - ci) / 2)
    hi_idx = int(n_iter * (1 + ci) / 2) - 1
    return means[lo_idx], means[hi_idx]


def aggregate(rows):
    n = len(rows)
    if n == 0:
        return None
    payouts = [r['payout'] for r in rows]
    pay = sum(payouts)
    hits = sum(1 for r in rows if r['won'])
    inv = n * 100
    recov = pay / inv * 100
    win_rate = hits / n * 100
    lo, hi = bootstrap_recovery_ci(payouts)
    return {
        'n': n, 'hits': hits, 'win_rate': win_rate,
        'inv': inv, 'pay': pay, 'profit': pay - inv,
        'recovery': recov,
        'ci_lo': lo, 'ci_hi': hi,
    }


def monthly_recovery(rows):
    """{ '2025-05': recovery%, ... } for stability check."""
    by_month = defaultdict(list)
    for r in rows:
        ym = r['date'][:7]
        by_month[ym].append(r['payout'])
    return {m: sum(p) / (len(p) * 100) * 100 if p else 0 for m, p in by_month.items()}


def all_months_above(monthly, threshold):
    if not monthly:
        return False
    return all(v >= threshold for v in monthly.values())


# ============================================================
# Reporting
# ============================================================
WD_LABEL = ['月', '火', '水', '木', '金', '土', '日']


def fmt_row(label, agg, monthly_rec=None, threshold=100):
    if agg is None:
        return f"| {label} | 0 | – | – | – | – | – |"
    stable = ""
    if monthly_rec:
        ok = all_months_above(monthly_rec, threshold)
        stable = "✓" if ok else "✗"
    return (f"| {label} | {agg['n']} | {agg['win_rate']:.1f}% | {agg['recovery']:.1f}% | "
            f"{agg['ci_lo']:.1f}% | {agg['ci_hi']:.1f}% | {stable} |")


def render_section(title, segments, threshold=100):
    """segments: list of (label, rows)"""
    lines = [f"### {title}", "",
             "| セグメント | n | 勝率 | 回収率 | CI下限 | CI上限 | 月安 |",
             "|---|---:|---:|---:|---:|---:|:---:|"]
    for label, rows in segments:
        agg = aggregate(rows)
        if agg and agg['n'] >= 30:
            mr = monthly_recovery(rows)
            lines.append(fmt_row(label, agg, mr, threshold))
        else:
            lines.append(fmt_row(label, agg))
    lines.append("")
    return '\n'.join(lines)


# ============================================================
# Main
# ============================================================
def run_period(period_label, gte, lte, races_pck):
    print(f"\n[{period_label}] fetching engine_hit_rates {gte}..{lte}", flush=True)
    rows = fetch_engine_hit_rates(gte, lte)
    print(f"  raw: {len(rows)}")
    clean = filter_clean(rows)
    print(f"  clean: {len(clean)}")

    evaluated = build_evaluated(clean, races_pck)
    print(f"  evaluable NAR races (cons_count>=2): {len(evaluated)}")

    md = [f"## {period_label} ({gte} 〜 {lte})", ""]

    # ===========================================================
    # 1. Weekday baseline
    # ===========================================================
    md.append("### 1. 曜日別 baseline (NAR + 2-3 一致, 全会場・人気不問)")
    md.append("")
    md.append("| 曜日 | n | 勝率 | 回収率 | CI下限 | CI上限 |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for wd in range(7):
        sub = [r for r in evaluated if r['weekday'] == wd and 2 <= r['cons_count'] <= 3]
        agg = aggregate(sub)
        if agg:
            md.append(f"| {WD_LABEL[wd]} | {agg['n']} | {agg['win_rate']:.1f}% | "
                      f"{agg['recovery']:.1f}% | {agg['ci_lo']:.1f}% | {agg['ci_hi']:.1f}% |")
    md.append("")

    # ===========================================================
    # 2. 月/金 segments
    # ===========================================================
    target_wds = {'月': [0], '金': [4], '月+金': [0, 4]}

    for wd_label, wd_set in target_wds.items():
        base = [r for r in evaluated if r['weekday'] in wd_set and 2 <= r['cons_count'] <= 3]
        md.append(f"### 2.{wd_label} {wd_label} 単独セグメント")
        md.append("")
        md.append(f"baseline n = {len(base)}")
        md.append("")

        # 2a. 会場大区分
        seg_a = [
            ("全会場 (人気不問, 2-3一致)", base),
            ("南関東4場 (川崎/船橋/大井/浦和)", [r for r in base if r['venue'] in GOLDEN_SOUTH_NANKAN]),
            ("旧強5会場 (園田/水沢/高知/笠松/金沢)", [r for r in base if r['venue'] in OLD_STRONG5]),
            ("強会場v4 (川崎/船橋/大井/浦和/門別/笠松)", [r for r in base if r['venue'] in GOLDEN_STRONG_VENUES_V4]),
        ]
        md.append(render_section("2a. 会場大区分", seg_a))

        # 2b. 人気 bucket
        seg_b = []
        for low, high in [(1, 4), (5, 8), (9, 99)]:
            label = f"{low}-{high if high < 99 else '∞'}人気"
            sub = [r for r in base if r['pop'] and low <= r['pop'] <= high]
            seg_b.append((label, sub))
        md.append(render_section("2b. 人気 bucket (全会場)", seg_b))

        # 2c. 旧強5会場 × 人気 × 合議度 グリッドサーチ (Layer 1 と同形式)
        seg_c = []
        for venues_label, venues in [("旧強5", OLD_STRONG5), ("南関東4", GOLDEN_SOUTH_NANKAN)]:
            for pop_label, pop_range in [("5-8人気", (5, 8)), ("6人気のみ", (6, 6)), ("人気不問", (1, 99))]:
                for cc_label, cc_set in [("2-3一致", {2, 3}), ("3一致のみ", {3}), ("2一致のみ", {2})]:
                    label = f"{venues_label} × {pop_label} × {cc_label}"
                    sub = [r for r in base
                           if r['venue'] in venues
                           and r['pop'] and pop_range[0] <= r['pop'] <= pop_range[1]
                           and r['cons_count'] in cc_set]
                    seg_c.append((label, sub))
        md.append(render_section("2c. グリッドサーチ", seg_c))

        # 2d. 採用候補 (n>=80, CI下限>=110%, 月安定)
        candidates = []
        for label, rows in seg_a + seg_b + seg_c:
            agg = aggregate(rows)
            if not agg or agg['n'] < 80:
                continue
            if agg['ci_lo'] < 110:
                continue
            mr = monthly_recovery(rows)
            if not all_months_above(mr, 90):  # 緩めの月安基準
                continue
            candidates.append((label, agg, mr))
        if candidates:
            md.append(f"### 2.{wd_label}.採用 候補 (n>=80, CI下限>=110%, 月別>=90%)")
            md.append("")
            md.append("| セグメント | n | 回収率 | CI下限 | 月別最低 |")
            md.append("|---|---:|---:|---:|---:|")
            for label, agg, mr in sorted(candidates, key=lambda x: -x[1]['ci_lo']):
                m_min = min(mr.values()) if mr else 0
                md.append(f"| {label} | {agg['n']} | {agg['recovery']:.1f}% | "
                          f"{agg['ci_lo']:.1f}% | {m_min:.1f}% |")
            md.append("")
        else:
            md.append(f"### 2.{wd_label}.採用 候補")
            md.append("")
            md.append(f"**該当なし** ({wd_label}単独で n>=80 AND CI下限>=110% AND 月別>=90% を満たすセグメントは見つからず)")
            md.append("")

    return '\n'.join(md)


def main():
    print("=" * 78)
    print("月/金 NAR 単独バックテスト 開始")
    print("=" * 78, flush=True)

    print("\nloading PCKEIBA payouts (year >= 2025)...", flush=True)
    races_pck = load_pckeiba_payouts(year_min='2025')
    print(f"  loaded {len(races_pck)} NAR races")

    md_parts = [
        "# 月/金 NAR 単独バックテスト",
        f"**生成**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "**目的**: 火水木 Layer 1 と並ぶ月単独/金単独の素材を探索",
        "**採用基準**: n>=80 AND CI下限>=110% AND 月別>=90%",
        "**手法**: Bootstrap 1000回 95%CI, leakage除去 clean, 単勝¥100",
        "",
        "## サマリー",
        "",
        "詳細は各期間セクション参照。Section 2.{月,金,月+金}.採用 が最終候補。",
        "",
        "---",
        "",
    ]

    for label, (gte, lte) in [
        ("1年データ", PERIOD_1Y),
        ("clean 2ヶ月", PERIOD_CLEAN),
    ]:
        md_parts.append(run_period(label, gte, lte, races_pck))
        md_parts.append("\n---\n")

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'docs', f'weekday_mon_fri_backtest_{datetime.now().strftime("%Y%m%d")}.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_parts))
    print(f"\n[OK] report: {out_path}")


if __name__ == "__main__":
    main()
