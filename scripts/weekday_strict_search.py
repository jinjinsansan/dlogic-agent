#!/usr/bin/env python3
"""Search for "曜日別厳格" patterns in 6-week engine_hit_rates.

For each weekday (especially 月/金/土/日), find segment combinations
where engine consensus achieves 100%+ recovery.

Focus: which (venue × field × pop × consensus) cells produce profit
on each weekday separately.
"""
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime

out = subprocess.check_output(
    ['ssh', 'root@220.158.24.157',
     'grep -E "^(SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=" /opt/dlogic/linebot/.env.local'],
    text=True, timeout=10,
)
for line in out.strip().split('\n'):
    k, v = line.split('=', 1)
    os.environ[k] = v

from supabase import create_client

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_all(sb, table, select="*", chunk=1000, gte=None):
    rows, offset = [], 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items():
                q = q.gte(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < chunk: break
        offset += chunk
    return rows


def field_bucket(n):
    if n <= 9: return "6-9"
    if n <= 12: return "10-12"
    if n <= 15: return "13-15"
    return "16+"


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,result_1st,result_2nd,result_3rd")
    logger.info(f"  {len(hits)} rows")

    logger.info("loading race_results...")
    results = fetch_all(sb, "race_results", select="race_id,result_json,winner_number,win_payout,status")
    by_rid = {}
    for r in results:
        if r.get("status") != "finished": continue
        rj = r.get("result_json")
        if isinstance(rj, str):
            try: rj = json.loads(rj)
            except: rj = {}
        r["result_json"] = rj or {}
        by_rid[r["race_id"]] = r
    logger.info(f"  {len(by_rid)} finished")

    logger.info("loading odds_snapshots...")
    odds_rows = fetch_all(sb, "odds_snapshots",
        select="race_date,venue,race_number,odds_data,snapshot_at",
        gte={"race_date": "2026-03-11"})
    latest_at, latest_odds = {}, {}
    for o in odds_rows:
        key = (o["race_date"], o["venue"], o["race_number"])
        ts = o["snapshot_at"]
        if key not in latest_at or ts > latest_at[key]:
            latest_at[key] = ts
            data = o["odds_data"]
            if isinstance(data, str):
                try: data = json.loads(data)
                except: continue
            try:
                latest_odds[key] = {int(k): float(v) for k, v in (data or {}).items() if v}
            except: pass
    logger.info(f"  {len(latest_odds)} odds")

    # Group by race
    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    # Aggregate per race
    races_data = []
    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        result = by_rid.get(rid)
        if not result: continue

        any_row = next(iter(eng_rows.values()))
        date_iso = any_row["date"]
        venue = any_row["venue"]
        race_num = any_row["race_number"]
        race_type = any_row["race_type"]

        try:
            wd_idx = datetime.strptime(date_iso, "%Y-%m-%d").weekday()
        except ValueError:
            continue
        wd = ["月", "火", "水", "木", "金", "土", "日"][wd_idx]

        rj = result.get("result_json") or {}
        total_horses = rj.get("total_horses") or 0
        if total_horses == 0:
            continue

        odds_map = latest_odds.get((date_iso, venue, race_num))
        if not odds_map:
            continue

        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        if cons_horse not in odds_map:
            continue
        sp = sorted(odds_map.items(), key=lambda x: x[1])
        pop_rank = next((i for i, (hn, _) in enumerate(sp, 1) if hn == cons_horse), None)
        if not pop_rank:
            continue

        if pop_rank <= 5:
            pop_bucket = str(pop_rank)
        elif pop_rank <= 8:
            pop_bucket = "6-8"
        else:
            pop_bucket = "9+"

        winner = result.get("winner_number")
        win_payout = result.get("win_payout") or 0
        won = (cons_horse == winner)
        profit = (win_payout - 100) if won else -100

        races_data.append({
            "wd": wd,
            "venue": venue,
            "race_type": race_type,
            "field_bucket": field_bucket(total_horses),
            "pop_bucket": pop_bucket,
            "cons_count": cons_count,
            "won": won,
            "payout": win_payout if won else 0,
            "profit": profit,
        })

    logger.info(f"enriched races: {len(races_data)}")

    # ============================================================
    # Search 1: pop × cons × wd (no venue filter)
    # ============================================================
    print("\n" + "=" * 78)
    print("曜日別 × pop × consensus_count (会場フィルタなし、min 30レース)")
    print("=" * 78)
    seg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in races_data:
        key = (r["wd"], r["pop_bucket"], r["cons_count"])
        s = seg[key]
        s["races"] += 1
        if r["won"]:
            s["wins"] += 1
            s["payout"] += r["payout"]

    print(f"  {'wd':<3} {'pop':<5} {'cons':<5} {'races':>6} {'win%':>6} {'recov%':>7}")
    rows = []
    for (wd, pop, cc), s in seg.items():
        n = s["races"]
        if n < 30: continue
        rec = s["payout"] / (n * 100) * 100 if n else 0
        rows.append((wd, pop, cc, n, s["wins"], s["wins"]/n*100 if n else 0, rec))
    rows.sort(key=lambda x: x[6], reverse=True)
    for wd, pop, cc, n, wins, wr, rec in rows[:30]:
        marker = " 🚀" if rec >= 150 else (" ✅" if rec >= 100 else "")
        print(f"  {wd:<3} {pop:<5} {cc:<5} {n:>6} {wr:>5.1f}% {rec:>6.1f}%{marker}")

    # ============================================================
    # Search 2: per weekday top patterns (venue × field × pop × cons)
    # ============================================================
    print("\n" + "=" * 78)
    print("月/金/土/日の TOP10 セグメント (min 15レース)")
    print("=" * 78)

    per_wd = defaultdict(list)
    seg2 = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in races_data:
        key = (r["wd"], r["race_type"], r["venue"], r["field_bucket"], r["pop_bucket"], r["cons_count"])
        s = seg2[key]
        s["races"] += 1
        if r["won"]:
            s["wins"] += 1
            s["payout"] += r["payout"]
    for (wd, rt, venue, fb, pop, cc), s in seg2.items():
        n = s["races"]
        if n < 15: continue
        rec = s["payout"] / (n * 100) * 100 if n else 0
        per_wd[wd].append({
            "rt": rt, "venue": venue, "fb": fb, "pop": pop, "cc": cc,
            "n": n, "wins": s["wins"], "rec": rec,
        })

    for wd in ["月", "火", "水", "木", "金", "土", "日"]:
        items = sorted(per_wd.get(wd, []), key=lambda x: x["rec"], reverse=True)[:10]
        if not items: continue
        print(f"\n  [{wd}曜日 TOP10]")
        print(f"    {'rt':<4} {'venue':<7} {'field':<6} {'pop':<5} {'cc':<3} {'races':>6} {'win%':>6} {'recov%':>7}")
        for it in items:
            marker = " 🚀" if it["rec"] >= 150 else (" ✅" if it["rec"] >= 100 else "")
            wr = it["wins"]/it["n"]*100
            print(f"    {it['rt']:<4} {it['venue']:<7} {it['fb']:<6} {it['pop']:<5} {it['cc']:<3} {it['n']:>6} {wr:>5.1f}% {it['rec']:>6.1f}%{marker}")

    # ============================================================
    # Search 3: 曜日 × pop only (sample size large)
    # ============================================================
    print("\n" + "=" * 78)
    print("曜日 × pop_bucket のみ (大サンプル)")
    print("=" * 78)
    pop_seg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in races_data:
        key = (r["wd"], r["pop_bucket"])
        s = pop_seg[key]
        s["races"] += 1
        if r["won"]:
            s["wins"] += 1
            s["payout"] += r["payout"]
    print(f"  {'wd':<3} {'pop':<5} {'races':>6} {'win%':>6} {'recov%':>7}")
    for wd in ["月", "火", "水", "木", "金", "土", "日"]:
        for pop in ["1", "2", "3", "4", "5", "6-8", "9+"]:
            s = pop_seg.get((wd, pop))
            if not s or s["races"] == 0: continue
            n = s["races"]
            rec = s["payout"] / (n * 100) * 100
            wr = s["wins"]/n*100
            marker = " ✅" if rec >= 100 else ""
            print(f"  {wd:<3} {pop:<5} {n:>6} {wr:>5.1f}% {rec:>6.1f}%{marker}")

    # ============================================================
    # Per-weekday summary across all consensus patterns
    # ============================================================
    print("\n" + "=" * 78)
    print("曜日別 全体集計 (合議制ありの全レース)")
    print("=" * 78)
    wd_seg = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
    for r in races_data:
        s = wd_seg[r["wd"]]
        s["races"] += 1
        if r["won"]:
            s["wins"] += 1
            s["payout"] += r["payout"]
    for wd in ["月", "火", "水", "木", "金", "土", "日"]:
        s = wd_seg.get(wd)
        if not s or s["races"] == 0: continue
        n = s["races"]
        rec = s["payout"] / (n * 100) * 100
        wr = s["wins"]/n*100
        print(f"  {wd}: races={n} win%={wr:.1f}% recov%={rec:.1f}%")


if __name__ == "__main__":
    main()
