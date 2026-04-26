#!/usr/bin/env python3
"""How often does the golden pattern appear (daily frequency analysis)."""
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

    print("Loading...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,result_1st,result_2nd,result_3rd")
    rresults = fetch_all(sb, "race_results", select="race_id,winner_number,win_payout,result_json,status")
    by_rid = {}
    for r in rresults:
        if r.get("status") != "finished": continue
        rj = r.get("result_json")
        if isinstance(rj, str): rj = json.loads(rj)
        r["_total_horses"] = rj.get("total_horses") if rj else None
        by_rid[r["race_id"]] = r

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

    # Group hits by race
    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

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

        try:
            d = datetime.strptime(any_row["date"], "%Y-%m-%d")
            weekday = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
        except Exception:
            weekday = "?"

        races_data.append({
            "date": any_row["date"],
            "race_type": any_row["race_type"],
            "venue": any_row["venue"],
            "race_number": any_row["race_number"],
            "weekday": weekday,
            "total_horses": total_horses,
            "cons_count": cons_count,
            "pop_rank": pop_rank,
            "won": cons_horse == win_horse,
            "payout": payout,
        })

    # Filters
    BEST_VENUES = {"園田", "水沢", "高知", "笠松", "金沢"}
    BEST_WEEKDAYS = {"火", "水", "木"}

    def loose_golden(r):
        return (r["cons_count"] in (2, 3)
                and r["pop_rank"] is not None
                and 5 <= r["pop_rank"] <= 8)

    def strict_golden(r):
        if not loose_golden(r): return False
        if r["race_type"] != "nar": return False
        if r["venue"] not in BEST_VENUES: return False
        if r["total_horses"] is None or not (6 <= r["total_horses"] <= 12): return False
        if r["weekday"] not in BEST_WEEKDAYS: return False
        return True

    # All races + golden + strict
    print(f"\nTotal races (4 engines + finished): {len(races_data)}")
    loose = [r for r in races_data if loose_golden(r)]
    strict = [r for r in races_data if strict_golden(r)]
    print(f"Loose golden (2-3 agree, pop 5-8): {len(loose)}")
    print(f"Strict golden (+ NAR + 5 venues + 6-12頭 + 火水木): {len(strict)}")

    # Date span
    dates = sorted(set(r["date"] for r in races_data))
    print(f"\nDate range: {dates[0]} 〜 {dates[-1]} ({len(dates)} unique days with any race)")

    # Daily counts
    print("\n" + "=" * 70)
    print("DAILY FREQUENCY")
    print("=" * 70)
    daily_total = Counter(r["date"] for r in races_data)
    daily_loose = Counter(r["date"] for r in loose)
    daily_strict = Counter(r["date"] for r in strict)

    print(f"  {'date':<12} {'wd':<3} {'all':>5} {'loose':>6} {'strict':>7}")
    for d in dates:
        try:
            wd = ["月", "火", "水", "木", "金", "土", "日"][datetime.strptime(d, "%Y-%m-%d").weekday()]
        except Exception:
            wd = "?"
        print(f"  {d:<12} {wd:<3} {daily_total[d]:>5} {daily_loose[d]:>6} {daily_strict[d]:>7}")

    # Summary by weekday
    print("\n" + "=" * 70)
    print("BY WEEKDAY (averages)")
    print("=" * 70)
    wd_loose = defaultdict(list)
    wd_strict = defaultdict(list)
    wd_total = defaultdict(list)
    by_date_wd = {}
    for d in dates:
        try:
            wd = ["月", "火", "水", "木", "金", "土", "日"][datetime.strptime(d, "%Y-%m-%d").weekday()]
        except Exception:
            wd = "?"
        by_date_wd[d] = wd
        wd_total[wd].append(daily_total[d])
        wd_loose[wd].append(daily_loose[d])
        wd_strict[wd].append(daily_strict[d])

    print(f"  {'wd':<3} {'days':>5} {'all/day':>9} {'loose/day':>11} {'strict/day':>11}")
    for wd in ["月", "火", "水", "木", "金", "土", "日"]:
        if wd not in wd_total: continue
        d = wd_total[wd]
        l = wd_loose[wd]
        s = wd_strict[wd]
        days = len(d)
        avg_t = sum(d)/days if days else 0
        avg_l = sum(l)/days if days else 0
        avg_s = sum(s)/days if days else 0
        print(f"  {wd:<3} {days:>5} {avg_t:>8.1f} {avg_l:>10.1f} {avg_s:>10.1f}")

    # Strict pattern profitability
    if strict:
        s_won = sum(1 for r in strict if r["won"])
        s_payout = sum(r["payout"] for r in strict if r["won"])
        s_invest = len(strict) * 100
        print(f"\n=== STRICT PATTERN OVERALL ===")
        print(f"  bets={len(strict)} wins={s_won} ({s_won/len(strict)*100:.1f}%)")
        print(f"  invest={s_invest} payout={s_payout} recovery={s_payout/s_invest*100:.1f}%")
        print(f"  profit={s_payout - s_invest}")


if __name__ == "__main__":
    main()
