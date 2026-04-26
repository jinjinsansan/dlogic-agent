#!/usr/bin/env python3
"""Phase B-2: Wide (ワイド) recovery rate analysis.

Strategies tested:
  A) Engine top1+top2 wide 1pt (each engine separately)
  B) Engine top3 BOX wide 3pt
  C) Consensus axis × top1 of remaining engines (1〜3pt)

Wide hits = both horses in top3 finish.
"""
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from itertools import combinations

# Read Supabase creds from VPS
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


def get_wide_payout(payouts: dict, h1: int, h2: int) -> int:
    """payouts.wide から (h1, h2) のワイド払戻を取得。"""
    target = frozenset([h1, h2])
    for entry in (payouts.get("wide") or []):
        combo = entry.get("combo") or []
        if frozenset(combo) == target:
            return entry.get("payout") or 0
    return 0


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,result_1st,result_2nd,result_3rd")
    logger.info(f"  {len(hits)} rows")

    logger.info("loading race_results...")
    results = fetch_all(sb, "race_results", select="race_id,result_json,status")
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

    # ============================================================
    # Strategy A: Each engine top1+top2 wide (1pt per race)
    # ============================================================
    logger.info("Computing Strategy A: top1+top2 wide...")
    eng_a_stats = defaultdict(lambda: {"races": 0, "hits": 0, "payout": 0})
    eng_a_type = defaultdict(lambda: defaultdict(lambda: {"races": 0, "hits": 0, "payout": 0}))

    for h in hits:
        rid = h["race_id"]
        result = by_rid.get(rid)
        if not result: continue
        payouts = (result["result_json"].get("payouts") or {})
        if not payouts.get("wide"): continue

        top3 = h.get("top3_horses") or []
        if len(top3) < 2: continue
        h1, h2 = top3[0], top3[1]

        s = eng_a_stats[h["engine"]]
        st = eng_a_type[h["engine"]][h.get("race_type", "?")]
        s["races"] += 1
        st["races"] += 1

        wide_p = get_wide_payout(payouts, h1, h2)
        if wide_p > 0:
            s["hits"] += 1
            s["payout"] += wide_p
            st["hits"] += 1
            st["payout"] += wide_p

    print("\n" + "=" * 70)
    print("STRATEGY A: 各エンジン top1+top2 ワイド 1点 (100yen)")
    print("=" * 70)
    print(f"{'engine':<10} {'races':>7} {'hits':>5} {'hit%':>6} {'payout':>10} {'recov%':>7}")
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        s = eng_a_stats[eng]
        n = s["races"]
        if n == 0: continue
        hit_rate = s["hits"] / n * 100
        rec = s["payout"] / (n * 100) * 100
        print(f"{eng:<10} {n:>7} {s['hits']:>5} {hit_rate:>5.1f}% {s['payout']:>10} {rec:>6.1f}%")

    print("\n  [JRA / NAR breakdown]")
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        for rt in ["jra", "nar"]:
            st = eng_a_type[eng][rt]
            if st["races"] == 0: continue
            n = st["races"]
            hr = st["hits"] / n * 100
            rec = st["payout"] / (n * 100) * 100
            print(f"  [{eng:<9}][{rt}] races={n:>5} hit={hr:>5.1f}% recovery={rec:>6.1f}%")

    # ============================================================
    # Strategy B: Engine top3 BOX wide (3pt per race)
    # ============================================================
    logger.info("Computing Strategy B: top3 BOX wide...")
    eng_b_stats = defaultdict(lambda: {"races": 0, "any_hit": 0, "total_payout": 0})
    eng_b_type = defaultdict(lambda: defaultdict(lambda: {"races": 0, "any_hit": 0, "total_payout": 0}))

    for h in hits:
        rid = h["race_id"]
        result = by_rid.get(rid)
        if not result: continue
        payouts = (result["result_json"].get("payouts") or {})
        if not payouts.get("wide"): continue

        top3 = h.get("top3_horses") or []
        if len(top3) < 3: continue

        s = eng_b_stats[h["engine"]]
        st = eng_b_type[h["engine"]][h.get("race_type", "?")]
        s["races"] += 1
        st["races"] += 1

        # 3 pairs: (top3[0], top3[1]), (top3[0], top3[2]), (top3[1], top3[2])
        any_hit = False
        race_payout = 0
        for a, b in combinations(top3[:3], 2):
            wp = get_wide_payout(payouts, a, b)
            if wp > 0:
                any_hit = True
                race_payout += wp

        if any_hit:
            s["any_hit"] += 1
            st["any_hit"] += 1
        s["total_payout"] += race_payout
        st["total_payout"] += race_payout

    print("\n" + "=" * 70)
    print("STRATEGY B: 各エンジン top3 BOX ワイド 3点 (300yen / race)")
    print("=" * 70)
    print(f"{'engine':<10} {'races':>7} {'any_hit':>8} {'hit%':>6} {'payout':>10} {'recov%':>7}")
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        s = eng_b_stats[eng]
        n = s["races"]
        if n == 0: continue
        hr = s["any_hit"] / n * 100
        rec = s["total_payout"] / (n * 300) * 100  # 300yen per race
        print(f"{eng:<10} {n:>7} {s['any_hit']:>8} {hr:>5.1f}% {s['total_payout']:>10} {rec:>6.1f}%")

    print("\n  [JRA / NAR breakdown]")
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        for rt in ["jra", "nar"]:
            st = eng_b_type[eng][rt]
            if st["races"] == 0: continue
            n = st["races"]
            hr = st["any_hit"] / n * 100
            rec = st["total_payout"] / (n * 300) * 100
            print(f"  [{eng:<9}][{rt}] races={n:>5} any_hit={hr:>5.1f}% recovery={rec:>6.1f}%")

    # ============================================================
    # Strategy C: Consensus axis × other engines' top1
    # axis = consensus_horse, partners = unique top1 from non-agreeing engines
    # ============================================================
    logger.info("Computing Strategy C: consensus axis flow...")
    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    cons_stats = defaultdict(lambda: defaultdict(lambda: {
        "races": 0, "tickets": 0, "hit_races": 0, "total_payout": 0,
    }))  # consensus_count -> pop_bucket

    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        result = by_rid.get(rid)
        if not result: continue
        payouts = (result["result_json"].get("payouts") or {})
        if not payouts.get("wide"): continue

        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        # Partners = unique top1 from other engines (excluding consensus_horse)
        partners = sorted(set(p for p in picks.values() if p != cons_horse))

        any_row = next(iter(eng_rows.values()))
        odds_map = latest_odds.get((any_row["date"], any_row["venue"], any_row["race_number"]))
        pop = None
        if odds_map and cons_horse in odds_map:
            sp = sorted(odds_map.items(), key=lambda x: x[1])
            pop = next((i for i, (hn, _) in enumerate(sp, 1) if hn == cons_horse), None)
        if not pop: continue
        bucket = pop if pop <= 5 else ("6-8" if pop <= 8 else "9+")

        # Each partner = 1 wide ticket (axis-cons_horse + partner)
        n_tickets = len(partners)
        if n_tickets == 0: continue

        race_payout = 0
        race_hit = False
        for p in partners:
            wp = get_wide_payout(payouts, cons_horse, p)
            if wp > 0:
                race_payout += wp
                race_hit = True

        s = cons_stats[cons_count][bucket]
        s["races"] += 1
        s["tickets"] += n_tickets
        if race_hit: s["hit_races"] += 1
        s["total_payout"] += race_payout

    print("\n" + "=" * 70)
    print("STRATEGY C: 合議制本命を軸 × 他エンジンtop1を相手にワイド流し")
    print("=" * 70)
    for lv in [4, 3, 2]:
        if lv not in cons_stats: continue
        print(f"\n  [{lv}/4 一致]")
        print(f"    {'pop':<5} {'races':>6} {'tickets':>8} {'hit_races':>10} {'hit%':>6} {'invest':>8} {'payout':>9} {'recov%':>7}")
        for b in [1, 2, 3, 4, 5, "6-8", "9+"]:
            s = cons_stats[lv].get(b)
            if not s or s["races"] == 0: continue
            n = s["races"]
            t = s["tickets"]
            invest = t * 100
            hr = s["hit_races"] / n * 100
            rec = s["total_payout"] / invest * 100 if invest else 0
            print(f"    {str(b):<5} {n:>6} {t:>8} {s['hit_races']:>10} {hr:>5.1f}% {invest:>8} {s['total_payout']:>9} {rec:>6.1f}%")


if __name__ == "__main__":
    main()
