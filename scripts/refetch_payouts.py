#!/usr/bin/env python3
"""特定日の race_results を再 fetch して payouts を埋め込む.

Usage:
  python scripts/refetch_payouts.py --date 2026-05-02 [--venue 東京]

既存の race_results は upsert で更新される（result_json.payouts に複勝・三連複等が入る）。
fetch_results.py が pending のみ対象なのに対し、こちらは date 指定で全件強制再 fetch。
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env.local")

from db.result_manager import save_race_result
from db.supabase_client import get_client
from scrapers.race_result import fetch_race_result
from scrapers.nar import NAR_VENUES
from scripts.fetch_results import _resolve_netkeiba_id, _is_custom_race_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run(date_str: str, venue_filter: str = "") -> None:
    sb = get_client()
    q = sb.table("race_results").select(
        "race_id,race_name,venue,race_type,race_date"
    ).eq("race_date", date_str)
    if venue_filter:
        q = q.eq("venue", venue_filter)
    rows = q.execute().data or []

    logger.info(f"target rows: {len(rows)} (date={date_str} venue={venue_filter or 'all'})")

    fetched = 0
    skipped = 0
    errors = 0

    for row in rows:
        race_id = row["race_id"]
        venue = row.get("venue", "")
        race_type = row.get("race_type") or ("nar" if any(v in venue for v in NAR_VENUES) else "jra")

        # custom race_id → Netkeiba race_id 解決
        if _is_custom_race_id(race_id):
            nk_id = _resolve_netkeiba_id(race_id, race_type)
            if not nk_id:
                logger.warning(f"skip {race_id}: cannot resolve netkeiba_id")
                skipped += 1
                continue
        else:
            nk_id = race_id

        try:
            result = fetch_race_result(nk_id, race_type)
        except Exception as e:
            logger.warning(f"fetch failed {race_id} ({nk_id}): {e}")
            errors += 1
            continue

        if not result:
            logger.info(f"no result {race_id}: page not found or unfinished")
            skipped += 1
            continue

        try:
            save_race_result(
                race_id=race_id,
                winner_number=result["winner_number"],
                winner_name=result["winner_name"],
                win_payout=result["win_payout"],
                result_json=result["result_json"],
                race_name=row.get("race_name", ""),
                venue=venue,
                race_date=date_str,
                race_type=race_type,
            )
            fetched += 1
            payouts = (result["result_json"] or {}).get("payouts") or {}
            kinds = list(payouts.keys())
            logger.info(f"ok {race_id}: payouts={kinds}")
        except Exception as e:
            logger.warning(f"save failed {race_id}: {e}")
            errors += 1

    logger.info(f"=== done: fetched={fetched} skipped={skipped} errors={errors} ===")


def main():
    p = argparse.ArgumentParser(description="Re-fetch race_results to populate payouts")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--venue", default="", help="Filter by venue name (optional)")
    args = p.parse_args()
    run(args.date, args.venue)


if __name__ == "__main__":
    main()
