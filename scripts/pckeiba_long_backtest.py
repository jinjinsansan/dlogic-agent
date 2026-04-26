#!/usr/bin/env python3
"""Long-term backtest using PCKEIBA data alone (no engine predictions).

Tests whether the "火水木 + 強5会場 + 6-12頭 + 5-8人気" filter pattern
is statistically significant across multi-year data, and discovers
other high-recovery segments via grid search.

Outputs a markdown report under docs/.

Usage:
    python scripts/pckeiba_long_backtest.py [--since YYYY] [--years N]
"""
import argparse
import csv
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime

import psycopg2

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PCKEIBA_CONFIG = {
    "host": "127.0.0.1", "port": 5432, "database": "pckeiba",
    "user": "postgres", "password": "postgres",
}

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")
SCHEDULE_PATHS = [
    os.path.join(PROJECT_DIR, "data", "nar_schedule_master_2020_2026.json"),
    r"E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json",
]

JRA_VENUES = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟',
    '05': '東京', '06': '中山', '07': '中京', '08': '京都',
    '09': '阪神', '10': '小倉',
}
NAR_VENUES = {
    '83': '帯広', '30': '門別', '35': '盛岡', '36': '水沢',
    '45': '浦和', '43': '船橋', '42': '大井', '44': '川崎',
    '46': '金沢', '47': '笠松', '48': '名古屋',
    '50': '園田', '51': '姫路', '54': '高知', '55': '佐賀',
}
NANKAN_CODES = {'42', '43', '44', '45'}
REGION_GROUPS = [
    {'35', '36'}, {'46', '47', '48'}, {'50', '51'},
    {'54', '55'}, {'30', '83'},
]
STRONG_5 = {"園田", "水沢", "高知", "笠松", "金沢"}


def load_schedule_master():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return None


def correct_nar_venue(nen, tsukihi, code, schedule):
    if not schedule or 'schedule_data' not in schedule:
        return code
    race_date = f"{nen}{tsukihi}"
    day_venues = schedule['schedule_data'].get(race_date, [])
    if not day_venues: return code
    if len(day_venues) == 1: return day_venues[0]
    if code in day_venues: return code
    if code in NANKAN_CODES:
        n_on_day = [c for c in day_venues if c in NANKAN_CODES]
        if len(n_on_day) == 1: return n_on_day[0]
    for group in REGION_GROUPS:
        if code in group:
            cands = [c for c in day_venues if c in group]
            if len(cands) == 1: return cands[0]
            break
    return code


def pop_bucket(ninki):
    """Convert tansho_ninkijun (str) to bucket label."""
    try:
        n = int(str(ninki).strip())
    except (ValueError, TypeError):
        return None
    if n == 0: return None
    if n <= 5: return str(n)
    if n <= 8: return "6-8"
    return "9+"


def field_bucket(field_size):
    if field_size <= 9: return "6-9"
    if field_size <= 12: return "10-12"
    if field_size <= 15: return "13-15"
    return "16+"


def weekday_label(nen, tsukihi):
    try:
        d = datetime.strptime(nen + tsukihi, "%Y%m%d")
        return ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
    except ValueError:
        return None


def safe_int(v):
    if v is None: return 0
    s = str(v).strip()
    try: return int(s) if s else 0
    except (ValueError, TypeError): return 0


def fetch_and_aggregate(conn, table_se, table_hr, race_type, since_year, schedule):
    """Yield aggregated stats grouped by (weekday, venue, field, pop)."""
    cur = conn.cursor("backtest_cur", cursor_factory=None)
    cur.itersize = 50000

    logger.info(f"  pulling field sizes for {race_type} (since {since_year})...")
    fc = conn.cursor()
    fc.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, COUNT(*)
        FROM {table_se}
        WHERE kaisai_nen::int >= %s
        GROUP BY kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango
    """, (since_year,))
    field_sizes = {}
    for row in fc:
        key = (row[0], row[1], row[2], row[3])
        field_sizes[key] = row[4]
    fc.close()
    logger.info(f"  field sizes for {len(field_sizes)} races")

    logger.info(f"  pulling winning payouts for {race_type}...")
    pc = conn.cursor()
    pc.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b
        FROM {table_hr}
        WHERE kaisai_nen::int >= %s
    """, (since_year,))
    win_payouts = {}
    for row in pc:
        key = (row[0], row[1], row[2], row[3])
        winner = str(row[4]).strip() if row[4] else ""
        payout = safe_int(row[5])
        if winner and payout > 0:
            try:
                winner_n = int(winner)
                win_payouts[key] = (winner_n, payout)
            except ValueError:
                pass
    pc.close()
    logger.info(f"  payouts for {len(win_payouts)} races")

    # Now stream SE rows
    logger.info(f"  streaming {table_se} rows...")
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               umaban, tansho_ninkijun, kakutei_chakujun
        FROM {table_se}
        WHERE kaisai_nen::int >= %s
    """, (since_year,))

    # Aggregator: (weekday, venue_name, field_bucket, pop_bucket) → {races, wins, payout}
    agg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    total = 0

    for row in cur:
        nen, md, code, bango, umaban, ninki, chaku = row
        total += 1
        if total % 500000 == 0:
            logger.info(f"    streamed {total:,} {race_type} rows...")

        wd = weekday_label(nen, md)
        if wd is None: continue

        pb = pop_bucket(ninki)
        if pb is None: continue

        field_key = (nen, md, code, bango)
        fs = field_sizes.get(field_key)
        if fs is None: continue
        if fs < 5: continue  # skip tiny fields
        fb = field_bucket(fs)

        # Venue
        if race_type == "jra":
            venue = JRA_VENUES.get(code)
        else:
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = NAR_VENUES.get(cc)
        if not venue: continue

        # Did this horse win?
        won = False
        payout = 0
        wp = win_payouts.get(field_key)
        if wp:
            winner_n, p = wp
            try:
                if int(str(umaban).strip()) == winner_n:
                    won = True
                    payout = p
            except ValueError:
                pass
        else:
            # No HR record (cancelled etc) — skip
            continue

        # Sanity check: kakutei_chakujun should be '01' if won
        # but trust HR over SE since HR is post-race confirmed

        key = (wd, venue, fb, pb)
        s = agg[key]
        s["races"] += 1
        if won:
            s["wins"] += 1
            s["payout"] += payout

    cur.close()
    logger.info(f"  done. total {race_type} rows: {total:,}, segments: {len(agg)}")

    return agg


def render_report(jra_agg, nar_agg, since_year, output_path):
    lines = []
    lines.append(f"# PCKEIBA 長期バックテスト結果\n")
    lines.append(f"**対象期間**: {since_year}年〜2026年\n")
    lines.append(f"**作成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**目的**: エンジン要素を含まない素朴な統計で「火水木+強5会場+6-12頭+5-8人気」フィルタの長期再現性を検証\n")
    lines.append("\n---\n")

    def aggregate_to_records(agg, race_type):
        records = []
        for (wd, venue, fb, pb), s in agg.items():
            n = s["races"]
            if n == 0: continue
            wins = s["wins"]
            payout = s["payout"]
            invest = n * 100
            recov = payout / invest * 100 if invest else 0
            win_rate = wins / n * 100
            records.append({
                "race_type": race_type, "weekday": wd, "venue": venue,
                "field": fb, "pop": pb, "races": n, "wins": wins,
                "payout": payout, "win_rate": win_rate, "recovery": recov,
            })
        return records

    all_records = aggregate_to_records(jra_agg, "jra") + aggregate_to_records(nar_agg, "nar")
    logger.info(f"total segments: {len(all_records)}")

    # Filter for meaningful sample size
    significant = [r for r in all_records if r["races"] >= 200]
    significant.sort(key=lambda x: x["recovery"], reverse=True)

    # ============ Specific filter check ============
    lines.append("## 1. 既知パターン (火水木+強5会場+6-12頭+5-8人気) の長期検証\n")
    lines.append("| 曜日 | 会場 | 頭数 | 人気 | races | wins | win% | recov% |")
    lines.append("|---|---|---|---|---|---|---|---|")
    target_check = [
        r for r in all_records
        if r["weekday"] in ("火", "水", "木")
        and r["venue"] in STRONG_5
        and r["field"] in ("6-9", "10-12")
        and r["pop"] in ("5", "6-8")
    ]
    target_check.sort(key=lambda x: (x["weekday"], x["venue"], x["field"], x["pop"]))
    sub_total = {"races": 0, "wins": 0, "payout": 0}
    for r in target_check:
        lines.append(f"| {r['weekday']} | {r['venue']} | {r['field']} | {r['pop']} | "
                     f"{r['races']} | {r['wins']} | {r['win_rate']:.1f}% | "
                     f"**{r['recovery']:.1f}%** |")
        sub_total["races"] += r["races"]
        sub_total["wins"] += r["wins"]
        sub_total["payout"] += r["payout"]
    if sub_total["races"]:
        rec = sub_total["payout"] / (sub_total["races"] * 100) * 100
        wr = sub_total["wins"] / sub_total["races"] * 100
        lines.append(f"| **合計** | — | — | — | **{sub_total['races']}** | "
                     f"{sub_total['wins']} | {wr:.1f}% | **{rec:.1f}%** |")

    lines.append("\n→ ここがエンジン無しで100%超なら、'本当に効いてる' のはフィルタ条件で、")
    lines.append("  エンジン要素は補助的だったという可能性が高い。\n")

    # ============ Top recovery segments ============
    lines.append("\n## 2. 全期間で回収率トップ30セグメント (races >= 200)\n")
    lines.append("| race_type | 曜日 | 会場 | 頭数 | 人気 | races | wins | win% | recov% |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in significant[:30]:
        lines.append(f"| {r['race_type']} | {r['weekday']} | {r['venue']} | "
                     f"{r['field']} | {r['pop']} | {r['races']} | {r['wins']} | "
                     f"{r['win_rate']:.1f}% | **{r['recovery']:.1f}%** |")

    # ============ Summary by race_type ============
    lines.append("\n## 3. race_type 別サマリ\n")
    for rt, agg in [("JRA", jra_agg), ("NAR", nar_agg)]:
        races_all = sum(s["races"] for s in agg.values())
        wins_all = sum(s["wins"] for s in agg.values())
        payout_all = sum(s["payout"] for s in agg.values())
        if races_all:
            rec = payout_all / (races_all * 100) * 100
            wr = wins_all / races_all * 100
            lines.append(f"- **{rt}**: bets={races_all:,} wins={wins_all:,} ({wr:.2f}%) recovery={rec:.2f}%")

    # ============ Summary by weekday × race_type ============
    lines.append("\n## 4. 曜日別 × race_type 別サマリ\n")
    lines.append("| race_type | 曜日 | races | wins | win% | recov% |")
    lines.append("|---|---|---|---|---|---|")
    wd_agg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in all_records:
        k = (r["race_type"], r["weekday"])
        s = wd_agg[k]
        s["races"] += r["races"]
        s["wins"] += r["wins"]
        s["payout"] += r["payout"]
    for rt in ["jra", "nar"]:
        for wd in ["月", "火", "水", "木", "金", "土", "日"]:
            s = wd_agg.get((rt, wd))
            if not s or s["races"] == 0: continue
            rec = s["payout"] / (s["races"] * 100) * 100
            wr = s["wins"] / s["races"] * 100
            lines.append(f"| {rt} | {wd} | {s['races']:,} | {s['wins']:,} | {wr:.2f}% | {rec:.2f}% |")

    # ============ Summary by venue ============
    lines.append("\n## 5. 会場別サマリ (人気5-8 限定)\n")
    lines.append("| race_type | 会場 | races | wins | win% | recov% |")
    lines.append("|---|---|---|---|---|---|")
    venue_agg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in all_records:
        if r["pop"] not in ("5", "6-8"): continue
        k = (r["race_type"], r["venue"])
        s = venue_agg[k]
        s["races"] += r["races"]
        s["wins"] += r["wins"]
        s["payout"] += r["payout"]
    venue_records = []
    for (rt, venue), s in venue_agg.items():
        if s["races"] < 100: continue
        venue_records.append({
            "rt": rt, "venue": venue, "races": s["races"],
            "wins": s["wins"], "payout": s["payout"],
            "recovery": s["payout"] / (s["races"] * 100) * 100,
        })
    venue_records.sort(key=lambda x: x["recovery"], reverse=True)
    for v in venue_records:
        wr = v["wins"] / v["races"] * 100
        lines.append(f"| {v['rt']} | {v['venue']} | {v['races']:,} | {v['wins']} | "
                     f"{wr:.2f}% | {v['recovery']:.2f}% |")

    # ============ Summary by popularity ============
    lines.append("\n## 6. 人気別サマリ\n")
    lines.append("| race_type | 人気 | races | wins | win% | recov% |")
    lines.append("|---|---|---|---|---|---|")
    pop_agg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in all_records:
        k = (r["race_type"], r["pop"])
        s = pop_agg[k]
        s["races"] += r["races"]
        s["wins"] += r["wins"]
        s["payout"] += r["payout"]
    for rt in ["jra", "nar"]:
        for pop in ["1", "2", "3", "4", "5", "6-8", "9+"]:
            s = pop_agg.get((rt, pop))
            if not s or s["races"] == 0: continue
            rec = s["payout"] / (s["races"] * 100) * 100
            wr = s["wins"] / s["races"] * 100
            lines.append(f"| {rt} | {pop} | {s['races']:,} | {s['wins']:,} | {wr:.2f}% | {rec:.2f}% |")

    lines.append("\n## 7. 結論案\n")
    lines.append("- このレポートはエンジン要素を一切含まず、人気・曜日・会場・頭数だけで分類")
    lines.append("- 既知パターンの '火水木+強5会場+6-12頭+5-8人気' のセクション1の数字を見て:")
    lines.append("  - 100%超 → エンジン要素は不要。素朴フィルタで十分")
    lines.append("  - 75-99% → エンジン合議が真の "+" 効果")
    lines.append("  - 75%未満 → エンジン合議が圧倒的に効果あり (現在の454%の中核)")
    lines.append("- セクション2の Top30 を見て、JRAでも何か見つかるか確認")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2020", help="開始年 (default: 2020)")
    args = ap.parse_args()

    schedule = load_schedule_master()
    if not schedule:
        logger.warning("no schedule master; NAR venue correction disabled")

    conn = psycopg2.connect(**PCKEIBA_CONFIG)

    logger.info("=" * 60)
    logger.info(f"PCKEIBA long backtest since {args.since}")
    logger.info("=" * 60)

    logger.info("\n[1/2] JRA処理...")
    jra_agg = fetch_and_aggregate(conn, "jvd_se", "jvd_hr", "jra", args.since, schedule)

    logger.info("\n[2/2] NAR処理...")
    nar_agg = fetch_and_aggregate(conn, "nvd_se", "nvd_hr", "nar", args.since, schedule)

    conn.close()

    out_path = os.path.join(DOCS_DIR, f"pckeiba_long_backtest_{args.since}_to_2026.md")
    logger.info(f"\nrendering report → {out_path}")
    render_report(jra_agg, nar_agg, args.since, out_path)
    logger.info(f"DONE. {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
