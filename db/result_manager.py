"""Race result management + prediction matching for 'みんなの予想' Phase 2."""

import json
import logging
from datetime import datetime, timezone, timedelta

from db.supabase_client import get_client

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Race results CRUD
# ---------------------------------------------------------------------------

def save_race_result(
    race_id: str,
    winner_number: int,
    winner_name: str,
    win_payout: int,
    result_json: dict,
    race_name: str = "",
    venue: str = "",
    race_date: str = "",
    race_type: str = "jra",
) -> dict:
    """Save or update a race result. Returns the saved record."""
    sb = get_client()

    data = {
        "race_id": race_id,
        "winner_number": winner_number,
        "winner_name": winner_name,
        "win_payout": win_payout,
        "result_json": json.dumps(result_json, ensure_ascii=False),
        "race_name": race_name,
        "venue": venue,
        "race_type": race_type,
        "status": "finished",
        "fetched_at": datetime.now(JST).isoformat(),
    }
    if race_date:
        data["race_date"] = race_date

    res = sb.table("race_results") \
        .upsert(data, on_conflict="race_id") \
        .execute()

    logger.info(f"Race result saved: {race_id} winner={winner_number} {winner_name} payout={win_payout}")
    return res.data[0] if res.data else data


def get_race_result(race_id: str) -> dict | None:
    """Get a stored race result by race_id."""
    sb = get_client()
    res = sb.table("race_results") \
        .select("*") \
        .eq("race_id", race_id) \
        .limit(1) \
        .execute()
    return res.data[0] if res.data else None


def get_pending_races(date_str: str = "") -> list[dict]:
    """Get races that have predictions but no results yet.

    Finds race_ids in user_predictions AND mybot_predictions that don't have
    a 'finished' entry in race_results. Optionally filter by date.
    """
    sb = get_client()

    # Get distinct race_ids from user_predictions
    query = sb.table("user_predictions").select("race_id, race_name, venue, race_date, race_type")
    if date_str:
        query = query.eq("race_date", date_str)

    pred_res = query.execute()

    # Deduplicate race_ids
    seen = set()
    races = []
    for p in (pred_res.data or []):
        rid = p["race_id"]
        if rid not in seen:
            seen.add(rid)
            races.append(p)

    # Also include mybot_predictions
    try:
        mybot_query = sb.table("mybot_predictions").select("race_id, race_name, venue")
        mybot_res = mybot_query.execute()
        for p in (mybot_res.data or []):
            rid = p["race_id"]
            if rid not in seen:
                seen.add(rid)
                # Infer race_type from venue
                venue = p.get("venue", "")
                races.append({
                    "race_id": rid,
                    "race_name": p.get("race_name", ""),
                    "venue": venue,
                    "race_date": None,
                    "race_type": "nar" if venue in _NAR_VENUE_SET else "jra",
                })
    except Exception:
        logger.warning("Could not query mybot_predictions for pending races")

    if not races:
        return []

    # Check which already have results
    race_ids = list(seen)
    result_res = sb.table("race_results") \
        .select("race_id") \
        .in_("race_id", race_ids) \
        .eq("status", "finished") \
        .execute()

    finished_ids = {r["race_id"] for r in result_res.data} if result_res.data else set()
    pending = [r for r in races if r["race_id"] not in finished_ids]

    logger.info(f"Pending races: {len(pending)}/{len(races)} (date={date_str or 'all'})")
    return pending


# NAR venues for race_type inference
_NAR_VENUE_SET = {
    "大井", "川崎", "船橋", "浦和", "園田", "姫路", "名古屋", "笠松",
    "金沢", "高知", "佐賀", "盛岡", "水沢", "門別", "帯広",
}


# ---------------------------------------------------------------------------
# Prediction matching (的中判定)
# ---------------------------------------------------------------------------

def judge_predictions(race_id: str) -> dict:
    """Judge all predictions for a race against its result.

    Returns:
        {
            "race_id": str,
            "winner_number": int,
            "winner_name": str,
            "win_payout": int,
            "total_predictions": int,
            "winners": [{"user_profile_id": str, "horse_number": int, "horse_name": str}],
            "losers": [{"user_profile_id": str, "horse_number": int, "horse_name": str}],
        }
    """
    sb = get_client()

    # Get race result
    result = get_race_result(race_id)
    if not result or result["status"] != "finished":
        return {"race_id": race_id, "error": "result_not_found"}

    winner_number = result["winner_number"]
    winner_name = result["winner_name"]
    win_payout = result["win_payout"]

    # Get all predictions for this race
    pred_res = sb.table("user_predictions") \
        .select("user_profile_id, horse_number, horse_name") \
        .eq("race_id", race_id) \
        .execute()

    if not pred_res.data:
        return {
            "race_id": race_id,
            "winner_number": winner_number,
            "winner_name": winner_name,
            "win_payout": win_payout,
            "total_predictions": 0,
            "winners": [],
            "losers": [],
        }

    winners = []
    losers = []
    for pred in pred_res.data:
        entry = {
            "user_profile_id": pred["user_profile_id"],
            "horse_number": pred["horse_number"],
            "horse_name": pred["horse_name"],
        }
        if pred["horse_number"] == winner_number:
            winners.append(entry)
        else:
            losers.append(entry)

    logger.info(
        f"Judged {race_id}: {len(winners)} wins / {len(losers)} losses "
        f"(winner={winner_number} {winner_name}, payout={win_payout})"
    )

    return {
        "race_id": race_id,
        "winner_number": winner_number,
        "winner_name": winner_name,
        "win_payout": win_payout,
        "total_predictions": len(pred_res.data),
        "winners": winners,
        "losers": losers,
    }


def update_user_stats_for_race(race_id: str) -> int:
    """Update user_stats for all users who predicted on this race.

    Idempotent: rebuilds each user's stats from actual data every time.
    Safe to call multiple times for the same race.
    Returns number of users updated.
    """
    judgement = judge_predictions(race_id)
    if "error" in judgement:
        logger.warning(f"Cannot update stats for {race_id}: {judgement['error']}")
        return 0

    # Collect unique user IDs from winners + losers
    user_ids = set()
    for w in judgement["winners"]:
        user_ids.add(w["user_profile_id"])
    for l in judgement["losers"]:
        user_ids.add(l["user_profile_id"])

    updated = 0
    for uid in user_ids:
        _rebuild_user_stats(uid)
        updated += 1

    logger.info(f"Updated stats for {updated} users on race {race_id}")
    return updated


# ---------------------------------------------------------------------------
# Stats & Ranking queries (Phase 3)
# ---------------------------------------------------------------------------

def get_user_stats(user_profile_id: str) -> dict | None:
    """Get a user's prediction stats."""
    sb = get_client()
    res = sb.table("user_stats") \
        .select("*") \
        .eq("user_profile_id", user_profile_id) \
        .limit(1) \
        .execute()
    return res.data[0] if res.data else None


def get_user_recent_results(user_profile_id: str, limit: int = 10) -> list[dict]:
    """Get a user's recent predictions with results (的中/不的中).

    Joins user_predictions with race_results to show outcome.
    """
    sb = get_client()

    # Get recent predictions
    pred_res = sb.table("user_predictions") \
        .select("race_id, horse_number, horse_name, race_name, venue, race_date") \
        .eq("user_profile_id", user_profile_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()

    if not pred_res.data:
        return []

    # Get race results for those races
    race_ids = [p["race_id"] for p in pred_res.data]
    result_res = sb.table("race_results") \
        .select("race_id, winner_number, winner_name, win_payout") \
        .in_("race_id", race_ids) \
        .execute()

    result_map = {r["race_id"]: r for r in result_res.data} if result_res.data else {}

    # Merge
    results = []
    for p in pred_res.data:
        entry = {
            "race_id": p["race_id"],
            "horse_number": p["horse_number"],
            "horse_name": p["horse_name"],
            "race_name": p.get("race_name", ""),
            "venue": p.get("venue", ""),
            "race_date": p.get("race_date", ""),
        }
        r = result_map.get(p["race_id"])
        if r:
            is_win = p["horse_number"] == r["winner_number"]
            entry["result"] = "的中" if is_win else "不的中"
            entry["winner_number"] = r["winner_number"]
            entry["winner_name"] = r["winner_name"]
            entry["win_payout"] = r["win_payout"]
        else:
            entry["result"] = "結果待ち"
        results.append(entry)

    return results


def get_ranking(limit: int = 20) -> list[dict]:
    """Get the prediction ranking (回収率 top N, minimum 3 picks).

    Returns list of {rank, display_name, total_picks, total_wins, win_rate,
                     recovery_rate, best_payout, current_streak}.
    """
    sb = get_client()

    # Get stats with minimum picks filter
    stats_res = sb.table("user_stats") \
        .select("user_profile_id, total_picks, total_wins, win_rate, recovery_rate, best_payout, current_streak") \
        .gte("total_picks", 3) \
        .order("recovery_rate", desc=True) \
        .limit(limit) \
        .execute()

    if not stats_res.data:
        return []

    # Get display names from user_profiles
    user_ids = [s["user_profile_id"] for s in stats_res.data]
    profile_res = sb.table("user_profiles") \
        .select("id, display_name") \
        .in_("id", user_ids) \
        .execute()

    name_map = {}
    if profile_res.data:
        name_map = {p["id"]: p["display_name"] for p in profile_res.data}

    ranking = []
    for i, s in enumerate(stats_res.data, 1):
        uid = s["user_profile_id"]
        name = name_map.get(uid, "???")
        # Mask name for privacy: first char + ***
        if len(name) > 1:
            masked = name[0] + "***"
        else:
            masked = name
        ranking.append({
            "rank": i,
            "display_name": masked,
            "total_picks": s["total_picks"],
            "total_wins": s["total_wins"],
            "win_rate": s["win_rate"],
            "recovery_rate": s["recovery_rate"],
            "best_payout": s["best_payout"],
            "current_streak": s["current_streak"],
        })

    return ranking


def _rebuild_user_stats(user_profile_id: str):
    """Rebuild a single user's stats from user_predictions + race_results.

    Idempotent: always produces the same result regardless of how many times called.
    """
    sb = get_client()
    now = datetime.now(JST).isoformat()

    # Get all predictions for this user
    preds = sb.table("user_predictions") \
        .select("race_id, horse_number") \
        .eq("user_profile_id", user_profile_id) \
        .execute()

    if not preds.data:
        return

    # Get results for races this user predicted on
    race_ids = list({p["race_id"] for p in preds.data})
    results = sb.table("race_results") \
        .select("race_id, winner_number, win_payout") \
        .eq("status", "finished") \
        .in_("race_id", race_ids) \
        .execute()
    result_map = {r["race_id"]: r for r in (results.data or [])}

    # Calculate stats from actual data
    total_picks = 0
    total_wins = 0
    total_payout = 0
    best_payout = 0
    current_streak = 0

    for pred in sorted(preds.data, key=lambda x: x["race_id"]):
        result = result_map.get(pred["race_id"])
        if not result:
            continue  # Race not finished yet

        total_picks += 1
        is_win = pred["horse_number"] == result["winner_number"]

        if is_win:
            total_wins += 1
            total_payout += result["win_payout"]
            current_streak += 1
            best_payout = max(best_payout, result["win_payout"])
        else:
            current_streak = 0

    total_bet = total_picks * 100
    win_rate = round((total_wins / total_picks * 100), 1) if total_picks > 0 else 0
    recovery_rate = round((total_payout / total_bet * 100), 1) if total_bet > 0 else 0

    sb.table("user_stats").upsert({
        "user_profile_id": user_profile_id,
        "total_picks": total_picks,
        "total_wins": total_wins,
        "total_payout": total_payout,
        "total_bet": total_bet,
        "win_rate": win_rate,
        "recovery_rate": recovery_rate,
        "current_streak": current_streak,
        "best_payout": best_payout,
        "last_updated_at": now,
    }, on_conflict="user_profile_id").execute()


def rebuild_all_user_stats() -> int:
    """Rebuild user_stats for ALL users from scratch.

    Fixes any duplicate counting issues by recalculating from actual data.
    Returns number of users rebuilt.
    """
    sb = get_client()

    # Get all unique user IDs from predictions
    all_preds = sb.table("user_predictions") \
        .select("user_profile_id") \
        .execute()
    if not all_preds.data:
        return 0

    user_ids = list({p["user_profile_id"] for p in all_preds.data})

    for uid in user_ids:
        _rebuild_user_stats(uid)

    logger.info(f"Rebuilt stats for {len(user_ids)} users")
    return len(user_ids)
