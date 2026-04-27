#!/usr/bin/env python3
"""NAR 深掘り分析: 5系統の追加検証.

1. 3軸組合せ (venue × pop × cons) で隠れた特異点を探索
2. エンジン単独 NAR (どのエンジンが真にアルファ持つか)
3. 外れ値選定 (3/4一致の時、1個違うエンジンが推した馬の精度)
4. 連敗後の反発 (ミーンリバージョン)
5. 発走時刻 (NARの夕方/夜)

出力: docs/engine_deep_dive_v4_*.md
"""
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime
from itertools import combinations

import psycopg2

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


def fetch_all(sb, table, select, eq=None, chunk=1000):
    rows, offset = [], 0
    while True:
        q = sb.table(table).select(select)
        if eq:
            for k, v in eq.items(): q = q.eq(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < chunk: break
        offset += chunk
    return rows


def safe_int(v):
    if v is None: return None
    s = str(v).strip()
    try: return int(s) if s else None
    except: return None


def build_pckeiba_indexes(since_yyyymmdd, until_yyyymmdd, schedule):
    logger.info(f"PCKEIBA fetch since={since_yyyymmdd} until={until_yyyymmdd}")
    conn = psycopg2.connect(**PCKEIBA_CONFIG)

    pop_idx = {}
    field_idx = {}
    cur = conn.cursor("se_cur")
    cur.itersize = 50000
    cur.execute("""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               umaban, tansho_ninkijun
        FROM nvd_se
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
    """, (since_yyyymmdd, until_yyyymmdd))
    field_count = defaultdict(int)
    for nen, md, code, bango, umaban, ninki in cur:
        if not nen or not md: continue
        md = str(md).zfill(4)
        code = str(code).zfill(2)
        race_num = safe_int(bango)
        uma = safe_int(umaban)
        if race_num is None or uma is None: continue
        ninki_int = safe_int(ninki)
        corrected = correct_nar_venue(nen, md, code, schedule)
        venue = NAR_VENUES.get(corrected)
        if not venue: continue
        date_iso = f"{nen}-{md[:2]}-{md[2:]}"
        field_count[(date_iso, venue, race_num)] += 1
        if ninki_int and ninki_int > 0:
            pop_idx[(date_iso, venue, race_num, uma)] = ninki_int
    cur.close()
    field_idx.update(field_count)

    payout_idx = {}
    cur = conn.cursor("hr_cur")
    cur.itersize = 50000
    cur.execute("""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b
        FROM nvd_hr
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
    """, (since_yyyymmdd, until_yyyymmdd))
    for nen, md, code, bango, t1a, t1b in cur:
        if not nen or not md: continue
        md = str(md).zfill(4)
        code = str(code).zfill(2)
        race_num = safe_int(bango)
        if race_num is None: continue
        winner = safe_int(t1a)
        payout = safe_int(t1b)
        if winner is None or payout is None or payout <= 0: continue
        corrected = correct_nar_venue(nen, md, code, schedule)
        venue = NAR_VENUES.get(corrected)
        if not venue: continue
        date_iso = f"{nen}-{md[:2]}-{md[2:]}"
        payout_idx[(date_iso, venue, race_num)] = (winner, payout)
    cur.close()
    conn.close()
    return pop_idx, field_idx, payout_idx


def main():
    schedule = load_schedule_master()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    logger.info("loading NAR engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,engine,top1_horse",
        eq={"race_type": "nar"})
    logger.info(f"  {len(hits):,} NAR rows")

    earliest = min(h["date"] for h in hits).replace("-", "")
    latest = max(h["date"] for h in hits).replace("-", "")

    pop_idx, field_idx, payout_idx = build_pckeiba_indexes(earliest, latest, schedule)

    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    races_data = []
    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4: continue
        any_row = next(iter(eng_rows.values()))
        date_iso = any_row["date"]
        venue = any_row["venue"]
        race_num = any_row["race_number"]

        try:
            d = datetime.strptime(date_iso, "%Y-%m-%d")
        except ValueError: continue
        wd_idx = d.weekday()
        wd = ["月","火","水","木","金","土","日"][wd_idx]

        key3 = (date_iso, venue, race_num)
        payout_info = payout_idx.get(key3)
        if not payout_info: continue
        winner, win_payout = payout_info
        total_horses = field_idx.get(key3, 0)
        if total_horses == 0: continue

        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        pop_rank = pop_idx.get((date_iso, venue, race_num, cons_horse))
        if pop_rank is None: continue

        # Per-engine: did each engine pick the winner?
        engine_correct = {eng: (picks.get(eng) == winner) for eng in picks}

        # Outlier engine: when 3/4 agree, find the "different" engine and check if its pick won
        outlier_won = None
        outlier_pop = None
        outlier_payout = 0
        if cons_count == 3:
            outlier_engs = [eng for eng, p in picks.items() if p != cons_horse]
            if outlier_engs:
                outlier_eng = outlier_engs[0]
                outlier_horse = picks[outlier_eng]
                outlier_won = (outlier_horse == winner)
                outlier_pop = pop_idx.get((date_iso, venue, race_num, outlier_horse))
                if outlier_won:
                    outlier_payout = win_payout

        won = (cons_horse == winner)
        profit = (win_payout - 100) if won else -100

        races_data.append({
            "date": date_iso, "wd_idx": wd_idx, "wd": wd,
            "venue": venue, "race_num": race_num,
            "total_horses": total_horses, "cons": cons_count,
            "pop_rank": pop_rank,
            "won": won, "payout": win_payout, "profit": profit,
            "engine_correct": engine_correct,
            "outlier_won": outlier_won, "outlier_pop": outlier_pop,
            "outlier_payout": outlier_payout,
        })

    races_data.sort(key=lambda r: (r["date"], r["venue"], r["race_num"]))
    n_total = len(races_data)
    logger.info(f"matched: {n_total:,}")

    # ============ Output ============
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs",
        f"engine_deep_dive_v4_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
    )

    lines = []
    lines.append(f"# NAR深掘り分析 v4 — 5系統の追加検証\n")
    lines.append(f"**作成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**サンプル**: NAR matched={n_total:,}レース")
    lines.append(f" (期間: {earliest[:4]}-{earliest[4:6]}-{earliest[6:]} 〜 {latest[:4]}-{latest[4:6]}-{latest[6:]})\n")

    # ============ 1. 3軸組合せ ============
    lines.append("\n## 1. 3軸組合せ: venue × pop × cons (recov>=130%, n>=30)\n")

    seg = defaultdict(lambda: {"n": 0, "wins": 0, "payout": 0})
    for r in races_data:
        if r["pop_rank"] > 12: continue
        k = (r["venue"], r["pop_rank"], r["cons"])
        s = seg[k]
        s["n"] += 1
        if r["won"]: s["wins"] += 1; s["payout"] += r["payout"]
    rows = []
    for k, s in seg.items():
        if s["n"] < 30: continue
        rec = s["payout"] / (s["n"] * 100) * 100
        if rec < 130: continue
        rows.append((k, s["n"], s["wins"], rec))
    rows.sort(key=lambda x: x[3], reverse=True)

    lines.append("| 会場 | 人気 | 合議 | races | win% | recov% |")
    lines.append("|---|---|---|---|---|---|")
    for k, n, wins, rec in rows[:30]:
        marker = " 🚀" if rec > 200 else " ✅"
        lines.append(f"| {k[0]} | {k[1]}人気 | {k[2]}/4 | {n} | {wins/n*100:.1f}% | **{rec:.1f}%**{marker} |")

    lines.append(f"\n→ 100%超セグメント数: {len([r for r in seg.values() if r['n']>=30 and r['payout']/(r['n']*100)*100 >= 100])}")

    # ============ 2. エンジン単独 NAR ============
    lines.append("\n## 2. エンジン単独 NAR (誰が真のアルファ持ちか)\n")

    eng_stats = defaultdict(lambda: {"n": 0, "wins": 0, "payout": 0})
    for r in races_data:
        for eng, correct in r["engine_correct"].items():
            es = eng_stats[eng]
            es["n"] += 1
            if correct:
                es["wins"] += 1
                es["payout"] += r["payout"]

    lines.append("| エンジン | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for eng in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
        s = eng_stats[eng]
        if s["n"] == 0: continue
        rec = s["payout"] / (s["n"] * 100) * 100
        lines.append(f"| {eng} | {s['n']:,} | {s['wins']/s['n']*100:.1f}% | **{rec:.1f}%** |")

    # Engine × pop_rank
    lines.append("\n### エンジン × 人気 (S本命の人気が何番だった時の単独回収率)\n")
    eng_pop = defaultdict(lambda: defaultdict(lambda: {"n":0,"wins":0,"payout":0}))
    for r in races_data:
        for eng, correct in r["engine_correct"].items():
            # We need the engine's own top1 popularity, not consensus
            # but races_data only has consensus pop_rank
            # For simplification: use consensus pop_rank when this engine agrees with consensus
            # Otherwise skip (different pop)
            pass
    # This requires per-engine pop_rank lookup. Skip for now.

    # ============ 3. 外れ値選定 (3/4一致時の1個違うエンジンの精度) ============
    lines.append("\n## 3. 外れ値選定: 3/4一致時に1個だけ違うエンジンが推した馬の精度\n")
    lines.append("3エンジンが同じ馬を本命にした時、残り1個のエンジンが選んだ「別の馬」の単勝率と回収率。\n")

    n_outlier = 0
    o_wins = 0
    o_payout = 0
    o_by_pop = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
    for r in races_data:
        if r["cons"] != 3 or r["outlier_won"] is None: continue
        n_outlier += 1
        if r["outlier_won"]:
            o_wins += 1
            o_payout += r["outlier_payout"]
        if r["outlier_pop"] and r["outlier_pop"] <= 12:
            ob = o_by_pop[r["outlier_pop"]]
            ob["n"] += 1
            if r["outlier_won"]:
                ob["wins"] += 1
                ob["payout"] += r["outlier_payout"]

    if n_outlier:
        rec = o_payout / (n_outlier * 100) * 100
        lines.append(f"- 全体: {n_outlier}レース, 単勝率 {o_wins/n_outlier*100:.1f}%, **回収率 {rec:.1f}%**\n")

    lines.append("\n人気別 (min 30):\n")
    lines.append("| 外れ馬の人気 | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for pop in sorted(o_by_pop.keys()):
        s = o_by_pop[pop]
        if s["n"] < 30: continue
        rec = s["payout"] / (s["n"] * 100) * 100
        marker = " ✅" if rec >= 100 else ""
        lines.append(f"| {pop}番人気 | {s['n']} | {s['wins']/s['n']*100:.1f}% | {rec:.1f}%{marker} |")

    # ============ 4. 連敗後の反発 (ミーンリバージョン) ============
    lines.append("\n## 4. 連敗後の反発 (ミーンリバージョン)\n")
    lines.append("Strict v3条件 (火水木+園田5強+6-12頭+5-8人気+2-3一致) でのN連敗後の翌レース勝率\n")

    STRONG_V3 = {"園田", "水沢", "高知", "笠松", "金沢"}
    GOOD_WD = {1, 2, 3}
    bets = [r for r in races_data
            if r["wd_idx"] in GOOD_WD
            and r["venue"] in STRONG_V3
            and 6 <= r["total_horses"] <= 12
            and r["cons"] in (2, 3)
            and r["pop_rank"] in (5, 6, 7, 8)]

    if bets:
        # Calc previous loss streak before each bet
        consecutive_losses = 0
        streak_perf = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
        for r in bets:
            cl_bucket = consecutive_losses if consecutive_losses < 5 else "5+"
            s = streak_perf[cl_bucket]
            s["n"] += 1
            if r["won"]:
                s["wins"] += 1
                s["payout"] += r["payout"]
                consecutive_losses = 0
            else:
                consecutive_losses += 1

        lines.append("| 直前の連敗数 | races | win% | recov% |")
        lines.append("|---|---|---|---|")
        for k in [0, 1, 2, 3, 4, "5+"]:
            s = streak_perf.get(k)
            if not s or s["n"] < 10: continue
            rec = s["payout"] / (s["n"] * 100) * 100 if s["n"] else 0
            wr = s["wins"]/s["n"]*100
            marker = " 🚀" if rec > 200 else (" ✅" if rec > 100 else "")
            lines.append(f"| {k}連敗後 | {s['n']} | {wr:.1f}% | {rec:.1f}%{marker} |")

    # ============ 5. 発走時刻別 ============
    lines.append("\n## 5. レース番号 × 会場 (発走時刻代替)\n")
    lines.append("NARは race_num が大きいほど夕方〜夜開催。レース番号と会場で時間帯バイアスを見る。\n")

    rn_venue = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
    for r in races_data:
        if r["pop_rank"] != 6: continue  # 6人気特化で見る
        bucket = "1-4R" if r["race_num"] <= 4 else ("5-8R" if r["race_num"] <= 8 else ("9-11R" if r["race_num"] <= 11 else "12R+"))
        k = (r["venue"], bucket)
        s = rn_venue[k]
        s["n"] += 1
        if r["won"]:
            s["wins"] += 1
            s["payout"] += r["payout"]

    lines.append("\n6番人気時の (会場 × 発走時刻帯) min 30:\n")
    lines.append("| 会場 | 時間帯 | races | win% | recov% |")
    lines.append("|---|---|---|---|---|")
    rows = sorted(
        [(k, s["n"], s["wins"], s["payout"]/(s["n"]*100)*100) for k, s in rn_venue.items() if s["n"]>=30],
        key=lambda x: x[3], reverse=True
    )
    for k, n, wins, rec in rows[:20]:
        marker = " 🚀" if rec > 200 else (" ✅" if rec > 100 else "")
        lines.append(f"| {k[0]} | {k[1]} | {n} | {wins/n*100:.1f}% | {rec:.1f}%{marker} |")

    # ============ 6. 強Strict v4 (新ルール候補) シミュレーション ============
    lines.append("\n## 6. 新Strict ルール候補シミュレーション\n")

    # Candidate 1: 南関東 + 6人気 + 2-3一致
    SOUTH_NANKAN = {"川崎", "船橋", "大井", "浦和"}
    cand1 = [r for r in races_data
             if r["venue"] in SOUTH_NANKAN
             and r["pop_rank"] == 6
             and r["cons"] in (2, 3)]
    # Candidate 2: 6人気 + 2-3一致 (会場不問)
    cand2 = [r for r in races_data
             if r["pop_rank"] == 6 and r["cons"] in (2, 3)]
    # Candidate 3: 全南関東4場 + 2-3一致 (人気不問)
    cand3 = [r for r in races_data
             if r["venue"] in SOUTH_NANKAN and r["cons"] in (2, 3)]
    # Candidate 4: NAR強会場拡大 (川崎/船橋/大井/浦和/門別/笠松) + 6人気 + 2-3一致
    STRONG_V4 = {"川崎", "船橋", "大井", "浦和", "門別", "笠松"}
    cand4 = [r for r in races_data
             if r["venue"] in STRONG_V4
             and r["pop_rank"] == 6
             and r["cons"] in (2, 3)]
    # Candidate 5: 13+頭 + 6人気 + 2-3一致
    cand5 = [r for r in races_data
             if r["total_horses"] >= 13
             and r["pop_rank"] == 6
             and r["cons"] in (2, 3)]
    # Candidate 6: 全期間 6人気 + 2-3一致 (単純)
    # = cand2

    candidates = [
        ("A1: 6人気+2-3一致 (会場不問)", cand2),
        ("A2: 南関東4場 + 6人気 + 2-3一致", cand1),
        ("A3: 強会場v4 (川崎/船橋/大井/浦和/門別/笠松) + 6人気 + 2-3一致", cand4),
        ("A4: 13+頭 + 6人気 + 2-3一致", cand5),
        ("A5: 南関東4場 + 2-3一致 (人気不問)", cand3),
    ]

    for name, bets in candidates:
        if not bets:
            lines.append(f"\n### {name}\n対象なし")
            continue
        n = len(bets)
        wins = sum(1 for r in bets if r["won"])
        payout = sum(r["payout"] for r in bets if r["won"])
        invest = n * 100
        rec = payout / invest * 100
        daily = defaultdict(int)
        for r in bets: daily[r["date"]] += r["profit"]
        days = sorted(daily.keys())
        plus_days = sum(1 for d in days if daily[d] > 0)

        max_losing = 0; cur_l = 0
        for d in days:
            if daily[d] < 0: cur_l += 1; max_losing = max(max_losing, cur_l)
            elif daily[d] > 0: cur_l = 0
        cumulative = 0; peak = 0; max_dd = 0
        for d in days:
            cumulative += daily[d]
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        lines.append(f"\n### {name}\n")
        lines.append(f"- ベット {n}, 単勝 {wins} ({wins/n*100:.1f}%), **回収率 {rec:.1f}%**, 純利益 ¥{payout-invest:+,}")
        lines.append(f"- 実施日数 {len(days)} (プラス {plus_days}, {plus_days/len(days)*100:.0f}%)")
        lines.append(f"- 最長連敗 {max_losing}日, 最大DD ¥{max_dd:,}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"DONE: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
