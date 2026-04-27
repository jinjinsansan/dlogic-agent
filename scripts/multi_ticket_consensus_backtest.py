#!/usr/bin/env python3
"""Multi-ticket consensus backtest (1年NAR+JRA).

各エンジンの top3 出力を「投票」と見なし、馬ごとの投票数 (1-4) で
重なり度を判定。単勝・複勝・ワイド・馬連・3連複 の各馬券種について、
重なり度・会場・人気・曜日でセグメント化した回収率を出す。

データソース:
- Supabase engine_hit_rates: 1年の top1/top3 (4エンジン)
- PCKEIBA nvd_hr/jvd_hr: 全7馬券種払戻
- PCKEIBA nvd_se/jvd_se: 馬番・人気・着順

ローカル実行 (PCKEIBA がローカル). Supabase 鍵は VPS .env.local から SSH で取得.

Usage: python scripts/multi_ticket_consensus_backtest.py [--out DOC]
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime
from itertools import combinations
from typing import Optional

import psycopg2

# ---- env: Supabase keys from VPS ----
def load_supabase_env():
    out = subprocess.check_output(
        ['ssh', 'root@220.158.24.157',
         'grep -E "^(SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=" /opt/dlogic/linebot/.env.local'],
        text=True, timeout=15,
    )
    for line in out.strip().split('\n'):
        k, v = line.split('=', 1)
        os.environ[k] = v


load_supabase_env()
from supabase import create_client

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")

PCKEIBA_CONFIG = {
    "host": "127.0.0.1", "port": 5432, "database": "pckeiba",
    "user": "postgres", "password": "postgres",
}

JRA_VENUES = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟',
    '05': '東京', '06': '中山', '07': '中京', '08': '京都',
    '09': '阪神', '10': '小倉',
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
    os.path.join(PROJECT_DIR, "data", "nar_schedule_master_2020_2026.json"),
    r"E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json",
]


def load_schedule_master():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return None


def correct_nar_venue(nen, tsukihi, code, schedule):
    if not schedule or 'schedule_data' not in schedule:
        return code
    race_date = f"{nen}{tsukihi}"
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


def safe_int(v):
    if v is None: return 0
    s = str(v).strip()
    try: return int(s) if s else 0
    except (ValueError, TypeError): return 0


def parse_horse_pair(s: str):
    """'0304' → (3, 4)  / '030407' → (3, 4, 7)  / '03' → (3,)"""
    s = (s or "").strip()
    if not s or s == "00": return ()
    if len(s) % 2 != 0: return ()
    parts = []
    for i in range(0, len(s), 2):
        try: parts.append(int(s[i:i+2]))
        except ValueError: return ()
    return tuple(parts)


def parse_payout(s: str) -> int:
    """'000003690' → 3690"""
    return safe_int(s)


# -------------- engine_hit_rates ロード --------------
def fetch_all(sb, table, select="*", chunk=1000, gte=None, lte=None):
    rows, offset = [], 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items(): q = q.gte(k, v)
        if lte:
            for k, v in lte.items(): q = q.lte(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < chunk: break
        offset += chunk
    return rows


def load_engine_data(sb, since_date: str, until_date: str, clean_only: bool = True):
    """engine_hit_rates から各レースの (engine -> top3) と (engine -> top1) を構築.

    clean_only=True: created_at <= race_date のみ採用 (leakage除去).
    """
    logger.info(f"loading engine_hit_rates {since_date} ~ {until_date} clean_only={clean_only}...")
    rows = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at",
        gte={"date": since_date}, lte={"date": until_date})
    logger.info(f"  {len(rows)} engine rows (raw)")

    # Filter clean rows
    if clean_only:
        clean = []
        skipped = 0
        for r in rows:
            try:
                rd = datetime.strptime(r['date'], '%Y-%m-%d').date()
                cd = datetime.fromisoformat(r['created_at'].replace('Z','+00:00')).date()
                gap = (cd - rd).days
            except (ValueError, TypeError):
                skipped += 1
                continue
            if gap <= 0:
                clean.append(r)
            else:
                skipped += 1
        logger.info(f"  clean (gap<=0): {len(clean)}, skipped (post-race created): {skipped}")
        rows = clean

    # Group by race_id
    by_race = defaultdict(dict)  # race_id -> {engine: (top1, top3)}
    race_meta = {}  # race_id -> (date, venue, race_number, race_type)
    for r in rows:
        rid = r["race_id"]
        by_race[rid][r["engine"]] = (r["top1_horse"], r["top3_horses"] or [])
        race_meta[rid] = (r["date"], r["venue"], r["race_number"], r["race_type"])
    logger.info(f"  unique races: {len(by_race)}")

    # Filter to races with at least 3 engines (need enough votes)
    full = {rid: e for rid, e in by_race.items() if len(e) >= 3}
    logger.info(f"  with >=3 engines: {len(full)}")
    return full, race_meta


# -------------- PCKEIBA ロード --------------
def load_pckeiba_data(conn, table_se, table_hr, race_type, since_yyyymmdd, schedule):
    """Load all races in date range with payouts + per-horse popularity/finish.
    Returns dict: race_key -> race_data
    where race_key = (date_yyyymmdd_str, venue_name, race_no_int)
    """
    since_nen = since_yyyymmdd[:4]
    since_md = since_yyyymmdd[4:]
    logger.info(f"  pulling {table_hr} payouts (since {since_yyyymmdd})...")
    cur = conn.cursor()
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b,
               haraimodoshi_fukusho_1a, haraimodoshi_fukusho_1b,
               haraimodoshi_fukusho_2a, haraimodoshi_fukusho_2b,
               haraimodoshi_fukusho_3a, haraimodoshi_fukusho_3b,
               haraimodoshi_wide_1a, haraimodoshi_wide_1b,
               haraimodoshi_wide_2a, haraimodoshi_wide_2b,
               haraimodoshi_wide_3a, haraimodoshi_wide_3b,
               haraimodoshi_umaren_1a, haraimodoshi_umaren_1b,
               haraimodoshi_sanrenpuku_1a, haraimodoshi_sanrenpuku_1b
        FROM {table_hr}
        WHERE (kaisai_nen > %s) OR (kaisai_nen = %s AND kaisai_tsukihi >= %s)
    """, (since_nen, since_nen, since_md))

    races = {}  # key -> data
    for row in cur.fetchall():
        nen, md, code, bango = row[0], row[1], row[2], row[3]

        # venue resolution
        if race_type == 'jra':
            venue = JRA_VENUES.get(code)
        else:
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = NAR_VENUES.get(cc)
        if not venue: continue

        try:
            race_no = int(bango)
        except (ValueError, TypeError):
            continue

        date_str = f"{nen}-{md[:2]}-{md[2:4]}"
        key = (date_str, venue, race_no)

        # winner
        winner_horse = parse_horse_pair(row[4])
        winner_payout = parse_payout(row[5])
        if not winner_horse:
            continue

        # 複勝 (3 entries — last may be empty for small fields)
        place_payouts = {}  # horse -> payout
        for i, (idx_a, idx_b) in enumerate([(6,7),(8,9),(10,11)]):
            hh = parse_horse_pair(row[idx_a])
            pp = parse_payout(row[idx_b])
            if hh and pp > 0:
                place_payouts[hh[0]] = pp

        # ワイド (3 entries — pair → payout)
        wide_payouts = {}  # frozenset({h1,h2}) -> payout
        for idx_a, idx_b in [(12,13),(14,15),(16,17)]:
            pair = parse_horse_pair(row[idx_a])
            pp = parse_payout(row[idx_b])
            if len(pair) == 2 and pp > 0:
                wide_payouts[frozenset(pair)] = pp

        # 馬連
        umaren_pair = parse_horse_pair(row[18])
        umaren_payout = parse_payout(row[19])
        umaren = (frozenset(umaren_pair), umaren_payout) if len(umaren_pair) == 2 and umaren_payout > 0 else None

        # 3連複
        spk_trio = parse_horse_pair(row[20])
        spk_payout = parse_payout(row[21])
        sanrenpuku = (frozenset(spk_trio), spk_payout) if len(spk_trio) == 3 and spk_payout > 0 else None

        races[key] = {
            "winner": winner_horse[0],
            "win_payout": winner_payout,
            "place_payouts": place_payouts,
            "wide_payouts": wide_payouts,
            "umaren": umaren,
            "sanrenpuku": sanrenpuku,
            "race_type": race_type,
            "venue": venue,
            "race_no": race_no,
            "date_str": date_str,
            "weekday": ["月","火","水","木","金","土","日"][datetime.strptime(f"{nen}{md}", "%Y%m%d").weekday()],
        }
    cur.close()
    logger.info(f"  {len(races)} {race_type} races loaded with payouts")

    # Now load per-horse popularity + finish from se table
    logger.info(f"  pulling {table_se} per-horse data...")
    cur = conn.cursor("se_cur")
    cur.itersize = 50000
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               umaban, tansho_ninkijun, kakutei_chakujun
        FROM {table_se}
        WHERE (kaisai_nen > %s) OR (kaisai_nen = %s AND kaisai_tsukihi >= %s)
    """, (since_nen, since_nen, since_md))
    se_count = 0
    for row in cur:
        nen, md, code, bango, umaban, ninki, chaku = row
        if race_type == 'jra':
            venue = JRA_VENUES.get(code)
        else:
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = NAR_VENUES.get(cc)
        if not venue: continue
        try:
            race_no = int(bango)
            horse = int(str(umaban).strip())
            pop = int(str(ninki).strip())
        except (ValueError, TypeError):
            continue
        date_str = f"{nen}-{md[:2]}-{md[2:4]}"
        key = (date_str, venue, race_no)
        race = races.get(key)
        if not race: continue
        race.setdefault("horses", {})[horse] = {
            "pop": pop,
            "finish": safe_int(chaku),
        }
        se_count += 1
    cur.close()
    logger.info(f"  {se_count} {race_type} per-horse rows attached")

    # Compute popularity rank lookup, field size
    for race in races.values():
        horses = race.get("horses", {})
        race["field_size"] = len(horses)
        # 2nd, 3rd places
        sorted_by_finish = sorted(
            [(h, d["finish"]) for h, d in horses.items() if d["finish"] > 0],
            key=lambda x: x[1])
        race["top3_finish"] = [h for h, _ in sorted_by_finish[:3]]

    return races


# -------------- 馬投票数の計算 --------------
def compute_vote_data(by_race, race_meta, races_pck):
    """各レース毎に各馬の投票数を計算. レースを race_data dict にマージ."""
    matched = 0
    for rid, eng_picks in by_race.items():
        date, venue, race_no, race_type = race_meta[rid]
        key = (date, venue, race_no)
        race = races_pck.get(key)
        if not race:
            continue

        # 投票カウント (top3 ベース)
        votes_top3 = Counter()
        votes_top1 = Counter()
        for engine, (top1, top3) in eng_picks.items():
            for h in (top3 or []):
                if h: votes_top3[h] += 1
            if top1:
                votes_top1[top1] += 1

        # 馬ごとに引ける形に
        race["votes_top3"] = dict(votes_top3)  # horse -> count (1-4)
        race["votes_top1"] = dict(votes_top1)  # horse -> count (1-4)
        race["engines_count"] = len(eng_picks)
        race["matched"] = True
        matched += 1
    logger.info(f"matched {matched} races (engine × pckeiba)")
    return matched


# -------------- 戦略バックテスト --------------
def run_strategies(races: dict) -> dict:
    """各戦略×全レースで投資・払戻を集計.
    Returns: {strategy_name: {filter_key: {races, invested, payout, hits}}}
    """
    results = defaultdict(lambda: defaultdict(lambda: {"races":0, "invested":0, "payout":0, "hits":0}))

    valid_races = [r for r in races.values() if r.get("matched")]
    logger.info(f"running strategies over {len(valid_races)} matched races")

    for race in valid_races:
        winner = race["winner"]
        win_payout = race["win_payout"]
        place_p = race["place_payouts"]
        wide_p = race["wide_payouts"]
        umaren = race["umaren"]
        sanren = race["sanrenpuku"]
        votes_top3 = race.get("votes_top3", {})
        votes_top1 = race.get("votes_top1", {})

        rt = race["race_type"]
        venue = race["venue"]
        wd = race["weekday"]
        horses_meta = race.get("horses", {})

        # === 投票度別の馬リスト ===
        all4_horses = [h for h, c in votes_top3.items() if c == 4]   # 全エンジン top3 一致
        all3plus = [h for h, c in votes_top3.items() if c >= 3]
        all2plus = [h for h, c in votes_top3.items() if c >= 2]
        # top1合議 (各エンジンの1位)
        top1_2plus = [h for h, c in votes_top1.items() if c >= 2]
        top1_3plus = [h for h, c in votes_top1.items() if c >= 3]

        # 投票数で降順ソート (top3 ベース、tie で top1 ボーナス)
        ranked_by_votes = sorted(
            votes_top3.items(),
            key=lambda x: (-x[1], -votes_top1.get(x[0], 0), x[0])
        )

        # ====== 戦略リスト ======
        # Each entry: (strategy_name, picks: list[horse], cost (total in 100yen units), payout_func)
        # picks 形は 単勝なら [horse], ワイド/馬連なら [(h1,h2),...], 3連複は [(h1,h2,h3),...]

        bets = []  # list of (strategy, segment_filter, cost, payout)

        # --- 単勝戦略 ---
        # T-A: 4票一致馬 → 単勝 (各 100yen)
        for h in all4_horses:
            payout = win_payout if h == winner else 0
            bets.append(("T-A 4票一致馬の単勝", h, 100, payout))
        # T-B: 3票以上の馬 → 単勝
        for h in all3plus:
            if h in all4_horses: continue  # T-A と重複避け
            payout = win_payout if h == winner else 0
            bets.append(("T-B 3票一致馬の単勝", h, 100, payout))

        # --- 複勝戦略 ---
        # F-A: 4票一致馬 → 複勝
        for h in all4_horses:
            p = place_p.get(h, 0) if h in place_p else 0
            bets.append(("F-A 4票一致馬の複勝", h, 100, p))
        # F-B: 3票以上の馬 → 複勝
        for h in all3plus:
            if h in all4_horses: continue
            p = place_p.get(h, 0) if h in place_p else 0
            bets.append(("F-B 3票一致馬の複勝", h, 100, p))
        # F-C: 各エンジン top1 → 複勝 (重複馬は1回のみ)
        for h in votes_top1.keys():
            p = place_p.get(h, 0) if h in place_p else 0
            cnt = votes_top1[h]
            # 各エンジンが推しているので票数分買う
            bets.append(("F-C 各エンジンtop1の複勝", h, 100*cnt, p*cnt))

        # --- ワイド戦略 ---
        # W-A: 投票数 top2 馬の組合せ (2点 BOX = 1組)
        if len(ranked_by_votes) >= 2:
            h1, h2 = ranked_by_votes[0][0], ranked_by_votes[1][0]
            pair = frozenset({h1, h2})
            payout = wide_p.get(pair, 0)
            bets.append(("W-A 投票TOP2のワイド1点", (h1, h2), 100, payout))
        # W-B: 投票数 top3 馬の組合せ (3組 BOX)
        if len(ranked_by_votes) >= 3:
            top3_h = [r[0] for r in ranked_by_votes[:3]]
            for h1, h2 in combinations(top3_h, 2):
                pair = frozenset({h1, h2})
                payout = wide_p.get(pair, 0)
                bets.append(("W-B 投票TOP3のワイドBOX3点", (h1,h2), 100, payout))
        # W-C: 4票馬 軸 + 3票馬流し
        for axis in all4_horses:
            others = [h for h, c in votes_top3.items() if c == 3 and h != axis]
            for h2 in others:
                pair = frozenset({axis, h2})
                payout = wide_p.get(pair, 0)
                bets.append(("W-C 4票軸×3票流しワイド", (axis,h2), 100, payout))

        # --- 馬連戦略 ---
        if umaren:
            umaren_pair, umaren_payout = umaren
            # U-A: 投票TOP2 馬連1点
            if len(ranked_by_votes) >= 2:
                h1, h2 = ranked_by_votes[0][0], ranked_by_votes[1][0]
                pair = frozenset({h1,h2})
                p = umaren_payout if pair == umaren_pair else 0
                bets.append(("U-A 投票TOP2の馬連1点", (h1,h2), 100, p))
            # U-B: 投票TOP3 馬連BOX 3点
            if len(ranked_by_votes) >= 3:
                top3_h = [r[0] for r in ranked_by_votes[:3]]
                for h1, h2 in combinations(top3_h, 2):
                    pair = frozenset({h1,h2})
                    p = umaren_payout if pair == umaren_pair else 0
                    bets.append(("U-B 投票TOP3の馬連BOX3点", (h1,h2), 100, p))

        # --- 3連複戦略 ---
        if sanren:
            spk_trio, spk_payout = sanren
            # S-A: 投票TOP3 三連複1点 (3頭BOX = 1組)
            if len(ranked_by_votes) >= 3:
                t3 = frozenset({ranked_by_votes[i][0] for i in range(3)})
                p = spk_payout if t3 == spk_trio else 0
                bets.append(("S-A 投票TOP3の三連複1点", tuple(t3), 100, p))
            # S-B: 投票TOP4 三連複BOX 4点
            if len(ranked_by_votes) >= 4:
                t4 = [ranked_by_votes[i][0] for i in range(4)]
                for combo in combinations(t4, 3):
                    fs = frozenset(combo)
                    p = spk_payout if fs == spk_trio else 0
                    bets.append(("S-B 投票TOP4の三連複BOX4点", tuple(combo), 100, p))
            # S-C: 投票TOP5 三連複BOX 10点
            if len(ranked_by_votes) >= 5:
                t5 = [ranked_by_votes[i][0] for i in range(5)]
                for combo in combinations(t5, 3):
                    fs = frozenset(combo)
                    p = spk_payout if fs == spk_trio else 0
                    bets.append(("S-C 投票TOP5の三連複BOX10点", tuple(combo), 100, p))
            # S-D: 4票馬軸 + 投票TOP3-5から流し (3頭BOX 軸固定 = 軸+他2頭)
            for axis in all4_horses:
                others = [r[0] for r in ranked_by_votes if r[0] != axis][:4]
                for combo in combinations(others, 2):
                    fs = frozenset({axis, *combo})
                    p = spk_payout if fs == spk_trio else 0
                    bets.append(("S-D 4票軸三連複流し(軸+TOP4から2頭)", (axis,*combo), 100, p))

        # ====== 集計 ======
        # filter keys
        filters = [
            ("ALL", "all"),
            ("RACE_TYPE", rt),
            ("VENUE", f"{rt}/{venue}"),
            ("WEEKDAY", f"{rt}/{wd}"),
        ]
        # consensus horse popularity bucket — for strategies that have a single primary horse
        for name, pick, cost, payout in bets:
            for fkey, fval in filters:
                k = f"{fkey}={fval}"
                s = results[name][k]
                s["races"] += 1  # 厳密にはレース単位ではない (組合せ毎) が、ここは賭け数
                s["invested"] += cost
                s["payout"] += payout
                if payout > 0: s["hits"] += 1

    return results


# -------------- レポート生成 --------------
def render_report(results: dict, since: str, until: str, output_path: str):
    lines = [
        f"# マルチ馬券種 コンセンサスバックテスト 結果\n",
        f"**対象期間**: {since} ~ {until} (1年)\n",
        f"**作成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"**手法**: 4エンジンの top3 出力を「投票」と見なし、投票数 (1-4) に基づく購入戦略を全レースでバックテスト\n",
        "\n## 戦略一覧\n",
        "### 単勝\n",
        "- T-A: 4エンジン全部のtop3に入っている馬の単勝\n",
        "- T-B: 3エンジン以上のtop3に入っている馬の単勝\n",
        "\n### 複勝\n",
        "- F-A: 4票一致馬の複勝\n",
        "- F-B: 3票一致馬の複勝\n",
        "- F-C: 各エンジンtop1の複勝 (top1合議度は重み付け)\n",
        "\n### ワイド\n",
        "- W-A: 投票TOP2のワイド1点\n",
        "- W-B: 投票TOP3のワイドBOX 3点\n",
        "- W-C: 4票一致馬軸 × 3票一致馬流し\n",
        "\n### 馬連\n",
        "- U-A: 投票TOP2の馬連1点\n",
        "- U-B: 投票TOP3の馬連BOX 3点\n",
        "\n### 三連複\n",
        "- S-A: 投票TOP3の三連複1点\n",
        "- S-B: 投票TOP4の三連複BOX 4点\n",
        "- S-C: 投票TOP5の三連複BOX 10点\n",
        "- S-D: 4票一致馬軸 + 投票TOP4から2頭流し\n",
        "\n---\n",
    ]

    # 各戦略毎にメインサマリ
    for strat in sorted(results.keys()):
        lines.append(f"\n## {strat}\n")
        segs = results[strat]
        # ALL first, then race_type, then venue/weekday top recovery
        all_data = segs.get("ALL=all")
        if all_data:
            n = all_data["races"]
            inv = all_data["invested"]
            pay = all_data["payout"]
            hits = all_data["hits"]
            recov = pay/inv*100 if inv else 0
            hit_rate = hits/n*100 if n else 0
            lines.append(f"### 全体\n")
            lines.append(f"  - 賭け数: {n:,} / 投資: ¥{inv:,} / 払戻: ¥{pay:,} / 利益: ¥{pay-inv:+,}\n")
            lines.append(f"  - 的中: {hits:,} ({hit_rate:.1f}%) / **回収率: {recov:.1f}%**\n")

        # race_type 別
        lines.append(f"\n### race_type 別\n")
        lines.append("| 区分 | 賭け数 | 投資 | 払戻 | 利益 | 的中率 | 回収率 |\n")
        lines.append("|---|---:|---:|---:|---:|---:|---:|\n")
        for rt in ["jra", "nar"]:
            d = segs.get(f"RACE_TYPE={rt}")
            if not d: continue
            n = d["races"]; inv = d["invested"]; pay = d["payout"]
            hits = d["hits"]
            recov = pay/inv*100 if inv else 0
            lines.append(f"| {rt.upper()} | {n:,} | ¥{inv:,} | ¥{pay:,} | ¥{pay-inv:+,} | {hits/n*100:.1f}% | **{recov:.1f}%** |\n")

        # 会場別 TOP10 (回収率高い順、最低50件)
        venue_segs = [(k.replace("VENUE=",""), v) for k, v in segs.items() if k.startswith("VENUE=")]
        venue_segs = [(k, v) for k, v in venue_segs if v["races"] >= 50]
        venue_segs.sort(key=lambda x: x[1]["payout"]/max(x[1]["invested"],1), reverse=True)
        if venue_segs:
            lines.append(f"\n### 会場別 TOP10 (50件以上のみ)\n")
            lines.append("| 会場 | 賭け数 | 利益 | 回収率 |\n")
            lines.append("|---|---:|---:|---:|\n")
            for vk, d in venue_segs[:10]:
                recov = d["payout"]/d["invested"]*100 if d["invested"] else 0
                profit = d["payout"]-d["invested"]
                lines.append(f"| {vk} | {d['races']:,} | ¥{profit:+,} | **{recov:.1f}%** |\n")

        # 曜日別
        wd_segs = [(k.replace("WEEKDAY=",""), v) for k, v in segs.items() if k.startswith("WEEKDAY=")]
        wd_segs = [(k, v) for k, v in wd_segs if v["races"] >= 50]
        if wd_segs:
            wd_segs.sort(key=lambda x: x[0])
            lines.append(f"\n### 曜日別\n")
            lines.append("| 曜日 | 賭け数 | 利益 | 回収率 |\n")
            lines.append("|---|---:|---:|---:|\n")
            for wk, d in wd_segs:
                recov = d["payout"]/d["invested"]*100 if d["invested"] else 0
                profit = d["payout"]-d["invested"]
                lines.append(f"| {wk} | {d['races']:,} | ¥{profit:+,} | **{recov:.1f}%** |\n")

    # 黒字パターンTOP抽出 (全戦略横断)
    lines.append("\n---\n\n## 🌟 黒字パターンTOP30 (回収率100%超 / 50件以上)\n\n")
    lines.append("| 戦略 | セグメント | 賭け数 | 利益 | 回収率 |\n")
    lines.append("|---|---|---:|---:|---:|\n")
    candidates = []
    for strat, segs in results.items():
        for seg, d in segs.items():
            if d["races"] < 50: continue
            if d["invested"] == 0: continue
            recov = d["payout"]/d["invested"]*100
            if recov < 100: continue
            candidates.append((strat, seg, d["races"], d["payout"]-d["invested"], recov))
    candidates.sort(key=lambda x: x[4], reverse=True)
    for s, seg, n, profit, recov in candidates[:30]:
        lines.append(f"| {s} | {seg} | {n:,} | ¥{profit:+,} | **{recov:.1f}%** |\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    logger.info(f"report → {output_path}")


# -------------- main --------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(DOCS_DIR, f"multi_ticket_consensus_backtest_{datetime.now().strftime('%Y%m%d')}.md"))
    p.add_argument("--since", default="2025-04-27")
    p.add_argument("--until", default="2026-04-26")
    p.add_argument("--allow-leak", action="store_true",
                   help="post-race created 行も含む (leakageあり、デバッグ用)")
    args = p.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    by_race, race_meta = load_engine_data(sb, args.since, args.until, clean_only=not args.allow_leak)

    schedule = load_schedule_master()
    if not schedule:
        logger.warning("schedule master not found; NAR venue mapping may be inaccurate")

    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    since_yyyymmdd = args.since.replace("-", "")
    nar_races = load_pckeiba_data(conn, "nvd_se", "nvd_hr", "nar", since_yyyymmdd, schedule)
    jra_races = load_pckeiba_data(conn, "jvd_se", "jvd_hr", "jra", since_yyyymmdd, schedule)
    conn.close()
    races_pck = {**nar_races, **jra_races}
    logger.info(f"total pck races: {len(races_pck)} (nar {len(nar_races)} + jra {len(jra_races)})")

    matched = compute_vote_data(by_race, race_meta, races_pck)
    logger.info(f"running strategies on {matched} matched races")

    results = run_strategies(races_pck)
    render_report(results, args.since, args.until, args.out)
    print(f"\n=== Done. Report: {args.out} ===")


if __name__ == "__main__":
    sys.exit(main() or 0)
