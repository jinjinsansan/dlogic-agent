#!/usr/bin/env python3
"""5基合議バックテスト Step 1: ローカル PCKEIBA からレースデータをエクスポート.

Step 2 (VPS で predictions API 呼出) に渡すための JSON を生成する。

ローカルでのみ実行 (PCKEIBA は 127.0.0.1:5432)。
出力: data/5eng_races_{race_type}_{since}_{until}.json

Usage:
    python scripts/audit_5eng_step1_export.py --race-type nar --since 20260301 --until 20260430
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime

import psycopg2

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")

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
JRA_VENUES = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟',
    '05': '東京', '06': '中山', '07': '中京', '08': '京都',
    '09': '阪神', '10': '小倉',
}
NANKAN_CODES = {'42', '43', '44', '45'}
REGION_GROUPS = [{'35', '36'}, {'46', '47', '48'}, {'50', '51'}, {'54', '55'}, {'30', '83'}]

SCHEDULE_PATHS = [
    os.path.join(PROJECT_DIR, 'data', 'nar_schedule_master_2020_2026.json'),
    r'E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json',
]


# ---------------------------------------------------------------------------
# helpers (既存 audit_5engine_backtest.py から移植)
# ---------------------------------------------------------------------------
def load_schedule():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    return None


def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule:
        return code
    days = schedule['schedule_data'].get(nen + md, [])
    if not days:
        return code
    if len(days) == 1:
        return days[0]
    if code in days:
        return code
    if code in NANKAN_CODES:
        n = [c for c in days if c in NANKAN_CODES]
        if len(n) == 1:
            return n[0]
    for g in REGION_GROUPS:
        if code in g:
            cands = [c for c in days if c in g]
            if len(cands) == 1:
                return cands[0]
            break
    return code


def safe_int(v):
    if v is None:
        return 0
    s = str(v).strip()
    try:
        return int(s) if s else 0
    except (ValueError, TypeError):
        return 0


def parse_horses(s):
    s = (s or '').strip()
    if not s or s == '00':
        return ()
    if len(s) % 2 != 0:
        return ()
    out = []
    for i in range(0, len(s), 2):
        try:
            out.append(int(s[i:i + 2]))
        except ValueError:
            return ()
    return tuple(out)


def load_races_from_pckeiba(race_type, since, until, schedule):
    """Load race entries + results from PCKEIBA."""
    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    table_se = 'nvd_se' if race_type == 'nar' else 'jvd_se'
    table_hr = 'nvd_hr' if race_type == 'nar' else 'jvd_hr'
    venue_map = NAR_VENUES if race_type == 'nar' else JRA_VENUES

    # === 払戻 ===
    cur = conn.cursor()
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b
        FROM {table_hr}
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
    """, (since, until))

    results = {}
    for nen, md, code, bango, ta, tb in cur.fetchall():
        if race_type == 'nar':
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = venue_map.get(cc)
        else:
            venue = venue_map.get(code)
        if not venue:
            continue
        try:
            rno = int(bango)
        except (ValueError, TypeError):
            continue
        wh = parse_horses(ta)
        wp = safe_int(tb)
        if not wh or wp == 0:
            continue
        date_str = f"{nen}-{md[:2]}-{md[2:4]}"
        key = (date_str, venue, rno)
        results[key] = {'winner': wh[0], 'payout': wp}
    cur.close()

    # === 出走 ===
    test_cur = conn.cursor()
    test_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table_se,))
    available_cols = {r[0] for r in test_cur.fetchall()}
    test_cur.close()

    horse_col = next((c for c in ['bamei', 'umamei', 'horse_name'] if c in available_cols), None)
    jockey_col = next((c for c in ['kishumei_ryakusho', 'kishu_mei', 'kishumei'] if c in available_cols), None)
    post_col = next((c for c in ['wakuban', 'waku_bango'] if c in available_cols), None)
    dist_col = next((c for c in ['kyori', 'distance'] if c in available_cols), None)
    ninki_col = 'tansho_ninkijun' if 'tansho_ninkijun' in available_cols else None

    select_cols = [
        'kaisai_nen', 'kaisai_tsukihi', 'keibajo_code', 'race_bango',
        'umaban', 'kakutei_chakujun',
    ]
    for c in (horse_col, jockey_col, post_col, dist_col, ninki_col):
        if c:
            select_cols.append(c)

    cur = conn.cursor("se_stream")
    cur.itersize = 50000
    cur.execute(f"""
        SELECT {', '.join(select_cols)}
        FROM {table_se}
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
          AND (kaisai_nen || kaisai_tsukihi) <= %s
        ORDER BY kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, umaban
    """, (since, until))

    races = defaultdict(lambda: {'entries': [], 'meta': {}})
    for row in cur:
        idx = 0
        nen = row[idx]; idx += 1
        md = row[idx]; idx += 1
        code = row[idx]; idx += 1
        bango = row[idx]; idx += 1
        umaban = row[idx]; idx += 1
        chaku = row[idx]; idx += 1

        horse_name = row[idx] if horse_col else None
        if horse_col: idx += 1
        jockey = row[idx] if jockey_col else None
        if jockey_col: idx += 1
        post = row[idx] if post_col else None
        if post_col: idx += 1
        dist = row[idx] if dist_col else None
        if dist_col: idx += 1
        ninki = row[idx] if ninki_col else None
        if ninki_col: idx += 1

        if race_type == 'nar':
            cc = correct_nar_venue(nen, md, code, schedule)
            venue = venue_map.get(cc)
        else:
            venue = venue_map.get(code)
        if not venue:
            continue
        try:
            rno = int(bango)
            hno = int(str(umaban).strip())
        except (ValueError, TypeError):
            continue

        date_str = f"{nen}-{md[:2]}-{md[2:4]}"
        key = (date_str, venue, rno)

        hn = (str(horse_name).strip() if horse_name else f"#{hno}")
        jk = (str(jockey).strip() if jockey else "")
        pn = safe_int(post) or hno
        d = safe_int(dist)
        pop = safe_int(ninki)
        fin = safe_int(chaku)

        races[key]['entries'].append({
            'horse_no': hno, 'horse_name': hn, 'jockey': jk,
            'post_no': pn, 'finish': fin, 'pop': pop,
        })
        races[key]['meta'] = {
            'date': date_str, 'venue': venue, 'race_no': rno,
            'distance': d, 'race_type': race_type,
        }

    cur.close()
    conn.close()

    # Merge
    merged = []
    for key, race in races.items():
        res = results.get(key)
        if not res:
            continue
        if len(race['entries']) < 5:
            continue
        race['result'] = res
        merged.append(race)

    logger.info(f"Loaded {len(merged)} races with results ({race_type} {since}-{until})")
    return merged


# ---------------------------------------------------------------------------
# Step 1 main: convert race -> JSON record
# ---------------------------------------------------------------------------
def race_to_record(race):
    """Convert a race dict (from PCKEIBA) to a JSON-friendly record."""
    meta = race['meta']
    entries = sorted(race['entries'], key=lambda x: x['horse_no'])
    weekday_idx = datetime.strptime(meta['date'], '%Y-%m-%d').weekday()
    weekday = ['月', '火', '水', '木', '金', '土', '日'][weekday_idx]

    payload = {
        "race_id": f"{meta['date'].replace('-', '')}-{meta['venue']}-{meta['race_no']}",
        "horses": [e['horse_name'] for e in entries],
        "horse_numbers": [e['horse_no'] for e in entries],
        "venue": meta['venue'],
        "race_number": meta['race_no'],
        "jockeys": [e['jockey'] for e in entries],
        "posts": [e['post_no'] for e in entries],
        "distance": f"{meta['distance']}m" if meta['distance'] else "",
        "track_condition": "良",
    }

    pop_map = {str(e['horse_no']): e['pop'] for e in entries if e.get('pop')}

    return {
        "payload": payload,
        "result": race['result'],
        "pop_map": pop_map,
        "meta": {
            "date": meta['date'],
            "venue": meta['venue'],
            "race_no": meta['race_no'],
            "weekday": weekday,
            "race_type": meta['race_type'],
            "distance": meta['distance'],
        },
    }


def main():
    parser = argparse.ArgumentParser(description="5基合議バックテスト Step 1: PCKEIBA → JSON")
    parser.add_argument("--race-type", choices=["nar", "jra"], default="nar")
    parser.add_argument("--since", default="20260301", help="YYYYMMDD")
    parser.add_argument("--until", default="20260430", help="YYYYMMDD")
    parser.add_argument("--out", default=None, help="output JSON path")
    args = parser.parse_args()

    schedule = load_schedule()
    if not schedule:
        logger.warning("nar_schedule_master not found — NAR venue correction will be skipped")

    races = load_races_from_pckeiba(args.race_type, args.since, args.until, schedule)
    records = [race_to_record(r) for r in races]

    out_path = args.out or os.path.join(
        DATA_DIR, f"5eng_races_{args.race_type}_{args.since}_{args.until}.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)

    logger.info(f"Exported {len(records)} races → {out_path}")
    logger.info(f"File size: {os.path.getsize(out_path) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
