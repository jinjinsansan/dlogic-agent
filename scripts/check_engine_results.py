#!/usr/bin/env python3
"""Check engine prediction accuracy against actual race results.

Reads prefetch data, calls backend API for predictions, scrapes results,
and saves hit-rate data to Supabase.

Usage:
    python check_engine_results.py                # today
    python check_engine_results.py 20260311       # specific date
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env.local")

from scrapers.race_result import fetch_race_result
from scrapers.nar import NAR_VENUES
from db.engine_stats import save_hit_rate
from db.result_manager import save_race_result, get_race_result, judge_predictions, update_user_stats_for_race

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DLOGIC_API_URL = os.getenv("DLOGIC_API_URL", "http://localhost:8000")
PREFETCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'prefetch')

ENGINES = ["dlogic", "ilogic", "viewlogic", "metalogic"]


def load_prefetch(date_str: str) -> list[dict]:
    """Load prefetch races for a date."""
    path = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
    if not os.path.exists(path):
        logger.error(f"Prefetch file not found: {path}")
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("races", [])


def get_predictions(race: dict) -> dict[str, list[int]] | None:
    """Call backend API to get predictions for a race.

    Returns: {"dlogic": [5, 3, 1, ...], "ilogic": [...], ...} or None
    """
    payload = {
        "race_id": race.get("race_id", ""),
        "horses": race.get("horses", []),
        "horse_numbers": race.get("horse_numbers", []),
        "venue": race.get("venue", ""),
        "race_number": race.get("race_number", 0),
        "jockeys": race.get("jockeys", []),
        "posts": race.get("posts", []),
        "distance": race.get("distance", ""),
        "track_condition": race.get("track_condition", "良"),
    }

    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}/api/v2/predictions/newspaper",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        result = {}
        for eng in ENGINES:
            if eng in data:
                result[eng] = data[eng][:5]
        return result if result else None

    except Exception:
        logger.exception(f"Failed to get predictions for {race.get('race_id')}")
        return None


def process_race(race: dict, date_str: str) -> int:
    """Process a single race: get predictions, get result, save hit-rate.

    Returns: number of engine records saved (0 if skipped).
    """
    race_id = race.get("race_id", "")
    venue = race.get("venue", "")
    race_number = race.get("race_number", 0)
    netkeiba_id = race.get("race_id_netkeiba", "")
    is_local = race.get("is_local", True)
    race_type = "nar" if is_local else "jra"

    if not netkeiba_id:
        logger.warning(f"No netkeiba ID for {race_id}, skipping")
        return 0

    if not race.get("horses"):
        return 0

    # Step 1: Get predictions
    predictions = race.get("predictions")
    if not predictions:
        predictions = get_predictions(race)
    if not predictions:
        logger.info(f"No predictions for {race_id}")
        return 0

    # Step 2: Get result
    result = fetch_race_result(netkeiba_id, race_type)
    if not result or result.get("status") != "finished":
        logger.info(f"No result yet for {race_id} ({netkeiba_id})")
        return 0

    finishing = result.get("finishing_order", [])
    # Filter to actual finishers (position > 0)
    finishers = [f for f in finishing if f.get("position", 0) > 0]
    if len(finishers) < 3:
        logger.warning(f"Incomplete result for {race_id} ({len(finishers)} finishers)")
        return 0

    result_1st = finishers[0]["horse_number"]
    result_2nd = finishers[1]["horse_number"]
    result_3rd = finishers[2]["horse_number"]
    result_set = {result_1st, result_2nd, result_3rd}

    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # Also save to race_results table (needed for recovery rate calculation)
    existing = get_race_result(race_id)
    if not existing:
        try:
            save_race_result(
                race_id=race_id,
                winner_number=result["winner_number"],
                winner_name=result["winner_name"],
                win_payout=result["win_payout"],
                result_json=result["result_json"],
                race_name=race.get("race_name", ""),
                venue=venue,
                race_date=formatted_date,
                race_type=race_type,
            )
            logger.info(f"  Saved to race_results: {race_id} winner={result['winner_number']} payout={result['win_payout']}")
        except Exception:
            logger.exception(f"  Failed to save race_result for {race_id}")
    saved = 0

    # Step 3: Compare each engine
    for eng, top_horses in predictions.items():
        if eng not in ENGINES:
            continue
        if not top_horses:
            continue

        top1 = top_horses[0]
        top3_pred = top_horses[:3]

        hit_win = (top1 == result_1st)
        place_hit_count = len(set(top3_pred) & result_set)
        hit_place = place_hit_count >= 1

        save_hit_rate(
            date=formatted_date,
            race_id=race_id,
            venue=venue,
            race_number=race_number,
            race_type=race_type,
            engine=eng,
            top1_horse=top1,
            top3_horses=top3_pred,
            result_1st=result_1st,
            result_2nd=result_2nd,
            result_3rd=result_3rd,
            hit_win=hit_win,
            hit_place=hit_place,
            place_hit_count=place_hit_count,
        )

        mark = "✅" if hit_win else ("🔶" if hit_place else "❌")
        logger.info(f"  {mark} {eng}: pred={top3_pred} vs result=[{result_1st},{result_2nd},{result_3rd}]")
        saved += 1

    # Step 4: Judge user predictions + MYBOT predictions for this race
    try:
        judgement = judge_predictions(race_id)
        if "error" not in judgement and judgement.get("total_predictions", 0) > 0:
            wins = len(judgement["winners"])
            total_preds = judgement["total_predictions"]
            logger.info(f"  User predictions: {wins}/{total_preds} correct")
            update_user_stats_for_race(race_id)
    except Exception:
        pass  # No user predictions for this race is normal

    try:
        _judge_mybot_predictions(
            race_id=race_id,
            winner_number=result_1st,
            win_payout=result.get("win_payout", 0),
        )
    except Exception:
        pass  # No MYBOT predictions for this race is normal

    return saved


def _judge_mybot_predictions(race_id: str, winner_number: int, win_payout: int) -> None:
    """Judge all MYBOT predictions for a given race and update stats."""
    from db.supabase_client import get_client
    sb = get_client()

    res = sb.table("mybot_predictions").select("*").eq("race_id", race_id).execute()
    if not res.data:
        return

    for pred in res.data:
        bot_user_id = pred["bot_user_id"]
        is_win = pred["s_rank_horse_number"] == winner_number
        payout = win_payout if is_win else 0

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

        mark = "HIT" if is_win else "MISS"
        logger.info(f"  MYBOT {bot_user_id[:8]}...: S={pred['s_rank_horse_number']} {mark} (recovery={recovery_rate:.1f}%)")


def main():
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now(JST).strftime("%Y%m%d")

    logger.info(f"=== Checking engine results for {date_str} ===")

    races = load_prefetch(date_str)
    if not races:
        logger.error("No races found in prefetch")
        sys.exit(1)

    total_saved = 0
    total_processed = 0

    for race in races:
        saved = process_race(race, date_str)
        if saved > 0:
            total_processed += 1
            total_saved += saved
        # Be polite to netkeiba
        time.sleep(1)

    logger.info(f"=== Done: {total_processed} races, {total_saved} engine records saved ===")


if __name__ == "__main__":
    main()
