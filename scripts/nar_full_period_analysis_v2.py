#!/usr/bin/env python3
"""NAR 全期間分析 v2 — PCKEIBA から人気・結果を直接取得.

race_results テーブルへの依存を削除。nvd_hr (払戻) と nvd_se (出馬)
から直接、勝ち馬・単勝払戻・人気順位・出走頭数を取得する。

これでバックフィル後の全期間 (約8,000レース) で人気軸を含む分析が
可能になる。出力は markdown レポート。
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
    """nvd_se と nvd_hr から各種 index を構築."""
    logger.info(f"PCKEIBA fetch since={since_yyyymmdd} until={until_yyyymmdd}")
    conn = psycopg2.connect(**PCKEIBA_CONFIG)

    # ----- nvd_se: 人気 + 出走頭数 -----
    pop_idx = {}  # (date_iso, venue, race_num, umaban) -> ninkijun
    field_idx = {}  # (date_iso, venue, race_num) -> total_horses
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
    logger.info(f"  nvd_se: {len(pop_idx):,} pop entries, {len(field_idx):,} races")

    # ----- nvd_hr: 結果 + 単勝払戻 -----
    payout_idx = {}  # (date_iso, venue, race_num) -> (winner_umaban, win_payout)
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
    logger.info(f"  nvd_hr: {len(payout_idx):,} payout entries")

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
    if not hits:
        return 1

    earliest = min(h["date"] for h in hits).replace("-", "")
    latest = max(h["date"] for h in hits).replace("-", "")
    logger.info(f"  range: {earliest} ~ {latest}")

    pop_idx, field_idx, payout_idx = build_pckeiba_indexes(earliest, latest, schedule)

    by_race = defaultdict(dict)
    for h in hits:
        by_race[h["race_id"]][h["engine"]] = h

    races_data = []
    no_payout = no_pop = 0
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
        if not payout_info:
            no_payout += 1
            continue
        winner, win_payout = payout_info

        total_horses = field_idx.get(key3, 0)
        if total_horses == 0: continue

        picks = {eng: r["top1_horse"] for eng, r in eng_rows.items()}
        cnt = Counter(picks.values())
        cons_horse, cons_count = cnt.most_common(1)[0]

        pop_rank = pop_idx.get((date_iso, venue, race_num, cons_horse))
        if pop_rank is None:
            no_pop += 1
            continue

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
    logger.info(f"matched: {len(races_data):,}, no_payout: {no_payout}, no_pop: {no_pop}")

    # ============ Render markdown report ============
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs",
        f"engine_accuracy_audit_v4_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
    )

    lines = []
    lines.append(f"# 監査v4 — NAR全期間分析 (PCKEIBA直接照合、リーク除去)\n")
    lines.append(f"**作成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**サンプル**: NAR matched={len(races_data):,}レース")
    lines.append(f" (期間: {earliest[:4]}-{earliest[4:6]}-{earliest[6:]} 〜 {latest[:4]}-{latest[4:6]}-{latest[6:]})\n")
    lines.append("\n## 0. データ品質\n")
    lines.append(f"- NAR engine_hit_rates: {len(hits):,} 行")
    lines.append(f"- PCKEIBA 単勝払戻: {len(payout_idx):,} レース")
    lines.append(f"- PCKEIBA 人気: {len(pop_idx):,} 馬")
    lines.append(f"- マッチ成功: {len(races_data):,} ({len(races_data)/len(by_race)*100:.1f}%)")
    lines.append(f"- 未照合 (no_payout): {no_payout}, 未照合 (no_pop): {no_pop}")

    n_total = len(races_data)
    if n_total == 0:
        lines.append("\n⚠️ データ無し")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.error("no matched races")
        return 1

    wins_total = sum(1 for r in races_data if r["won"])
    payout_total = sum(r["payout"] for r in races_data if r["won"])
    lines.append(f"\n## 1. NAR ベースライン\n")
    lines.append(f"- 全 {n_total:,} レース")
    lines.append(f"- 単勝率: **{wins_total/n_total*100:.1f}%** ({wins_total}/{n_total})")
    lines.append(f"- 回収率: **{payout_total/(n_total*100)*100:.1f}%**")
    lines.append(f"- 純利益: ¥{payout_total - n_total*100:+,}")

    def field_b(n):
        if n <= 9: return "6-9"
        if n <= 12: return "10-12"
        return "13+"

    def rn_b(rn):
        if rn <= 4: return "1-4R"
        if rn <= 8: return "5-8R"
        if rn <= 11: return "9-11R"
        return "12R"

    def agg_by(key_fn, min_n=200):
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

    lines.append("\n## 2. 単軸別分析\n")

    lines.append("\n### 人気順位 (min 300R)\n")
    lines.append("| 人気 | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for x in agg_by(lambda r: r["pop_rank"], min_n=300):
        if x["key"] > 12: continue
        marker = " 🚀" if x["recov%"] > 150 else (" ✅" if x["recov%"] > 100 else "")
        lines.append(f"| {x['key']}番人気 | {x['n']:,} | {x['win%']:.1f}% | **{x['recov%']:.1f}%**{marker} |")

    lines.append("\n### 曜日 (min 500R)\n")
    lines.append("| 曜日 | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for x in agg_by(lambda r: r["wd"], min_n=500):
        marker = " ✅" if x["recov%"] > 100 else ""
        lines.append(f"| {x['key']}曜 | {x['n']:,} | {x['win%']:.1f}% | **{x['recov%']:.1f}%**{marker} |")

    lines.append("\n### 会場 (min 300R)\n")
    lines.append("| 会場 | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for x in agg_by(lambda r: r["venue"], min_n=300):
        marker = " ✅" if x["recov%"] > 100 else (" ❌" if x["recov%"] < 60 else "")
        lines.append(f"| {x['key']} | {x['n']:,} | {x['win%']:.1f}% | **{x['recov%']:.1f}%**{marker} |")

    lines.append("\n### 出走頭数 (min 500R)\n")
    lines.append("| 頭数 | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for x in agg_by(lambda r: field_b(r["total_horses"]), min_n=500):
        lines.append(f"| {x['key']}頭 | {x['n']:,} | {x['win%']:.1f}% | {x['recov%']:.1f}% |")

    lines.append("\n### 合議度 (min 500R)\n")
    lines.append("| 合議 | races | win% | recov% |")
    lines.append("|---|---|---|---|")
    for x in agg_by(lambda r: r["cons"], min_n=500):
        lines.append(f"| {x['key']}/4一致 | {x['n']:,} | {x['win%']:.1f}% | {x['recov%']:.1f}% |")

    # Multi-axis
    lines.append("\n## 3. 多軸組合せ (n>=100, recov>=120%)\n")

    def multi(combo_fn, min_n=100, min_recov=120):
        seg = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
        for r in races_data:
            k = combo_fn(r)
            if k is None: continue
            s = seg[k]; s["n"]+=1
            if r["won"]: s["wins"]+=1; s["payout"]+=r["payout"]
        rows = []
        for k, s in seg.items():
            if s["n"] < min_n: continue
            rec = s["payout"]/(s["n"]*100)*100
            if rec < min_recov: continue
            rows.append((k, s["n"], s["wins"], rec))
        return sorted(rows, key=lambda x: x[3], reverse=True)

    lines.append("\n### 曜日 × 合議度\n")
    lines.append("| 曜日 | 合議 | races | win% | recov% |")
    lines.append("|---|---|---|---|---|")
    for k, n, wins, rec in multi(lambda r: (r["wd"], r["cons"]), min_n=100, min_recov=100):
        marker = " 🚀" if rec > 200 else " ✅"
        lines.append(f"| {k[0]} | {k[1]}/4 | {n:,} | {wins/n*100:.1f}% | **{rec:.1f}%**{marker} |")

    lines.append("\n### 人気 × 合議度\n")
    lines.append("| 人気 | 合議 | races | win% | recov% |")
    lines.append("|---|---|---|---|---|")
    for k, n, wins, rec in multi(lambda r: (r["pop_rank"], r["cons"]) if r["pop_rank"] <= 12 else None, min_n=80, min_recov=100):
        marker = " 🚀" if rec > 200 else " ✅"
        lines.append(f"| {k[0]}人気 | {k[1]}/4 | {n:,} | {wins/n*100:.1f}% | **{rec:.1f}%**{marker} |")

    lines.append("\n### 会場 × 合議度\n")
    lines.append("| 会場 | 合議 | races | win% | recov% |")
    lines.append("|---|---|---|---|---|")
    for k, n, wins, rec in multi(lambda r: (r["venue"], r["cons"]), min_n=100, min_recov=100):
        marker = " 🚀" if rec > 200 else " ✅"
        lines.append(f"| {k[0]} | {k[1]}/4 | {n:,} | {wins/n*100:.1f}% | **{rec:.1f}%**{marker} |")

    # Strict simulation
    STRONG = {"園田", "水沢", "高知", "笠松", "金沢"}
    GOOD_WD = {1, 2, 3}
    bets = [r for r in races_data
            if r["wd_idx"] in GOOD_WD
            and r["venue"] in STRONG
            and 6 <= r["total_horses"] <= 12
            and r["cons"] in (2, 3)
            and r["pop_rank"] in (5, 6, 7, 8)]

    lines.append("\n## 4. Strict ルール 全期間シミュレーション\n")
    lines.append("**条件**: 火水木 + 強5会場 (園田/水沢/高知/笠松/金沢) + 6-12頭 + 5-8人気 + 2-3一致\n")

    if bets:
        n = len(bets)
        wins = sum(1 for r in bets if r["won"])
        payout = sum(r["payout"] for r in bets if r["won"])
        invest = n * 100
        rec = payout / invest * 100

        daily = defaultdict(int)
        for r in bets:
            daily[r["date"]] += r["profit"]
        days = sorted(daily.keys())
        plus_days = sum(1 for d in days if daily[d] > 0)
        minus_days = sum(1 for d in days if daily[d] < 0)
        zero_days = sum(1 for d in days if daily[d] == 0)

        max_losing = 0; cur_l = 0
        for d in days:
            if daily[d] < 0: cur_l += 1; max_losing = max(max_losing, cur_l)
            elif daily[d] > 0: cur_l = 0

        cumulative = 0; peak = 0; max_dd = 0
        for d in days:
            cumulative += daily[d]
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        lines.append(f"| 項目 | 値 |")
        lines.append(f"|---|---|")
        lines.append(f"| ベット数 | {n:,} |")
        lines.append(f"| 単勝率 | {wins/n*100:.1f}% ({wins}/{n}) |")
        lines.append(f"| 投資 | ¥{invest:,} |")
        lines.append(f"| 払戻 | ¥{payout:,} |")
        lines.append(f"| **回収率** | **{rec:.1f}%** |")
        lines.append(f"| 純利益 | ¥{payout-invest:+,} |")
        lines.append(f"| 実施日数 | {len(days)}日 (プラス {plus_days} / マイナス {minus_days} / ゼロ {zero_days}) |")
        lines.append(f"| プラス日比率 | {plus_days/len(days)*100:.1f}% |")
        lines.append(f"| 最長連敗日数 | {max_losing}日 |")
        lines.append(f"| 最大ドローダウン | ¥{max_dd:,} |")

        # Monthly
        monthly = defaultdict(lambda: {"n":0,"wins":0,"payout":0})
        for r in bets:
            ym = r["date"][:7]
            monthly[ym]["n"] += 1
            if r["won"]:
                monthly[ym]["wins"] += 1
                monthly[ym]["payout"] += r["payout"]
        lines.append("\n### 月次収支\n")
        lines.append("| 月 | ベット | 単勝 | 収支 | 回収率 |")
        lines.append("|---|---|---|---|---|")
        for ym in sorted(monthly.keys()):
            m = monthly[ym]
            mr = m["payout"]/(m["n"]*100)*100 if m["n"] else 0
            mp = m["payout"] - m["n"]*100
            marker = " ✅" if mp > 0 else (" ❌" if mp < 0 else "")
            lines.append(f"| {ym} | {m['n']:,} | {m['wins']} | **¥{mp:+,}**{marker} | {mr:.1f}% |")

    lines.append("\n## 5. 結論\n")
    if bets and rec > 200:
        lines.append(f"**Strict ルールは {n}レースの長期サンプルで回収率 {rec:.1f}% を維持。再現性確認。**\n")
    elif bets and rec > 100:
        lines.append(f"**Strict ルールは {n}レースで回収率 {rec:.1f}%。プラスだが v3 (457%) より下振れ。**\n")
    elif bets:
        lines.append(f"**Strict ルールは {n}レースで回収率 {rec:.1f}%。長期では弱い可能性。**\n")

    lines.append("v3 (1,309レース) との比較:")
    lines.append(f"- v3 Strict 回収率: 457.3% / 116ベット")
    if bets:
        lines.append(f"- v4 Strict 回収率: **{rec:.1f}%** / **{n:,}ベット** ({n/116:.1f}倍のサンプル)")
        verdict = "再現性確認" if rec > 250 else ("弱い再現" if rec > 100 else "再現性なし、要再評価")
        lines.append(f"- 判定: **{verdict}**")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"DONE: report saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
