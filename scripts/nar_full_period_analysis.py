#!/usr/bin/env python3
"""NAR全期間 (1年分) 分析: 人気を PCKEIBA から直接取得.

odds_snapshots は3/11以降のみだが、PCKEIBA の nvd_se.tansho_ninkijun
を使えば過去全期間の人気順位が取れる。これでバックフィル後の
全レースを人気軸で分析する。
"""
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime

import psycopg2

# Supabase env from VPS
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

PCKEIBA_CONFIG = {
    "host": "127.0.0.1", "port": 5432, "database": "pckeiba",
    "user": "postgres", "password": "postgres",
}

NAR_VENUES = {
    '83': '帯広', '30': '門別', '35': '盛岡', '36': '水沢',
    '45': '浦和', '43': '船橋', '42': '大井', '44': '川崎',
    '46': '金沢', '47': '笠松', '48': '名古屋',
    '50': '園田', '51': '姫路', '54': '高知', '55': '佐賀',
}
NAR_VENUE_TO_CODE = {v: k for k, v in NAR_VENUES.items()}
NANKAN_CODES = {'42', '43', '44', '45'}
REGION_GROUPS = [
    {'35', '36'}, {'46', '47', '48'}, {'50', '51'},
    {'54', '55'}, {'30', '83'},
]
SCHEDULE_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'data', 'nar_schedule_master_2020_2026.json'),
]


def load_schedule_master():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return None


def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule:
        return code
    race_date = f"{nen}{md}"
    day_venues = schedule['schedule_data'].get(race_date, [])
    if not day_venues: return code
    if len(day_venues) == 1: return day_venues[0]
    if code in day_venues: return code
    if code in NANKAN_CODES:
        n_on_day = [c for c in day_venues if c in NANKAN_CODES]
        if len(n_on_day) == 1: return n_on_day[0]
    for group in REGION_GROUPS:
        if code in group:
            cands = [c for c in day_venues if c in group]
            if len(cands) == 1: return cands[0]
            break
    return code


def fetch_all(sb, table, select, eq=None, gte=None, chunk=1000):
    rows, offset = [], 0
    while True:
        q = sb.table(table).select(select)
        if eq:
            for k, v in eq.items(): q = q.eq(k, v)
        if gte:
            for k, v in gte.items(): q = q.gte(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < chunk: break
        offset += chunk
    return rows


def build_pckeiba_index(since_yyyymmdd, until_yyyymmdd, schedule):
    """PCKEIBA から (date_iso, venue_corrected, race_num, umaban) → ninkijun の dict を構築"""
    logger.info(f"connecting PCKEIBA, fetching nvd_se {since_yyyymmdd}〜{until_yyyymmdd}...")
    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    cur = conn.cursor("nvd_cur")
    cur.itersize = 50000
    cur.execute("""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               umaban, tansho_ninkijun
        FROM nvd_se
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
    """, (since_yyyymmdd, until_yyyymmdd))

    idx = {}
    cnt = 0
    for nen, md, code, bango, umaban, ninki in cur:
        cnt += 1
        if cnt % 200000 == 0:
            logger.info(f"  loaded {cnt:,} nvd_se rows...")
        if not nen or not md: continue
        md = str(md).zfill(4)
        code = str(code).zfill(2)
        try:
            race_num = int(bango)
            uma = int(umaban)
            ninki_int = int(str(ninki).strip()) if ninki else None
        except (ValueError, TypeError, AttributeError):
            continue
        if not ninki_int or ninki_int <= 0: continue
        # Correct venue
        corrected = correct_nar_venue(nen, md, code, schedule)
        venue = NAR_VENUES.get(corrected)
        if not venue: continue
        date_iso = f"{nen}-{md[:2]}-{md[2:]}"
        idx[(date_iso, venue, race_num, uma)] = ninki_int
    cur.close()
    conn.close()
    logger.info(f"  total nvd_se rows: {cnt:,}, indexed: {len(idx):,}")
    return idx


def main():
    schedule = load_schedule_master()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading NAR engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,engine,top1_horse,result_1st,result_2nd,result_3rd",
        eq={"race_type": "nar"})
    logger.info(f"  {len(hits)} NAR rows")

    if not hits:
        logger.error("no NAR engine_hit_rates")
        return 1

    earliest_date = min(h["date"] for h in hits)
    latest_date = max(h["date"] for h in hits)
    logger.info(f"  date range: {earliest_date} ~ {latest_date}")

    since_yyyymmdd = earliest_date.replace("-", "")
    until_yyyymmdd = latest_date.replace("-", "")

    pop_idx = build_pckeiba_index(since_yyyymmdd, until_yyyymmdd, schedule)

    logger.info("loading race_results (with payouts)...")
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

    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    races_data = []
    matched = unmatched_pop = unmatched_result = 0
    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        result = by_rid.get(rid)
        if not result:
            unmatched_result += 1
            continue

        any_row = next(iter(eng_rows.values()))
        date_iso = any_row["date"]
        venue = any_row["venue"]
        race_num = any_row["race_number"]

        try:
            d = datetime.strptime(date_iso, "%Y-%m-%d")
        except ValueError: continue
        wd_idx = d.weekday()
        wd = ["月","火","水","木","金","土","日"][wd_idx]

        rj = result.get("result_json") or {}
        total_horses = rj.get("total_horses") or 0
        if total_horses == 0: continue

        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        # Get popularity from PCKEIBA
        pop_rank = pop_idx.get((date_iso, venue, race_num, cons_horse))
        if pop_rank is None:
            unmatched_pop += 1
            continue

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
        matched += 1

    logger.info(f"matched: {matched}, unmatched_result: {unmatched_result}, unmatched_pop: {unmatched_pop}")

    # ============ Analysis ============
    def field_b(n):
        if n <= 9: return "6-9"
        if n <= 12: return "10-12"
        return "13+"

    def rn_b(rn):
        if rn <= 4: return "1-4R"
        if rn <= 8: return "5-8R"
        if rn <= 11: return "9-11R"
        return "12R"

    print("\n" + "=" * 78)
    print(f"【NAR ベースライン (matched={matched})】")
    print("=" * 78)
    n_total = len(races_data)
    wins_total = sum(1 for r in races_data if r["won"])
    payout_total = sum(r["payout"] for r in races_data if r["won"])
    print(f"  total: {n_total} races, win={wins_total} ({wins_total/n_total*100:.1f}%), recov={payout_total/(n_total*100)*100:.1f}%")

    def agg_by(key_fn, min_n=100):
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

    print("\n■ pop_rank (min 200R)")
    for x in agg_by(lambda r: r["pop_rank"], min_n=200):
        if x["key"] > 12: continue
        print(f"  {x['key']:>2}番人気: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ weekday (min 300R)")
    for x in agg_by(lambda r: r["wd"], min_n=300):
        print(f"  {x['key']}曜: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ venue (min 300R)")
    for x in agg_by(lambda r: r["venue"], min_n=300):
        print(f"  {x['key']:<6}: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ field_b (min 300R)")
    for x in agg_by(lambda r: field_b(r["total_horses"]), min_n=300):
        print(f"  {x['key']}頭: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ rn_b (min 300R)")
    for x in agg_by(lambda r: rn_b(r["race_num"]), min_n=300):
        print(f"  {x['key']}: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n■ consensus (min 300R)")
    for x in agg_by(lambda r: r["cons"], min_n=300):
        print(f"  {x['key']}/4一致: n={x['n']:>5} win={x['win%']:>5.1f}% recov={x['recov%']:>6.1f}%")

    print("\n" + "=" * 78)
    print("【2-Axis Combos: 100%超 (n>=100)】")
    print("=" * 78)

    print("\n■ wd × cons (min 100R)")
    seg = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
    for r in races_data:
        k = (r["wd"], r["cons"])
        s = seg[k]; s["n"]+=1
        if r["won"]: s["wins"]+=1; s["payout"]+=r["payout"]
    rows = sorted([(k, s["n"], s["wins"], s["payout"]) for k, s in seg.items() if s["n"]>=100],
                  key=lambda x: x[3]/(x[1]*100)*100 if x[1] else 0, reverse=True)
    for k, n, wins, p in rows:
        rec = p/(n*100)*100
        if rec < 100: continue
        print(f"  {k[0]}曜 × {k[1]}/4一致: n={n:>5} win={wins/n*100:>5.1f}% recov={rec:>6.1f}%")

    print("\n■ pop × cons (min 50R)")
    seg = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
    for r in races_data:
        if r["pop_rank"] > 12: continue
        k = (r["pop_rank"], r["cons"])
        s = seg[k]; s["n"]+=1
        if r["won"]: s["wins"]+=1; s["payout"]+=r["payout"]
    rows = sorted([(k, s["n"], s["wins"], s["payout"]) for k, s in seg.items() if s["n"]>=50],
                  key=lambda x: x[3]/(x[1]*100)*100 if x[1] else 0, reverse=True)
    for k, n, wins, p in rows[:15]:
        rec = p/(n*100)*100
        if rec < 100: continue
        print(f"  {k[0]}番人気 × {k[1]}/4一致: n={n:>5} win={wins/n*100:>5.1f}% recov={rec:>6.1f}%")

    print("\n■ venue × cons (min 100R)")
    seg = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
    for r in races_data:
        k = (r["venue"], r["cons"])
        s = seg[k]; s["n"]+=1
        if r["won"]: s["wins"]+=1; s["payout"]+=r["payout"]
    rows = sorted([(k, s["n"], s["wins"], s["payout"]) for k, s in seg.items() if s["n"]>=100],
                  key=lambda x: x[3]/(x[1]*100)*100 if x[1] else 0, reverse=True)
    for k, n, wins, p in rows[:20]:
        rec = p/(n*100)*100
        if rec < 100: continue
        print(f"  {k[0]} × {k[1]}/4一致: n={n:>5} win={wins/n*100:>5.1f}% recov={rec:>6.1f}%")

    print("\n" + "=" * 78)
    print("【Strict (火水木+強5+6-12頭+5-8人気+2-3一致) シミュレーション】")
    print("=" * 78)
    STRONG = {"園田", "水沢", "高知", "笠松", "金沢"}
    GOOD_WD = {1, 2, 3}
    bets = [r for r in races_data
            if r["wd_idx"] in GOOD_WD
            and r["venue"] in STRONG
            and 6 <= r["total_horses"] <= 12
            and r["cons"] in (2, 3)
            and r["pop_rank"] in (5, 6, 7, 8)]
    if bets:
        n = len(bets)
        wins = sum(1 for r in bets if r["won"])
        payout = sum(r["payout"] for r in bets if r["won"])
        invest = n * 100
        rec = payout / invest * 100

        # Daily P&L
        daily = defaultdict(int)
        for r in bets:
            daily[r["date"]] += r["profit"]
        days = sorted(daily.keys())
        plus_days = sum(1 for d in days if daily[d] > 0)
        minus_days = sum(1 for d in days if daily[d] < 0)

        max_losing = 0; cur_l = 0
        for d in days:
            if daily[d] < 0: cur_l += 1; max_losing = max(max_losing, cur_l)
            elif daily[d] > 0: cur_l = 0

        cumulative = 0; peak = 0; max_dd = 0
        for d in days:
            cumulative += daily[d]
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        print(f"  ベット数: {n} (期間: {bets[0]['date']} 〜 {bets[-1]['date']})")
        print(f"  単勝率: {wins/n*100:.1f}% ({wins}/{n})")
        print(f"  投資: ¥{invest:,}, 払戻: ¥{payout:,}")
        print(f"  回収率: {rec:.1f}%, 純利益: ¥{payout-invest:+,}")
        print(f"  実施日数: {len(days)}日 (プラス {plus_days} / マイナス {minus_days})")
        print(f"  プラス日比率: {plus_days/len(days)*100:.1f}%")
        print(f"  最長連敗日数: {max_losing}日, 最大ドローダウン: ¥{max_dd:,}")

        # Monthly
        monthly = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
        for r in bets:
            ym = r["date"][:7]
            monthly[ym]["n"] += 1
            if r["won"]:
                monthly[ym]["wins"] += 1
                monthly[ym]["payout"] += r["payout"]
        print(f"\n  月次収支:")
        for ym in sorted(monthly.keys()):
            m = monthly[ym]
            mr = m["payout"]/(m["n"]*100)*100 if m["n"] else 0
            mp = m["payout"] - m["n"]*100
            print(f"    {ym}: ベット {m['n']:>3}, 単勝 {m['wins']:>2}, 収支 ¥{mp:+6,}, 回収率 {mr:>6.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
