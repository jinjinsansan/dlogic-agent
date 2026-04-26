#!/usr/bin/env python3
"""Step 3: Engine consensus analysis.

For each race, count how many engines picked the same S-rank horse,
and measure win/place/recovery rate by consensus level.
Also crosses with Step 2's popularity bucket finding.
"""
import os, sys, json
from collections import defaultdict, Counter
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")
from db.supabase_client import get_client


def fetch_all(sb, table, select="*", chunk=1000, gte=None):
    rows = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items():
                q = q.gte(k, v)
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

    print("Fetching engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,result_1st,result_2nd,result_3rd")
    print(f"  {len(hits)} rows")

    print("Fetching race_results...")
    rresults = fetch_all(sb, "race_results", select="race_id,winner_number,win_payout,status")
    payout_by_rid = {r["race_id"]: r for r in rresults if r.get("status") == "finished"}

    earliest = min(h["date"] for h in hits)
    print(f"Fetching odds_snapshots from {earliest}...")
    odds = fetch_all(sb, "odds_snapshots",
        select="race_date,venue,race_number,odds_data,snapshot_at",
        gte={"race_date": earliest})
    print(f"  {len(odds)}")

    latest_at = {}
    latest_odds = {}
    for o in odds:
        key = (o["race_date"], o["venue"], o["race_number"])
        ts = o["snapshot_at"]
        if key not in latest_at or ts > latest_at[key]:
            latest_at[key] = ts
            data = o["odds_data"]
            if isinstance(data, str):
                data = json.loads(data)
            latest_odds[key] = {int(k): float(v) for k, v in data.items() if v}
    print(f"  unique races with odds: {len(latest_odds)}")

    # Group hits by race_id
    by_race = defaultdict(dict)  # race_id -> {engine: row}
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h
    print(f"  unique races: {len(by_race)}")

    # ---- Per-race consensus analysis ----
    # For each race: count how many engines agreed on S-rank pick
    # consensus_level = max count of any single horse picked by N engines
    # Plus: most-popular pick (mode of S picks)

    consensus_stats = defaultdict(lambda: {
        "races": 0, "win": 0, "place": 0, "payout": 0,
    })  # key: consensus_level (1=all different, 4=all agree)

    pair_stats = defaultdict(lambda: {
        "races": 0, "win": 0, "place": 0, "payout": 0,
    })  # key: frozenset of engine pair, when both agree

    consensus_pop_stats = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "win": 0, "place": 0, "payout": 0,
    }))  # consensus_level -> pop_bucket -> stats

    triplet_dlogic_meta_ilogic = {
        "races": 0, "win": 0, "place": 0, "payout": 0,
    }

    no_data = 0
    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4:
            # Skip races where not all 4 engines logged
            continue

        # Pick counts
        picks = {eng: row["top1_horse"] for eng, row in eng_rows.items()}
        pick_counter = Counter(picks.values())
        consensus_horse, consensus_count = pick_counter.most_common(1)[0]

        # Use any engine row for race-level info
        any_row = next(iter(eng_rows.values()))
        result_set = {any_row["result_1st"], any_row["result_2nd"], any_row["result_3rd"]}
        win_horse = any_row["result_1st"]

        result = payout_by_rid.get(rid, {})
        payout = result.get("win_payout") or 0

        # Did consensus horse win/place?
        won = (consensus_horse == win_horse)
        placed = (consensus_horse in result_set)

        # Aggregate by consensus level
        s = consensus_stats[consensus_count]
        s["races"] += 1
        if won:
            s["win"] += 1
            s["payout"] += payout
        if placed:
            s["place"] += 1

        # Pair agreement (each pair where both picked the same horse)
        for e1, e2 in combinations(["dlogic", "ilogic", "viewlogic", "metalogic"], 2):
            if picks.get(e1) == picks.get(e2) and picks.get(e1) is not None:
                pair_horse = picks[e1]
                ps = pair_stats[frozenset([e1, e2])]
                ps["races"] += 1
                if pair_horse == win_horse:
                    ps["win"] += 1
                    ps["payout"] += payout
                if pair_horse in result_set:
                    ps["place"] += 1

        # Special triplet: dlogic + metalogic + ilogic agree
        if (picks.get("dlogic") == picks.get("metalogic") == picks.get("ilogic")
                and picks.get("dlogic") is not None):
            t = triplet_dlogic_meta_ilogic
            t["races"] += 1
            if won: t["win"] += 1; t["payout"] += payout
            if placed: t["place"] += 1

        # Pop bucket of consensus horse
        odds_map = latest_odds.get((any_row["date"], any_row["venue"], any_row["race_number"]))
        if not odds_map or consensus_horse not in odds_map:
            continue
        sorted_horses = sorted(odds_map.items(), key=lambda x: x[1])
        pop_rank = next((i for i, (hn, _) in enumerate(sorted_horses, 1) if hn == consensus_horse), None)
        if not pop_rank:
            continue
        bucket = pop_rank if pop_rank <= 5 else ("6-8" if pop_rank <= 8 else "9+")

        ps = consensus_pop_stats[consensus_count][bucket]
        ps["races"] += 1
        if won:
            ps["win"] += 1
            ps["payout"] += payout
        if placed:
            ps["place"] += 1

    # ---- Reports ----
    print("\n" + "=" * 78)
    print("CONSENSUS LEVEL: how often N engines pick the same S-rank horse")
    print("=" * 78)
    print(f"{'level':<8} {'races':>7} {'pct':>7} {'win':>5} {'win%':>6} {'place%':>7} {'recov%':>7}")
    total_races = sum(s["races"] for s in consensus_stats.values())
    for lv in [4, 3, 2, 1]:
        s = consensus_stats[lv]
        n = s["races"]
        if n == 0: continue
        pct = n / total_races * 100
        wr = s["win"] / n * 100
        pr = s["place"] / n * 100
        rec = s["payout"] / (n * 100) * 100
        print(f"{lv}/4 agree {n:>6} {pct:>6.1f}% {s['win']:>4} {wr:>5.1f}% {pr:>6.1f}% {rec:>6.1f}%")

    print("\n" + "=" * 78)
    print("PAIR AGREEMENT (when 2 specific engines pick the same horse)")
    print("=" * 78)
    print(f"{'pair':<25} {'races':>7} {'win%':>6} {'place%':>7} {'recov%':>7}")
    for pair_key in pair_stats:
        ps = pair_stats[pair_key]
        n = ps["races"]
        if n == 0: continue
        pair_str = "+".join(sorted(pair_key))
        wr = ps["win"] / n * 100
        pr = ps["place"] / n * 100
        rec = ps["payout"] / (n * 100) * 100
        print(f"{pair_str:<25} {n:>7} {wr:>5.1f}% {pr:>6.1f}% {rec:>6.1f}%")

    print("\n" + "=" * 78)
    print("TRIPLET: dlogic + metalogic + ilogic ALL agree (excludes viewlogic)")
    print("=" * 78)
    t = triplet_dlogic_meta_ilogic
    if t["races"]:
        n = t["races"]
        print(f"races={n}  win={t['win']/n*100:.1f}%  place={t['place']/n*100:.1f}%  recovery={t['payout']/(n*100)*100:.1f}%")
    else:
        print("no data")

    print("\n" + "=" * 78)
    print("CONSENSUS x POPULARITY (the holy grail combo)")
    print("=" * 78)
    for lv in [4, 3, 2]:
        if not consensus_pop_stats[lv]:
            continue
        print(f"\n  [{lv}/4 engines agree]")
        print(f"    {'pop':<5} {'races':>6} {'win%':>6} {'place%':>7} {'recov%':>7}")
        for b in [1, 2, 3, 4, 5, "6-8", "9+"]:
            s = consensus_pop_stats[lv].get(b)
            if not s or s["races"] == 0: continue
            n = s["races"]
            wr = s["win"] / n * 100
            pr = s["place"] / n * 100
            rec = s["payout"] / (n * 100) * 100
            print(f"    {str(b):<5} {n:>6} {wr:>5.1f}% {pr:>6.1f}% {rec:>6.1f}%")


if __name__ == "__main__":
    main()
