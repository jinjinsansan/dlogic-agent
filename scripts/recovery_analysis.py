#!/usr/bin/env python3
"""Calculate win recovery rate per engine from engine_hit_rates + race_results.

Investment = 100 yen on every S-rank horse (top1_horse).
Return = win_payout when top1_horse == winner_number.
"""
import os, sys, json
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")
from db.supabase_client import get_client


def fetch_all(sb, table, select="*", chunk=1000):
    rows = []
    offset = 0
    while True:
        res = sb.table(table).select(select).range(offset, offset + chunk - 1).execute()
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
                     select="date,race_id,engine,top1_horse,top3_horses,hit_win,hit_place,result_1st,result_2nd,result_3rd,race_type")
    print(f"  {len(hits)} rows")

    print("Fetching race_results...")
    results = fetch_all(sb, "race_results",
                        select="race_id,winner_number,win_payout,status")
    print(f"  {len(results)} rows")

    # Index race_results by race_id
    results_by_id = {r["race_id"]: r for r in results if r.get("status") == "finished"}
    print(f"  finished: {len(results_by_id)}")

    # Per-engine accumulators
    eng_stats = defaultdict(lambda: {
        "races": 0,
        "win_hits": 0,
        "place_hits": 0,
        "total_payout": 0,    # sum of win_payout when S won
        "missing_payout": 0,  # races where we have no payout data
        "no_result": 0,       # races without finished result
    })

    # Race-type breakdown (jra vs nar)
    eng_type_stats = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "win_hits": 0, "place_hits": 0, "total_payout": 0,
    }))

    # Weekly trend
    weekly = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "win_hits": 0, "total_payout": 0,
    }))

    for h in hits:
        eng = h["engine"]
        rid = h["race_id"]
        rtype = h.get("race_type", "?")
        s = eng_stats[eng]
        st = eng_type_stats[eng][rtype]

        result = results_by_id.get(rid)
        if not result:
            s["no_result"] += 1
            continue

        s["races"] += 1
        st["races"] += 1

        # Weekly bucket
        try:
            d = datetime.strptime(h["date"], "%Y-%m-%d")
            wk = d.strftime("%Y-W%W")
            weekly[eng][wk]["races"] += 1
        except Exception:
            wk = None

        if h.get("hit_win"):
            s["win_hits"] += 1
            st["win_hits"] += 1
            payout = result.get("win_payout")
            if payout and payout > 0:
                s["total_payout"] += payout
                st["total_payout"] += payout
                if wk:
                    weekly[eng][wk]["total_payout"] += payout
                    weekly[eng][wk]["win_hits"] += 1
            else:
                s["missing_payout"] += 1

        if h.get("hit_place"):
            s["place_hits"] += 1
            st["place_hits"] += 1

    # ---- Report ----
    print("\n" + "=" * 70)
    print("ENGINE WIN RECOVERY (S-rank only, 100yen flat bet)")
    print("=" * 70)
    print(f"{'engine':<10} {'races':>7} {'win':>6} {'win%':>7} {'payout':>10} {'recovery%':>11} {'place%':>8}")
    print("-" * 70)

    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        s = eng_stats[eng]
        n = s["races"]
        if n == 0:
            continue
        win_rate = s["win_hits"] / n * 100
        place_rate = s["place_hits"] / n * 100
        invest = n * 100
        recovery = s["total_payout"] / invest * 100
        print(f"{eng:<10} {n:>7} {s['win_hits']:>6} {win_rate:>6.1f}% {s['total_payout']:>10} {recovery:>10.1f}% {place_rate:>7.1f}%")
        if s["no_result"] or s["missing_payout"]:
            print(f"           (no_result={s['no_result']}, missing_payout={s['missing_payout']})")

    # By race type
    print("\n" + "=" * 70)
    print("BY RACE TYPE (JRA vs NAR)")
    print("=" * 70)
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        for rt in ["jra", "nar"]:
            st = eng_type_stats[eng][rt]
            n = st["races"]
            if n == 0:
                continue
            wr = st["win_hits"] / n * 100
            pr = st["place_hits"] / n * 100
            rec = st["total_payout"] / (n * 100) * 100
            print(f"  [{eng:<9}][{rt}] races={n:>5} win={wr:>5.1f}% place={pr:>5.1f}% recovery={rec:>5.1f}%")

    # Weekly trend
    print("\n" + "=" * 70)
    print("WEEKLY RECOVERY (S-rank, all engines combined would dilute, so per engine)")
    print("=" * 70)
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        if eng not in weekly:
            continue
        print(f"\n  [{eng}]")
        weeks = sorted(weekly[eng].keys())
        for wk in weeks:
            w = weekly[eng][wk]
            n = w["races"]
            if n == 0: continue
            rec = w["total_payout"] / (n * 100) * 100
            wr = w["win_hits"] / n * 100
            print(f"    {wk}: races={n:>4} win_rate={wr:>5.1f}% recovery={rec:>6.1f}%")

    # Distribution of payouts when hit (to see if hits are mostly favorites or longshots)
    print("\n" + "=" * 70)
    print("PAYOUT DISTRIBUTION (winning S-rank picks only)")
    print("=" * 70)
    bins = [(0, 200, "<2.0x  (heavy fav)"),
            (200, 400, "2.0-4.0x  (fav)"),
            (400, 700, "4.0-7.0x"),
            (700, 1500, "7.0-15x"),
            (1500, 5000, "15-50x  (mid longshot)"),
            (5000, 999999, ">=50x  (longshot)")]
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        bin_counts = [0] * len(bins)
        for h in hits:
            if h["engine"] != eng or not h.get("hit_win"):
                continue
            r = results_by_id.get(h["race_id"])
            if not r: continue
            p = r.get("win_payout") or 0
            for i, (lo, hi, _) in enumerate(bins):
                if lo <= p < hi:
                    bin_counts[i] += 1
                    break
        total = sum(bin_counts)
        if total == 0: continue
        print(f"\n  [{eng}] total wins={total}")
        for (lo, hi, label), cnt in zip(bins, bin_counts):
            pct = cnt / total * 100
            print(f"    {label:<22} {cnt:>4} ({pct:>5.1f}%)")


if __name__ == "__main__":
    main()
