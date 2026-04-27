#!/usr/bin/env python3
"""NAR限定 全条件総当たり: 100%超のセグメントを抽出.

JRA汚染を避けるため race_type='nar' のみ集計。
切り口: weekday × venue × pop × consensus × field × race_number_bucket
"""
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime
from itertools import combinations

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


def fetch_all(sb, table, select="*", chunk=1000, gte=None, eq=None):
    rows, offset = [], 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items(): q = q.gte(k, v)
        if eq:
            for k, v in eq.items(): q = q.eq(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < chunk: break
        offset += chunk
    return rows


def field_bucket(n):
    if n <= 9: return "6-9"
    if n <= 12: return "10-12"
    return "13+"


def rn_bucket(rn):
    if rn <= 4: return "1-4R"
    if rn <= 8: return "5-8R"
    if rn <= 11: return "9-11R"
    return "12R"


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading NAR engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,result_1st,result_2nd,result_3rd",
        eq={"race_type": "nar"})
    logger.info(f"  {len(hits)} NAR rows")

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
        gte={"race_date": "2025-04-01"})
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

    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    races_data = []
    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        result = by_rid.get(rid)
        if not result: continue

        any_row = next(iter(eng_rows.values()))
        date_iso = any_row["date"]
        venue = any_row["venue"]
        race_num = any_row["race_number"]

        try:
            wd_idx = datetime.strptime(date_iso, "%Y-%m-%d").weekday()
        except ValueError: continue
        wd = ["月","火","水","木","金","土","日"][wd_idx]

        rj = result.get("result_json") or {}
        total_horses = rj.get("total_horses") or 0
        if total_horses == 0: continue

        odds_map = latest_odds.get((date_iso, venue, race_num))
        if not odds_map: continue

        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        if cons_horse not in odds_map: continue
        sp = sorted(odds_map.items(), key=lambda x: x[1])
        pop_rank = next((i for i, (hn, _) in enumerate(sp, 1) if hn == cons_horse), None)
        if not pop_rank: continue

        if pop_rank <= 5: pop_b = str(pop_rank)
        elif pop_rank <= 8: pop_b = "6-8"
        else: pop_b = "9+"

        winner = result.get("winner_number")
        win_payout = result.get("win_payout") or 0
        won = (cons_horse == winner)
        profit = (win_payout - 100) if won else -100

        races_data.append({
            "wd": wd, "venue": venue,
            "field_b": field_bucket(total_horses),
            "rn_b": rn_bucket(race_num),
            "pop_b": pop_b, "pop_rank": pop_rank,
            "cons": cons_count,
            "won": won, "payout": win_payout, "profit": profit,
            "agreed_engines": [eng for eng, p in picks.items() if p == cons_horse],
        })

    logger.info(f"NAR enriched: {len(races_data)}")

    # ============ All single-axis aggregates ============
    def agg_by(key_fn, min_n=50):
        seg = defaultdict(lambda: {"n": 0, "wins": 0, "payout": 0})
        for r in races_data:
            k = key_fn(r)
            s = seg[k]
            s["n"] += 1
            if r["won"]:
                s["wins"] += 1
                s["payout"] += r["payout"]
        out = []
        for k, s in seg.items():
            if s["n"] < min_n: continue
            recov = s["payout"] / (s["n"] * 100) * 100
            out.append({"key": k, "n": s["n"], "wins": s["wins"],
                        "win%": s["wins"]/s["n"]*100, "recov%": recov})
        return sorted(out, key=lambda x: x["recov%"], reverse=True)

    # ============ Multi-axis combos ============
    def agg_multi(combo_fn, min_n=30):
        seg = defaultdict(lambda: {"n": 0, "wins": 0, "payout": 0})
        for r in races_data:
            k = combo_fn(r)
            if k is None: continue
            s = seg[k]
            s["n"] += 1
            if r["won"]:
                s["wins"] += 1
                s["payout"] += r["payout"]
        out = []
        for k, s in seg.items():
            if s["n"] < min_n: continue
            recov = s["payout"] / (s["n"] * 100) * 100
            out.append({"key": k, "n": s["n"], "wins": s["wins"],
                        "win%": s["wins"]/s["n"]*100, "recov%": recov})
        return sorted(out, key=lambda x: x["recov%"], reverse=True)

    print("\n" + "=" * 78)
    print("【NAR ベースライン】")
    print("=" * 78)
    n = len(races_data)
    wins = sum(1 for r in races_data if r["won"])
    payout = sum(r["payout"] for r in races_data if r["won"])
    print(f"  total: {n} races, win={wins} ({wins/n*100:.1f}%), recov={payout/(n*100)*100:.1f}%")

    print("\n" + "=" * 78)
    print("【Single Axis: 各軸トップ10】")
    print("=" * 78)
    print("\n■ pop_rank (人気順位, min 100R)")
    for x in agg_by(lambda r: r["pop_rank"], min_n=100)[:10]:
        print(f"  {x['key']}番人気: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ weekday (min 200R)")
    for x in agg_by(lambda r: r["wd"], min_n=200):
        print(f"  {x['key']}曜: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ venue (min 100R)")
    for x in agg_by(lambda r: r["venue"], min_n=100):
        print(f"  {x['key']:<6}: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ field_bucket (min 200R)")
    for x in agg_by(lambda r: r["field_b"], min_n=200):
        print(f"  {x['key']}頭: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ race_number_bucket (min 200R)")
    for x in agg_by(lambda r: r["rn_b"], min_n=200):
        print(f"  {x['key']}: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ consensus (min 200R)")
    for x in agg_by(lambda r: r["cons"], min_n=200):
        print(f"  {x['key']}/4一致: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n" + "=" * 78)
    print("【2-Axis Combos: 100%超セグメント (n>=50)】")
    print("=" * 78)

    print("\n■ wd × pop_rank")
    for x in agg_multi(lambda r: (r["wd"], r["pop_rank"]), min_n=50):
        if x["recov%"] < 100: continue
        print(f"  {x['key'][0]}曜 × {x['key'][1]}人気: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ wd × cons")
    for x in agg_multi(lambda r: (r["wd"], r["cons"]), min_n=50):
        if x["recov%"] < 100: continue
        print(f"  {x['key'][0]}曜 × {x['key'][1]}/4一致: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ venue × cons")
    for x in agg_multi(lambda r: (r["venue"], r["cons"]), min_n=30):
        if x["recov%"] < 100: continue
        print(f"  {x['key'][0]} × {x['key'][1]}/4一致: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ pop_rank × cons (NAR limited、min 30)")
    for x in agg_multi(lambda r: (r["pop_rank"], r["cons"]), min_n=30):
        if x["recov%"] < 100: continue
        print(f"  {x['key'][0]}人気 × {x['key'][1]}/4一致: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ rn_bucket × pop_rank (min 30)")
    for x in agg_multi(lambda r: (r["rn_b"], r["pop_rank"]), min_n=30):
        if x["recov%"] < 100: continue
        print(f"  {x['key'][0]} × {x['key'][1]}人気: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n" + "=" * 78)
    print("【3-Axis Combos: 150%超セグメント (n>=30)】")
    print("=" * 78)
    print("\n■ wd × venue × pop_b")
    for x in agg_multi(lambda r: (r["wd"], r["venue"], r["pop_b"]), min_n=30):
        if x["recov%"] < 150: continue
        print(f"  {x['key'][0]}曜 × {x['key'][1]} × {x['key'][2]}: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ wd × cons × pop_b")
    for x in agg_multi(lambda r: (r["wd"], r["cons"], r["pop_b"]), min_n=30):
        if x["recov%"] < 150: continue
        print(f"  {x['key'][0]}曜 × {x['key'][1]}/4一致 × {x['key'][2]}: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ venue × cons × pop_b")
    for x in agg_multi(lambda r: (r["venue"], r["cons"], r["pop_b"]), min_n=30):
        if x["recov%"] < 150: continue
        print(f"  {x['key'][0]} × {x['key'][1]}/4一致 × {x['key'][2]}: n={x['n']:>4} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")


if __name__ == "__main__":
    main()
