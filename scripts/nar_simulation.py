#!/usr/bin/env python3
"""NAR黄金パターン 実戦シミュレーション.

複数のフィルター案で、日次・累計収支・ドローダウンを計測し、
"使えるルール" を客観評価。
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


STRONG_VENUES = {"園田", "水沢", "高知", "笠松", "金沢"}
GOOD_WEEKDAYS = {1, 2, 3}  # 火水木


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading NAR engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,engine,top1_horse",
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
            d = datetime.strptime(date_iso, "%Y-%m-%d")
            wd_idx = d.weekday()
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

        winner = result.get("winner_number")
        win_payout = result.get("win_payout") or 0
        won = (cons_horse == winner)
        profit = (win_payout - 100) if won else -100

        races_data.append({
            "date": date_iso, "wd_idx": wd_idx, "wd": wd,
            "venue": venue, "race_num": race_num,
            "total_horses": total_horses, "cons": cons_count,
            "pop_rank": pop_rank,
            "won": won, "payout": win_payout, "profit": profit,
        })

    races_data.sort(key=lambda r: (r["date"], r["venue"], r["race_num"]))
    logger.info(f"NAR enriched: {len(races_data)}")

    # ---- Filter functions ----
    def filter_strict(r):
        return (r["wd_idx"] in GOOD_WEEKDAYS
                and r["venue"] in STRONG_VENUES
                and 6 <= r["total_horses"] <= 12
                and r["cons"] in (2, 3)
                and r["pop_rank"] in (5, 6, 7, 8))

    def filter_pop6_only(r):
        # 中穴特化: 6番人気のみ (NAR強5会場+火水木+合議2-3)
        return (r["wd_idx"] in GOOD_WEEKDAYS
                and r["venue"] in STRONG_VENUES
                and r["cons"] in (2, 3)
                and r["pop_rank"] == 6)

    def filter_pop68_pure(r):
        # NAR + 強5会場 + 6or8人気 + 2-3一致 (拡大)
        return (r["venue"] in STRONG_VENUES
                and r["cons"] in (2, 3)
                and r["pop_rank"] in (6, 8))

    def filter_loose(r):
        # 全曜日 + 強5会場 + 2-3一致 + 5-8人気
        return (r["venue"] in STRONG_VENUES
                and r["cons"] in (2, 3)
                and r["pop_rank"] in (5, 6, 7, 8))

    filters = [
        ("Strict (火水木+強5+6-12頭+5-8人気+2-3一致)", filter_strict),
        ("中穴特化 (火水木+強5+6人気のみ)", filter_pop6_only),
        ("拡大 (強5+6or8人気+2-3一致、曜日不問)", filter_pop68_pure),
        ("緩め (強5+5-8人気+2-3一致、曜日不問)", filter_loose),
    ]

    # ---- Run sims ----
    print("\n" + "=" * 78)
    print("【シミュレーション結果 比較】")
    print("=" * 78)

    for name, fn in filters:
        bets = [r for r in races_data if fn(r)]
        if not bets:
            print(f"\n■ {name}: 該当なし")
            continue

        # Daily P&L
        daily = defaultdict(int)
        for r in bets:
            daily[r["date"]] += r["profit"]

        days = sorted(daily.keys())

        # Cumulative + drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        max_dd_at = None
        cum_curve = []
        for d in days:
            cumulative += daily[d]
            peak = max(peak, cumulative)
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
                max_dd_at = d
            cum_curve.append((d, cumulative, peak - cumulative))

        # Stats
        n = len(bets)
        wins = sum(1 for r in bets if r["won"])
        invest = n * 100
        payout = sum(r["payout"] for r in bets if r["won"])
        recov = payout / invest * 100

        plus_days = sum(1 for d in days if daily[d] > 0)
        zero_days = sum(1 for d in days if daily[d] == 0)
        minus_days = sum(1 for d in days if daily[d] < 0)

        # Longest losing streak
        max_losing_streak = 0
        cur_losing = 0
        for d in days:
            if daily[d] < 0:
                cur_losing += 1
                max_losing_streak = max(max_losing_streak, cur_losing)
            elif daily[d] > 0:
                cur_losing = 0

        # Best/worst day
        best_day = max(days, key=lambda d: daily[d])
        worst_day = min(days, key=lambda d: daily[d])

        print(f"\n■ {name}")
        print(f"  ベット数: {n}, 投資: ¥{invest:,}, 払戻: ¥{payout:,}")
        print(f"  単勝率: {wins/n*100:.1f}% ({wins}/{n})")
        print(f"  回収率: <b>{recov:.1f}%</b>  純利益: ¥{payout - invest:+,}")
        print(f"  実施日数: {len(days)} 日 (プラス {plus_days} / ゼロ {zero_days} / マイナス {minus_days})")
        print(f"  プラス日比率: {plus_days/len(days)*100:.1f}%")
        print(f"  最長連敗日数: {max_losing_streak} 日")
        print(f"  最大ドローダウン: ¥{max_dd:,} ({max_dd_at}まで)")
        print(f"  最良の日: {best_day} → ¥{daily[best_day]:+,}")
        print(f"  最悪の日: {worst_day} → ¥{daily[worst_day]:+,}")
        print(f"  最終累計収支: ¥{cumulative:+,}")

        # Monthly breakdown
        monthly = defaultdict(lambda: {"races": 0, "wins": 0, "payout": 0})
        for r in bets:
            ym = r["date"][:7]
            s = monthly[ym]
            s["races"] += 1
            if r["won"]:
                s["wins"] += 1
                s["payout"] += r["payout"]
        print(f"  月次収支:")
        for ym in sorted(monthly.keys()):
            m = monthly[ym]
            mn = m["races"]
            mr = m["payout"] / (mn * 100) * 100 if mn else 0
            mp = m["payout"] - mn * 100
            print(f"    {ym}: ベット {mn:>3}, 単勝 {m['wins']:>2}, 収支 ¥{mp:+5,}, 回収率 {mr:>5.1f}%")


if __name__ == "__main__":
    main()
