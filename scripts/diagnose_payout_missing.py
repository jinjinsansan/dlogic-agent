#!/usr/bin/env python3
"""Diagnose why some race_results don't match PCKEIBA payouts.

For each missing race, check:
1. race_id parse → race_number extraction
2. PCKEIBA same-date races: do they exist with different venue?
3. venue name mismatch candidates
4. PCKEIBA total absence (race not in either jvd_hr or nvd_hr)
"""
import os
import sys
from collections import defaultdict, Counter

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_pckeiba_payouts_to_results import (
    PCKEIBA_CONFIG, JRA_VENUES, NAR_VENUES, HR_COLS,
    load_schedule_master, correct_venue, race_id_to_race_number,
    fetch_supabase_results, parse_payout_row,
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
)
from supabase import create_client


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    schedule_master = load_schedule_master()

    # Re-fetch PCKEIBA payouts and index by date
    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    cur = conn.cursor()

    print("Fetching JRA + NAR rows since 20260311...")
    cur.execute(f"""
        SELECT 'jra' as src, {HR_COLS} FROM jvd_hr
        WHERE (kaisai_nen || kaisai_tsukihi) >= '20260311'
        UNION ALL
        SELECT 'nar' as src, {HR_COLS} FROM nvd_hr
        WHERE (kaisai_nen || kaisai_tsukihi) >= '20260311'
    """)
    all_rows = cur.fetchall()
    print(f"  total: {len(all_rows)}")
    cur.close()
    conn.close()

    # By (date_iso, race_num) → list of (src, venue_code, venue_name_raw, venue_name_corrected)
    by_dr = defaultdict(list)
    for row in all_rows:
        src, nen, md, code, bango = row[0], row[1], row[2], row[3], row[4]
        if src == 'jra':
            venue = JRA_VENUES.get(code)
            corrected_code = code
        else:
            corrected_code = correct_venue(nen, md, code, schedule_master)
            venue = NAR_VENUES.get(corrected_code)
        if not venue:
            continue
        date_iso = f"{nen}-{md[:2]}-{md[2:]}"
        try: rn = int(bango)
        except: continue
        by_dr[(date_iso, rn)].append((src, code, corrected_code, venue))

    # Get matched index from main script logic
    matched_keys = set()
    for (date_iso, rn), entries in by_dr.items():
        for _, _, _, venue in entries:
            matched_keys.add((date_iso, venue, rn))

    # Get all Supabase race_results and find missing
    results = fetch_supabase_results(sb, "2026-03-11")
    print(f"Supabase rows: {len(results)}\n")

    missing = []
    for r in results:
        rid = r["race_id"]
        rn = race_id_to_race_number(rid)
        if rn is None:
            missing.append({"reason": "race_num_parse", "race_id": rid})
            continue
        key = (r["race_date"], r["venue"], rn)
        if key not in matched_keys:
            missing.append({
                "reason": "no_match",
                "race_id": rid,
                "race_date": r["race_date"],
                "venue": r["venue"],
                "race_num": rn,
            })

    print(f"missing total: {len(missing)}\n")

    # Categorize
    reason_count = Counter(m["reason"] for m in missing)
    print("by reason:")
    for k, v in reason_count.most_common():
        print(f"  {k}: {v}")

    # For "no_match", investigate further
    no_match = [m for m in missing if m["reason"] == "no_match"]
    if no_match:
        print(f"\n=== no_match 詳細 (sample 20) ===")
        for m in no_match[:20]:
            entries_same_dr = by_dr.get((m["race_date"], m["race_num"]), [])
            if entries_same_dr:
                # Same date+race_num exists in PCKEIBA but venue mismatch
                pck_venues = sorted(set(e[3] for e in entries_same_dr))
                print(f"  {m['race_id']}: Supabase '{m['venue']}' / PCKEIBA同日同R venue={pck_venues}")
            else:
                # No race at all in PCKEIBA for that date+race_num
                print(f"  {m['race_id']}: PCKEIBA に同日同レース番号なし")

    # Venue mismatch summary
    print(f"\n=== venue mismatch サマリ ===")
    sb_venues_missing = Counter()
    for m in no_match:
        entries_same_dr = by_dr.get((m["race_date"], m["race_num"]), [])
        if entries_same_dr:
            sb_venues_missing[m["venue"]] += 1
    for v, cnt in sb_venues_missing.most_common(15):
        print(f"  Supabase venue '{v}' (PCKEIBA同日同Rあるが unmatched): {cnt}件")

    # Total no race at all
    no_race = sum(1 for m in no_match
                  if not by_dr.get((m["race_date"], m["race_num"]), []))
    print(f"\n=== PCKEIBA未登録 (race_num自体が無い): {no_race} 件 ===")


if __name__ == "__main__":
    main()
