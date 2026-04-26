#!/usr/bin/env python3
"""Fetch all-ticket payouts from local PCKEIBA PostgreSQL and merge into
Supabase race_results.result_json.payouts.

JRA: jvd_hr (138K rows). NAR: nvd_hr (324K rows) with correct_venue() correction.

Run on jin's PC where PCKEIBA is reachable at 127.0.0.1:5432.

Usage:
    python scripts/fetch_pckeiba_payouts_to_results.py [--since YYYY-MM-DD]
        default since: 2026-03-01
"""
import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")

# Supabase env may not be in local .env.local — read from VPS via env override
# Temporary workaround: read SUPABASE_URL/KEY from environment or a fallback file
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    # Try to fetch from VPS env via SSH (one-time read)
    import subprocess
    try:
        out = subprocess.check_output(
            ["ssh", "root@220.158.24.157", "grep -E '^(SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=' /opt/dlogic/linebot/.env.local"],
            text=True, timeout=10,
        )
        for line in out.strip().split("\n"):
            k, v = line.split("=", 1)
            os.environ[k] = v
            if k == "SUPABASE_URL": SUPABASE_URL = v
            if k == "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY = v
    except Exception as e:
        print(f"WARN: could not auto-fetch Supabase creds from VPS: {e}", file=sys.stderr)

from supabase import create_client

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PCKEIBA_CONFIG = {
    "host": "127.0.0.1", "port": 5432, "database": "pckeiba",
    "user": "postgres", "password": "postgres",
}

# JRA venue code (jvd_hr.keibajo_code) → name
JRA_VENUES = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟',
    '05': '東京', '06': '中山', '07': '中京', '08': '京都',
    '09': '阪神', '10': '小倉',
}

# NAR venue code (nvd_hr.keibajo_code, after correction) → name
NAR_VENUES = {
    '83': '帯広', '30': '門別', '35': '盛岡', '36': '水沢',
    '45': '浦和', '43': '船橋', '42': '大井', '44': '川崎',
    '46': '金沢', '47': '笠松', '48': '名古屋',
    '50': '園田', '51': '姫路', '54': '高知', '55': '佐賀',
}

NANKAN_CODES = {'42', '43', '44', '45'}

REGION_GROUPS = [
    {'35', '36'},
    {'46', '47', '48'},
    {'50', '51'},
    {'54', '55'},
    {'30', '83'},
]

# Schedule master path (data dir of either repo)
SCHEDULE_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'data', 'nar_schedule_master_2020_2026.json'),
    r"E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json",
]


def load_schedule_master():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                logger.info(f"loaded schedule master: {p}")
                return json.load(f)
    logger.warning("schedule master not found; NAR correction will be limited")
    return None


def correct_venue(kaisai_nen, kaisai_tsukihi, original_code, schedule_master):
    """Return corrected NAR venue code (without race_name dependency)."""
    if not schedule_master or 'schedule_data' not in schedule_master:
        return original_code
    race_date = f"{kaisai_nen}{kaisai_tsukihi}"
    day_venues = schedule_master['schedule_data'].get(race_date, [])
    if not day_venues:
        return original_code
    if len(day_venues) == 1:
        return day_venues[0]
    if original_code in day_venues:
        return original_code
    if original_code in NANKAN_CODES:
        nankan_on_day = [c for c in day_venues if c in NANKAN_CODES]
        if len(nankan_on_day) == 1:
            return nankan_on_day[0]
    for group in REGION_GROUPS:
        if original_code in group:
            cands = [c for c in day_venues if c in group]
            if len(cands) == 1:
                return cands[0]
            break
    return original_code


# Column index helpers for jvd_hr / nvd_hr SELECT
HR_COLS = """
kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
haraimodoshi_tansho_1a, haraimodoshi_tansho_1b,
haraimodoshi_fukusho_1a, haraimodoshi_fukusho_1b,
haraimodoshi_fukusho_2a, haraimodoshi_fukusho_2b,
haraimodoshi_fukusho_3a, haraimodoshi_fukusho_3b,
haraimodoshi_fukusho_4a, haraimodoshi_fukusho_4b,
haraimodoshi_fukusho_5a, haraimodoshi_fukusho_5b,
haraimodoshi_umaren_1a, haraimodoshi_umaren_1b,
haraimodoshi_umaren_2a, haraimodoshi_umaren_2b,
haraimodoshi_umaren_3a, haraimodoshi_umaren_3b,
haraimodoshi_wide_1a, haraimodoshi_wide_1b,
haraimodoshi_wide_2a, haraimodoshi_wide_2b,
haraimodoshi_wide_3a, haraimodoshi_wide_3b,
haraimodoshi_wide_4a, haraimodoshi_wide_4b,
haraimodoshi_wide_5a, haraimodoshi_wide_5b,
haraimodoshi_wide_6a, haraimodoshi_wide_6b,
haraimodoshi_wide_7a, haraimodoshi_wide_7b,
haraimodoshi_umatan_1a, haraimodoshi_umatan_1b,
haraimodoshi_umatan_2a, haraimodoshi_umatan_2b,
haraimodoshi_umatan_3a, haraimodoshi_umatan_3b,
haraimodoshi_sanrenpuku_1a, haraimodoshi_sanrenpuku_1b,
haraimodoshi_sanrenpuku_2a, haraimodoshi_sanrenpuku_2b,
haraimodoshi_sanrenpuku_3a, haraimodoshi_sanrenpuku_3b,
haraimodoshi_sanrentan_1a, haraimodoshi_sanrentan_1b,
haraimodoshi_sanrentan_2a, haraimodoshi_sanrentan_2b,
haraimodoshi_sanrentan_3a, haraimodoshi_sanrentan_3b
"""


def parse_payout_row(row) -> dict:
    """Convert raw payout columns into structured payouts dict."""
    def _str(v):
        if v is None: return None
        s = str(v).strip()
        return s or None

    def _int(v):
        s = _str(v)
        try: return int(s) if s else None
        except (ValueError, TypeError): return None

    def _combo(s):
        """馬連等の馬番文字列パース: 例 '0712' → [7, 12], '030712' → [3, 7, 12]"""
        s = _str(s)
        if not s: return None
        try:
            n = len(s) // 2
            return [int(s[i*2:(i+1)*2]) for i in range(n)]
        except Exception:
            return None

    def _pair(a, b):
        n_a = _combo(a)
        n_b = _int(b)
        if n_a is None or n_b is None or n_b == 0:
            return None
        return {"combo": n_a, "payout": n_b}

    # row indices map to HR_COLS order (4 race-key fields then payouts)
    # Skip race-key fields (idx 0-3)
    p = row[4:]
    payouts = {}

    # 単勝
    win = _pair(p[0], p[1])
    if win:
        payouts["win"] = win

    # 複勝 (5枠)
    fukusho = []
    for i in range(5):
        fk = _pair(p[2 + i*2], p[3 + i*2])
        if fk:
            fukusho.append(fk)
    if fukusho:
        payouts["place"] = fukusho

    # 馬連 (3枠)
    umaren = []
    for i in range(3):
        u = _pair(p[12 + i*2], p[13 + i*2])
        if u:
            umaren.append(u)
    if umaren:
        payouts["umaren"] = umaren

    # ワイド (7枠 — レアだが取れるだけ)
    wide = []
    for i in range(7):
        w = _pair(p[18 + i*2], p[19 + i*2])
        if w:
            wide.append(w)
    if wide:
        payouts["wide"] = wide

    # 馬単 (3枠)
    umatan = []
    for i in range(3):
        ut = _pair(p[32 + i*2], p[33 + i*2])
        if ut:
            umatan.append(ut)
    if umatan:
        payouts["umatan"] = umatan

    # 3連複 (3枠)
    sanrenpuku = []
    for i in range(3):
        sf = _pair(p[38 + i*2], p[39 + i*2])
        if sf:
            sanrenpuku.append(sf)
    if sanrenpuku:
        payouts["sanrenpuku"] = sanrenpuku

    # 3連単 (3枠)
    sanrentan = []
    for i in range(3):
        st = _pair(p[44 + i*2], p[45 + i*2])
        if st:
            sanrentan.append(st)
    if sanrentan:
        payouts["sanrentan"] = sanrentan

    return payouts


def fetch_pckeiba_payouts(since_date: str) -> dict:
    """Fetch JRA + NAR payouts from PCKEIBA, return {(date_iso, venue_name, race_num): payouts}."""
    schedule_master = load_schedule_master()
    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    cur = conn.cursor()

    # since_date: 'YYYY-MM-DD' → 'YYYYMMDD'
    since_compact = since_date.replace("-", "")
    since_year = since_compact[:4]
    since_md = since_compact[4:]

    # JRA query
    logger.info(f"fetching JRA jvd_hr since {since_compact}...")
    cur.execute(f"""
        SELECT {HR_COLS}
        FROM jvd_hr
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
        ORDER BY kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango
    """, (since_compact,))
    jra_rows = cur.fetchall()
    logger.info(f"  {len(jra_rows)} JRA rows")

    logger.info(f"fetching NAR nvd_hr since {since_compact}...")
    cur.execute(f"""
        SELECT {HR_COLS}
        FROM nvd_hr
        WHERE (kaisai_nen || kaisai_tsukihi) >= %s
        ORDER BY kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango
    """, (since_compact,))
    nar_rows = cur.fetchall()
    logger.info(f"  {len(nar_rows)} NAR rows")

    cur.close()
    conn.close()

    # Index by (date_iso, venue_name, race_number)
    out = {}

    for row in jra_rows:
        nen, md, code, bango = row[0], row[1], row[2], row[3]
        venue = JRA_VENUES.get(code)
        if not venue:
            continue
        date_iso = f"{nen}-{md[:2]}-{md[2:]}"
        try: race_num = int(bango)
        except (ValueError, TypeError): continue
        payouts = parse_payout_row(row)
        if payouts:
            out[(date_iso, venue, race_num)] = payouts

    for row in nar_rows:
        nen, md, code, bango = row[0], row[1], row[2], row[3]
        # Apply venue correction
        corrected = correct_venue(nen, md, code, schedule_master)
        venue = NAR_VENUES.get(corrected)
        if not venue:
            continue
        date_iso = f"{nen}-{md[:2]}-{md[2:]}"
        try: race_num = int(bango)
        except (ValueError, TypeError): continue
        payouts = parse_payout_row(row)
        if payouts:
            out[(date_iso, venue, race_num)] = payouts

    logger.info(f"indexed payouts: {len(out)} race-keys")
    return out


def fetch_supabase_results(sb, since_date: str) -> list:
    """Fetch all finished race_results from Supabase since the given date."""
    rows = []
    offset = 0
    while True:
        res = sb.table("race_results") \
            .select("race_id,race_date,venue,result_json,win_payout,status") \
            .gte("race_date", since_date) \
            .eq("status", "finished") \
            .range(offset, offset + 999).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < 1000: break
        offset += 1000
    return rows


def race_id_to_race_number(race_id: str):
    """Extract race_number from race_id like '20260423-中山-7' or '202506010211' (12-digit)."""
    if "-" in race_id:
        parts = race_id.split("-")
        if len(parts) == 3:
            try: return int(parts[2])
            except ValueError: return None
    elif race_id.isdigit() and len(race_id) >= 11:
        # 12-digit JRA: positions 10-11 = race number
        try: return int(race_id[10:12])
        except ValueError: return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-03-01")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not available")
        return 1

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    payouts_index = fetch_pckeiba_payouts(args.since)
    results = fetch_supabase_results(sb, args.since)
    logger.info(f"Supabase race_results: {len(results)} rows")

    matched = 0
    missing = 0
    win_mismatch = 0
    updated = 0

    for r in results:
        race_id = r["race_id"]
        race_date = r["race_date"]
        venue = r["venue"]
        race_num = race_id_to_race_number(race_id)
        if race_num is None:
            missing += 1
            continue
        key = (race_date, venue, race_num)
        payouts = payouts_index.get(key)
        if not payouts:
            missing += 1
            continue
        matched += 1

        # Sanity: existing win_payout vs PCKEIBA win
        existing_win = r.get("win_payout") or 0
        pck_win = (payouts.get("win") or {}).get("payout") or 0
        if existing_win and pck_win and existing_win != pck_win:
            win_mismatch += 1
            logger.debug(f"win mismatch {race_id}: existing={existing_win} pckeiba={pck_win}")

        # Merge payouts into result_json
        rj = r.get("result_json") or {}
        if isinstance(rj, str):
            try: rj = json.loads(rj)
            except Exception: rj = {}
        rj["payouts"] = payouts

        if not args.dry_run:
            try:
                sb.table("race_results").update({"result_json": rj}).eq("race_id", race_id).execute()
                updated += 1
            except Exception as e:
                logger.error(f"update failed {race_id}: {e}")

    logger.info("=" * 50)
    logger.info(f"matched={matched} missing={missing} win_mismatch={win_mismatch} updated={updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
