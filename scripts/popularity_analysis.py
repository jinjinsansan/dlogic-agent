#!/usr/bin/env python3
"""Step 2: Engine vs popularity analysis.

For each engine S-rank pick, determine:
- What popularity rank (1=fav) the picked horse was
- Win/place rate when pick == #1 fav vs when pick != #1 fav
- Recovery rate split by popularity rank

Joins engine_hit_rates with odds_snapshots on (date, venue, race_number),
using the latest snapshot per race.
"""
import os, sys, json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")
from db.supabase_client import get_client


def fetch_all(sb, table, select="*", chunk=1000, filters=None):
    rows = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        if filters:
            for k, v in filters.items():
                q = q.gte(k, v["gte"]) if "gte" in v else q.eq(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < chunk:
            break
        offset += chunk
    return rows


def main():
    sb = get_client()

    # Engine hit rates
    print("Fetching engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,hit_win,hit_place,result_1st,result_2nd,result_3rd")
    print(f"  {len(hits)} rows")

    # Race results (for win_payout)
    print("Fetching race_results...")
    rresults = fetch_all(sb, "race_results", select="race_id,winner_number,win_payout,status")
    payout_by_rid = {r["race_id"]: r for r in rresults if r.get("status") == "finished"}
    print(f"  {len(payout_by_rid)} finished")

    # Odds snapshots — only those after engine_hit_rates earliest date
    earliest = min(h["date"] for h in hits)
    print(f"Fetching odds_snapshots from {earliest}...")
    odds = []
    offset = 0
    while True:
        res = sb.table("odds_snapshots") \
            .select("race_date,venue,race_number,odds_data,snapshot_at") \
            .gte("race_date", earliest) \
            .range(offset, offset + 999).execute()
        if not res.data:
            break
        odds.extend(res.data)
        if len(res.data) < 1000:
            break
        offset += 1000
    print(f"  {len(odds)} odds snapshots")

    # Keep latest snapshot per (date, venue, race_number)
    latest_odds = {}  # key=(date,venue,race_num), val={horse_num: odds}
    latest_at = {}
    for o in odds:
        key = (o["race_date"], o["venue"], o["race_number"])
        ts = o["snapshot_at"]
        if key not in latest_at or ts > latest_at[key]:
            latest_at[key] = ts
            data = o["odds_data"]
            if isinstance(data, str):
                data = json.loads(data)
            # normalize keys: int→str variations
            latest_odds[key] = {int(k): float(v) for k, v in data.items() if v}
    print(f"  unique races with odds: {len(latest_odds)}")

    # Compute popularity rank for picks
    # Aggregations
    eng_pop_dist = defaultdict(lambda: defaultdict(int))   # engine -> pop_rank -> count
    eng_pop_perf = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "win": 0, "place": 0, "payout": 0,
    }))
    fav_match_stats = defaultdict(lambda: {
        "match_fav": 0, "not_fav": 0,
        "match_fav_win": 0, "not_fav_win": 0,
        "match_fav_place": 0, "not_fav_place": 0,
        "match_fav_payout": 0, "not_fav_payout": 0,
    })
    no_odds = defaultdict(int)

    for h in hits:
        key = (h["date"], h["venue"], h["race_number"])
        odds_map = latest_odds.get(key)
        eng = h["engine"]
        if not odds_map:
            no_odds[eng] += 1
            continue

        pick = h["top1_horse"]
        pick_odds = odds_map.get(pick)
        if pick_odds is None:
            no_odds[eng] += 1
            continue

        # Compute popularity rank: sort by odds asc, find rank of pick
        sorted_horses = sorted(odds_map.items(), key=lambda x: x[1])
        pop_rank = None
        for i, (hn, _) in enumerate(sorted_horses, 1):
            if hn == pick:
                pop_rank = i
                break
        if pop_rank is None:
            no_odds[eng] += 1
            continue

        # Bucket popularity
        if pop_rank <= 5:
            bucket = pop_rank  # 1,2,3,4,5
        elif pop_rank <= 8:
            bucket = "6-8"
        else:
            bucket = "9+"

        eng_pop_dist[eng][bucket] += 1

        # Performance per popularity bucket
        result = payout_by_rid.get(h["race_id"], {})
        payout = result.get("win_payout") or 0

        s = eng_pop_perf[eng][bucket]
        s["races"] += 1
        if h.get("hit_win"):
            s["win"] += 1
            s["payout"] += payout
        if h.get("hit_place"):
            s["place"] += 1

        # Fav vs non-fav comparison
        fs = fav_match_stats[eng]
        is_fav = (pop_rank == 1)
        if is_fav:
            fs["match_fav"] += 1
            if h.get("hit_win"):
                fs["match_fav_win"] += 1
                fs["match_fav_payout"] += payout
            if h.get("hit_place"):
                fs["match_fav_place"] += 1
        else:
            fs["not_fav"] += 1
            if h.get("hit_win"):
                fs["not_fav_win"] += 1
                fs["not_fav_payout"] += payout
            if h.get("hit_place"):
                fs["not_fav_place"] += 1

    # ---- Reports ----
    engines = ["dlogic", "ilogic", "viewlogic", "metalogic"]

    print("\n" + "=" * 78)
    print("ENGINE PICK POPULARITY DISTRIBUTION (% of S-rank picks at each pop rank)")
    print("=" * 78)
    print(f"{'engine':<10} {'#1fav':>7} {'#2':>6} {'#3':>6} {'#4':>6} {'#5':>6} {'6-8':>6} {'9+':>6} {'covered':>9} {'no_odds':>8}")
    for eng in engines:
        dist = eng_pop_dist[eng]
        total = sum(dist.values())
        if total == 0: continue
        line = f"{eng:<10}"
        for b in [1, 2, 3, 4, 5, "6-8", "9+"]:
            pct = dist.get(b, 0) / total * 100
            line += f" {pct:>5.1f}%"
        line += f" {total:>9} {no_odds[eng]:>8}"
        print(line)

    print("\n" + "=" * 78)
    print("FAV-MATCH ANALYSIS (engine pick == #1 fav vs not)")
    print("=" * 78)
    print(f"{'engine':<10} | {'fav-match races':>15} {'win%':>6} {'place%':>7} {'recov%':>7} | {'non-fav races':>13} {'win%':>6} {'place%':>7} {'recov%':>7}")
    print("-" * 110)
    for eng in engines:
        fs = fav_match_stats[eng]
        fav_n = fs["match_fav"]
        non_n = fs["not_fav"]
        if fav_n == 0 and non_n == 0: continue
        fav_w = fs["match_fav_win"] / fav_n * 100 if fav_n else 0
        fav_p = fs["match_fav_place"] / fav_n * 100 if fav_n else 0
        fav_r = fs["match_fav_payout"] / (fav_n * 100) * 100 if fav_n else 0
        non_w = fs["not_fav_win"] / non_n * 100 if non_n else 0
        non_p = fs["not_fav_place"] / non_n * 100 if non_n else 0
        non_r = fs["not_fav_payout"] / (non_n * 100) * 100 if non_n else 0
        print(f"{eng:<10} | {fav_n:>15} {fav_w:>5.1f}% {fav_p:>6.1f}% {fav_r:>6.1f}% | {non_n:>13} {non_w:>5.1f}% {non_p:>6.1f}% {non_r:>6.1f}%")

    print("\n" + "=" * 78)
    print("PERFORMANCE BY POPULARITY BUCKET (per engine)")
    print("=" * 78)
    for eng in engines:
        print(f"\n  [{eng}]")
        print(f"    {'pop':<5} {'races':>6} {'win%':>6} {'place%':>7} {'recov%':>7}")
        for b in [1, 2, 3, 4, 5, "6-8", "9+"]:
            s = eng_pop_perf[eng].get(b)
            if not s or s["races"] == 0: continue
            n = s["races"]
            wr = s["win"] / n * 100
            pr = s["place"] / n * 100
            rec = s["payout"] / (n * 100) * 100
            print(f"    {str(b):<5} {n:>6} {wr:>5.1f}% {pr:>6.1f}% {rec:>6.1f}%")


if __name__ == "__main__":
    main()
