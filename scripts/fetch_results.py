"""Fetch race results for pending predictions and update user stats.

Run via cron or systemd timer after racing hours:
  python scripts/fetch_results.py [--date YYYY-MM-DD]

Flow:
1. Find races with user predictions but no results yet
2. Resolve custom race_id (YYYYMMDD-venue-num) to netkeiba race_id if needed
3. Scrape results from netkeiba
4. Save results to race_results table
5. Judge predictions (的中判定)
6. Update user_stats
"""

import argparse
import logging
import re
import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env.local")

from datetime import datetime, timezone, timedelta

from db.result_manager import (
    save_race_result,
    get_pending_races,
    judge_predictions,
    update_user_stats_for_race,
)
from scrapers.race_result import fetch_race_result
from scrapers.nar import NAR_VENUES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# Cache for netkeiba race_id lookups (date_str → {venue-num: netkeiba_id})
_netkeiba_id_cache: dict[str, dict[str, str]] = {}


def _is_custom_race_id(race_id: str) -> bool:
    """Check if race_id is in custom format: YYYYMMDD-venue-num."""
    return bool(re.match(r'^\d{8}-.+?-\d+$', race_id))


def _resolve_netkeiba_id(race_id: str, race_type: str) -> str | None:
    """Resolve custom race_id (YYYYMMDD-venue-num) to netkeiba race_id.

    Scrapes the race list for the date and matches by venue + race_number.
    Returns netkeiba race_id or None if not found.
    """
    m = re.match(r'^(\d{8})-(.+?)-(\d+)$', race_id)
    if not m:
        return None

    date_str = m.group(1)  # YYYYMMDD
    venue = m.group(2)
    race_number = int(m.group(3))

    cache_key = f"{date_str}-{race_type}"

    # Check cache
    if cache_key not in _netkeiba_id_cache:
        _netkeiba_id_cache[cache_key] = {}

        # Determine if NAR or JRA based on venue
        is_nar = any(v in venue for v in NAR_VENUES)

        if is_nar:
            from scrapers.nar import fetch_race_list
            races = fetch_race_list(date_str, venue_filter=venue)
        else:
            from scrapers.jra import fetch_race_list
            races = fetch_race_list(date_str)

        for r in races:
            key = f"{r.venue}-{r.race_number}"
            _netkeiba_id_cache[cache_key][key] = r.race_id

        time.sleep(1)  # Be polite to netkeiba

    lookup_key = f"{venue}-{race_number}"
    nk_id = _netkeiba_id_cache[cache_key].get(lookup_key)
    if nk_id:
        logger.info(f"Resolved {race_id} → {nk_id}")
    else:
        logger.warning(f"Could not resolve {race_id} to netkeiba ID (key={lookup_key})")

    return nk_id


def run(date_str: str = ""):
    """Fetch results for all pending races."""
    if not date_str:
        date_str = datetime.now(JST).strftime("%Y-%m-%d")

    logger.info(f"=== Fetching results for date: {date_str} ===")

    # 1. Find pending races
    pending = get_pending_races(date_str)

    # Also try without date filter if no results (race_date might be NULL)
    if not pending:
        logger.info(f"No pending races for date={date_str}, trying without date filter...")
        pending = get_pending_races("")
        if pending:
            logger.info(f"Found {len(pending)} pending races (all dates)")

    if not pending:
        logger.info("No pending races found.")
        return

    logger.info(f"Found {len(pending)} pending races")

    fetched = 0
    judged = 0
    errors = 0

    for race in pending:
        race_id = race["race_id"]
        race_type = race.get("race_type", "jra")
        venue = race.get("venue", "")

        # Auto-fix race_type based on venue
        if venue and any(v in venue for v in NAR_VENUES):
            race_type = "nar"

        logger.info(f"Processing {race_id} ({venue} {race.get('race_name', '')}) [type={race_type}]")

        # 2. Resolve custom race_id to netkeiba format if needed
        scrape_race_id = race_id
        if _is_custom_race_id(race_id):
            resolved = _resolve_netkeiba_id(race_id, race_type)
            if not resolved:
                logger.warning(f"Skipping {race_id} — could not resolve to netkeiba ID")
                errors += 1
                continue
            scrape_race_id = resolved

        # 3. Scrape result using netkeiba race_id
        try:
            result = fetch_race_result(scrape_race_id, race_type)
        except Exception:
            logger.exception(f"Error fetching result for {scrape_race_id}")
            errors += 1
            time.sleep(2)
            continue

        if not result:
            logger.warning(f"No result available for {scrape_race_id} — race may not be finished yet")
            time.sleep(1)
            continue

        # 4. Save result using ORIGINAL race_id (to match predictions)
        try:
            save_race_result(
                race_id=race_id,
                winner_number=result["winner_number"],
                winner_name=result["winner_name"],
                win_payout=result["win_payout"],
                result_json=result["result_json"],
                race_name=race.get("race_name", ""),
                venue=venue,
                race_date=date_str,
                race_type=race_type,
            )
            fetched += 1
        except Exception:
            logger.exception(f"Error saving result for {race_id}")
            errors += 1
            continue

        # 5. Judge predictions + update stats
        try:
            judgement = judge_predictions(race_id)
            if "error" not in judgement:
                total = judgement["total_predictions"]
                wins = len(judgement["winners"])
                logger.info(
                    f"  Result: {result['winner_number']} {result['winner_name']} "
                    f"(payout: {result['win_payout']}円) — "
                    f"{wins}/{total} users correct"
                )

                updated = update_user_stats_for_race(race_id)
                judged += updated
        except Exception:
            logger.exception(f"Error judging predictions for {race_id}")
            errors += 1

        # 6. Judge MYBOT predictions for this race
        try:
            _judge_mybot_predictions(
                race_id=race_id,
                winner_number=result["winner_number"],
                win_payout=result["win_payout"],
            )
        except Exception:
            logger.exception(f"Error judging MYBOT predictions for {race_id}")

        # Be polite to netkeiba
        time.sleep(2)

    logger.info(
        f"=== Done: {fetched} results fetched, {judged} user stats updated, {errors} errors ==="
    )


def _judge_mybot_predictions(race_id: str, winner_number: int, win_payout: int) -> None:
    """Judge all MYBOT predictions for a given race and update stats."""
    from db.supabase_client import get_client
    sb = get_client()

    # Find all MYBOT predictions for this race
    res = sb.table("mybot_predictions").select("*").eq("race_id", race_id).execute()
    if not res.data:
        return

    for pred in res.data:
        bot_user_id = pred["bot_user_id"]
        is_win = pred["s_rank_horse_number"] == winner_number
        payout = win_payout if is_win else 0

        # Get or create stats
        stats_res = sb.table("mybot_stats").select("*").eq("bot_user_id", bot_user_id).execute()
        if stats_res.data:
            stats = stats_res.data[0]
            total_predictions = stats["total_predictions"] + 1
            total_wins = stats["total_wins"] + (1 if is_win else 0)
            total_payout = stats["total_payout"] + payout
        else:
            total_predictions = 1
            total_wins = 1 if is_win else 0
            total_payout = payout

        total_bet = total_predictions * 100
        recovery_rate = (total_payout / total_bet * 100) if total_bet > 0 else 0
        win_rate = (total_wins / total_predictions * 100) if total_predictions > 0 else 0

        sb.table("mybot_stats").upsert({
            "bot_user_id": bot_user_id,
            "total_predictions": total_predictions,
            "total_wins": total_wins,
            "total_payout": total_payout,
            "recovery_rate": round(recovery_rate, 1),
            "win_rate": round(win_rate, 1),
            "last_updated_at": datetime.now(JST).isoformat(),
        }, on_conflict="bot_user_id").execute()

        logger.info(
            f"  MYBOT {bot_user_id}: S={pred['s_rank_horse_number']} "
            f"{'HIT' if is_win else 'MISS'} "
            f"(recovery={recovery_rate:.1f}%, win={win_rate:.1f}%)"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch race results and judge predictions")
    parser.add_argument("--date", type=str, default="",
                        help="Date in YYYY-MM-DD format (default: today)")
    args = parser.parse_args()
    run(args.date)
