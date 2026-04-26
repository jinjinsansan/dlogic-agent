#!/usr/bin/env python3
"""Phase B-1: Place (複勝) recovery rate analysis.

For each engine S-rank pick, compute place hit rate and place payout
recovery, segmented by engine, race_type, popularity, consensus level.
"""
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime

# Read Supabase creds from VPS env
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


def get_place_payout(payouts: dict, horse_number: int) -> int:
    """payouts.place 配列から指定馬番の複勝払戻を取得。"""
    for entry in (payouts.get("place") or []):
        if horse_number in (entry.get("combo") or []):
            return entry.get("payout") or 0
    return 0


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,hit_win,hit_place")
    logger.info(f"  {len(hits)} rows")

    logger.info("loading race_results...")
    results = fetch_all(sb, "race_results",
        select="race_id,result_json,status")
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
    logger.info(f"  unique races with odds: {len(latest_odds)}")

    # ---- Per-engine place stats ----
    eng_stats = defaultdict(lambda: {
        "races": 0, "place_hits": 0,
        "races_with_payout": 0, "total_payout": 0,
    })
    eng_pop_stats = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "hits": 0, "payout": 0,
    }))
    eng_type_stats = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "hits": 0, "payout": 0,
    }))

    for h in hits:
        rid = h["race_id"]
        result = by_rid.get(rid)
        if not result: continue
        payouts = (result["result_json"].get("payouts") or {})
        if not payouts.get("place"): continue  # PCKEIBAデータ未着レース除外

        eng = h["engine"]
        pick = h["top1_horse"]
        rtype = h.get("race_type", "?")

        s = eng_stats[eng]
        s["races"] += 1
        s["races_with_payout"] += 1

        place_payout = get_place_payout(payouts, pick)
        if h.get("hit_place"):
            s["place_hits"] += 1
        if place_payout > 0:
            s["total_payout"] += place_payout

        # Race type
        st = eng_type_stats[eng][rtype]
        st["races"] += 1
        if h.get("hit_place"): st["hits"] += 1
        st["payout"] += place_payout

        # Popularity bucket
        odds_map = latest_odds.get((h["date"], h["venue"], h["race_number"]))
        if odds_map and pick in odds_map:
            sp = sorted(odds_map.items(), key=lambda x: x[1])
            pop = next((i for i, (hn, _) in enumerate(sp, 1) if hn == pick), None)
            if pop:
                bucket = pop if pop <= 5 else ("6-8" if pop <= 8 else "9+")
                ps = eng_pop_stats[eng][bucket]
                ps["races"] += 1
                if h.get("hit_place"): ps["hits"] += 1
                ps["payout"] += place_payout

    # ---- Reports ----
    engines = ["dlogic", "ilogic", "viewlogic", "metalogic"]

    print("\n" + "=" * 70)
    print("ENGINE PLACE (複勝) RECOVERY — S-rank only, 100yen flat")
    print("=" * 70)
    print(f"{'engine':<10} {'races':>7} {'place':>6} {'place%':>7} {'payout':>10} {'recov%':>7}")
    for eng in engines:
        s = eng_stats[eng]
        n = s["races"]
        if n == 0: continue
        pr = s["place_hits"] / n * 100
        rec = s["total_payout"] / (n * 100) * 100
        print(f"{eng:<10} {n:>7} {s['place_hits']:>6} {pr:>6.1f}% {s['total_payout']:>10} {rec:>6.1f}%")

    print("\n" + "=" * 70)
    print("BY RACE TYPE")
    print("=" * 70)
    for eng in engines:
        for rt in ["jra", "nar"]:
            st = eng_type_stats[eng][rt]
            n = st["races"]
            if n == 0: continue
            pr = st["hits"] / n * 100
            rec = st["payout"] / (n * 100) * 100
            print(f"  [{eng:<9}][{rt}] races={n:>5} place={pr:>5.1f}% recovery={rec:>6.1f}%")

    print("\n" + "=" * 70)
    print("BY POPULARITY BUCKET (place recovery)")
    print("=" * 70)
    for eng in engines:
        print(f"\n  [{eng}]")
        print(f"    {'pop':<5} {'races':>6} {'place%':>7} {'recov%':>7}")
        for b in [1, 2, 3, 4, 5, "6-8", "9+"]:
            ps = eng_pop_stats[eng].get(b)
            if not ps or ps["races"] == 0: continue
            n = ps["races"]
            pr = ps["hits"] / n * 100
            rec = ps["payout"] / (n * 100) * 100
            print(f"    {str(b):<5} {n:>6} {pr:>6.1f}% {rec:>6.1f}%")

    # ---- Consensus × place ----
    print("\n" + "=" * 70)
    print("CONSENSUS × PLACE — 信頼度高さ別の複勝回収")
    print("=" * 70)

    # Group by race for consensus
    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    cons_stats = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "hits": 0, "payout": 0,
    }))

    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        result = by_rid.get(rid)
        if not result: continue
        payouts = (result["result_json"].get("payouts") or {})
        if not payouts.get("place"): continue

        picks = [r["top1_horse"] for r in eng_rows.values()]
        cnt = Counter(picks)
        cons_horse, cons_count = cnt.most_common(1)[0]

        any_row = next(iter(eng_rows.values()))
        odds_map = latest_odds.get((any_row["date"], any_row["venue"], any_row["race_number"]))
        if not odds_map or cons_horse not in odds_map: continue
        sp = sorted(odds_map.items(), key=lambda x: x[1])
        pop = next((i for i, (hn, _) in enumerate(sp, 1) if hn == cons_horse), None)
        if not pop: continue
        bucket = pop if pop <= 5 else ("6-8" if pop <= 8 else "9+")

        result_set = {any_row["result_1st"] if "result_1st" in any_row else None,
                      any_row["result_2nd"] if "result_2nd" in any_row else None,
                      any_row["result_3rd"] if "result_3rd" in any_row else None}
        # Actually check via top3 in result_json
        top3 = result["result_json"].get("top3") or []
        top3_nums = {t.get("horse_number") for t in top3}
        placed = cons_horse in top3_nums

        place_payout = get_place_payout(payouts, cons_horse)

        s = cons_stats[cons_count][bucket]
        s["races"] += 1
        if placed: s["hits"] += 1
        s["payout"] += place_payout

    for lv in [4, 3, 2, 1]:
        if lv not in cons_stats: continue
        print(f"\n  [{lv}/4 一致]")
        print(f"    {'pop':<5} {'races':>6} {'place%':>7} {'recov%':>7}")
        for b in [1, 2, 3, 4, 5, "6-8", "9+"]:
            s = cons_stats[lv].get(b)
            if not s or s["races"] == 0: continue
            n = s["races"]
            pr = s["hits"] / n * 100
            rec = s["payout"] / (n * 100) * 100
            print(f"    {str(b):<5} {n:>6} {pr:>6.1f}% {rec:>6.1f}%")


if __name__ == "__main__":
    main()
