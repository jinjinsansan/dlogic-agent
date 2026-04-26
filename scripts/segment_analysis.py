#!/usr/bin/env python3
"""Step 4: Segment analysis on top of Step 3's golden pattern.

Golden pattern = (2/4 or 3/4 engines agree) AND (S-pick popularity in 5-8)
Segments: race_type (jra/nar), venue, total_horses, race_number, weekday
"""
import os, sys, json
from collections import defaultdict, Counter
from datetime import datetime

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

    print("Loading data...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,result_1st,result_2nd,result_3rd")
    print(f"  hits: {len(hits)}")

    rresults = fetch_all(sb, "race_results", select="race_id,winner_number,win_payout,result_json,status")
    by_rid = {}
    for r in rresults:
        if r.get("status") != "finished": continue
        rj = r.get("result_json")
        if isinstance(rj, str): rj = json.loads(rj)
        r["_total_horses"] = rj.get("total_horses") if rj else None
        by_rid[r["race_id"]] = r
    print(f"  finished: {len(by_rid)}")

    earliest = min(h["date"] for h in hits)
    odds_rows = fetch_all(sb, "odds_snapshots",
        select="race_date,venue,race_number,odds_data,snapshot_at",
        gte={"race_date": earliest})
    latest_at, latest_odds = {}, {}
    for o in odds_rows:
        key = (o["race_date"], o["venue"], o["race_number"])
        ts = o["snapshot_at"]
        if key not in latest_at or ts > latest_at[key]:
            latest_at[key] = ts
            data = o["odds_data"]
            if isinstance(data, str): data = json.loads(data)
            latest_odds[key] = {int(k): float(v) for k, v in data.items() if v}
    print(f"  odds covered: {len(latest_odds)}")

    # Group by race
    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h
    print(f"  races: {len(by_race)}")

    # ---- Build per-race "golden pattern" status ----
    # For each race: consensus_horse, consensus_count, consensus_pop_rank, win, place, payout
    races_data = []
    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        any_row = next(iter(eng_rows.values()))
        result_set = {any_row["result_1st"], any_row["result_2nd"], any_row["result_3rd"]}
        win_horse = any_row["result_1st"]
        result = by_rid.get(rid, {})
        payout = result.get("win_payout") or 0
        total_horses = result.get("_total_horses")

        odds_map = latest_odds.get((any_row["date"], any_row["venue"], any_row["race_number"]))
        pop_rank = None
        if odds_map and cons_horse in odds_map:
            sh = sorted(odds_map.items(), key=lambda x: x[1])
            pop_rank = next((i for i, (hn, _) in enumerate(sh, 1) if hn == cons_horse), None)

        # Weekday
        try:
            d = datetime.strptime(any_row["date"], "%Y-%m-%d")
            weekday = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
        except Exception:
            weekday = "?"

        races_data.append({
            "rid": rid,
            "race_type": any_row["race_type"],
            "venue": any_row["venue"],
            "race_number": any_row["race_number"],
            "weekday": weekday,
            "total_horses": total_horses,
            "cons_count": cons_count,
            "pop_rank": pop_rank,
            "won": cons_horse == win_horse,
            "placed": cons_horse in result_set,
            "payout": payout,
        })

    print(f"  enriched races: {len(races_data)}")

    # Golden pattern: 2-3/4 agree AND pop rank in 5-8
    def is_golden(r):
        return (r["cons_count"] in (2, 3)
                and r["pop_rank"] is not None
                and 5 <= r["pop_rank"] <= 8)

    golden = [r for r in races_data if is_golden(r)]
    print(f"\n  golden pattern races: {len(golden)}")

    def agg(rows):
        n = len(rows)
        if not n: return None
        win = sum(1 for r in rows if r["won"])
        place = sum(1 for r in rows if r["placed"])
        payout = sum(r["payout"] for r in rows if r["won"])
        return {"n": n, "win%": win/n*100, "place%": place/n*100, "recov%": payout/(n*100)*100, "win": win}

    def print_segment(title, segments, min_n=20):
        print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
        print(f"  {'segment':<20} {'races':>6} {'win':>4} {'win%':>6} {'place%':>7} {'recov%':>7}")
        # Sort by recovery rate desc
        sorted_segs = sorted(segments.items(), key=lambda x: x[1]["recov%"] if x[1] else 0, reverse=True)
        for k, v in sorted_segs:
            if not v or v["n"] < min_n: continue
            print(f"  {str(k):<20} {v['n']:>6} {v['win']:>4} {v['win%']:>5.1f}% {v['place%']:>6.1f}% {v['recov%']:>6.1f}%")

    # ---- Segment by race_type ----
    type_seg = defaultdict(list)
    for r in golden:
        type_seg[r["race_type"]].append(r)
    type_agg = {k: agg(v) for k, v in type_seg.items()}
    print_segment("GOLDEN x RACE_TYPE", type_agg, min_n=20)

    # ---- Segment by venue ----
    venue_seg = defaultdict(list)
    for r in golden:
        venue_seg[r["venue"]].append(r)
    venue_agg = {k: agg(v) for k, v in venue_seg.items()}
    print_segment("GOLDEN x VENUE", venue_agg, min_n=15)

    # ---- Segment by total_horses (bucket) ----
    def horses_bucket(n):
        if n is None: return "?"
        if n <= 9: return "6-9"
        if n <= 12: return "10-12"
        if n <= 15: return "13-15"
        return "16+"
    horses_seg = defaultdict(list)
    for r in golden:
        horses_seg[horses_bucket(r["total_horses"])].append(r)
    horses_agg = {k: agg(v) for k, v in horses_seg.items()}
    print_segment("GOLDEN x TOTAL_HORSES", horses_agg, min_n=20)

    # ---- Segment by weekday ----
    wd_seg = defaultdict(list)
    for r in golden:
        wd_seg[r["weekday"]].append(r)
    wd_agg = {k: agg(v) for k, v in wd_seg.items()}
    print_segment("GOLDEN x WEEKDAY", wd_agg, min_n=20)

    # ---- Segment by race_number bucket ----
    def rn_bucket(n):
        if n <= 4: return "1-4R"
        if n <= 8: return "5-8R"
        if n <= 11: return "9-11R"
        return "12R"
    rn_seg = defaultdict(list)
    for r in golden:
        rn_seg[rn_bucket(r["race_number"])].append(r)
    rn_agg = {k: agg(v) for k, v in rn_seg.items()}
    print_segment("GOLDEN x RACE_NUMBER", rn_agg, min_n=20)

    # ---- Cross: race_type × pop_rank inside golden pattern ----
    print(f"\n{'=' * 78}\nGOLDEN x RACE_TYPE x POP_RANK detail\n{'=' * 78}")
    cross = defaultdict(list)
    for r in golden:
        cross[(r["race_type"], r["pop_rank"])].append(r)
    print(f"  {'segment':<20} {'races':>6} {'win%':>6} {'place%':>7} {'recov%':>7}")
    for k in sorted(cross.keys()):
        v = agg(cross[k])
        if not v or v["n"] < 15: continue
        print(f"  {f'{k[0]} pop={k[1]}':<20} {v['n']:>6} {v['win%']:>5.1f}% {v['place%']:>6.1f}% {v['recov%']:>6.1f}%")

    # ---- All races baseline (for comparison) ----
    print(f"\n{'=' * 78}\nBASELINE COMPARISONS\n{'=' * 78}")
    print("  All races         :", agg(races_data))
    print("  All odds-covered  :", agg([r for r in races_data if r["pop_rank"] is not None]))
    print("  Golden pattern    :", agg(golden))


if __name__ == "__main__":
    main()
