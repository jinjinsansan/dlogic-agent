"""User prediction management for 'みんなの予想' feature via Supabase."""

import logging
from datetime import datetime, timezone
from db.supabase_client import get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Record / check user predictions
# ---------------------------------------------------------------------------

def record_prediction(
    user_profile_id: str,
    race_id: str,
    horse_number: int,
    horse_name: str,
    race_name: str = "",
    venue: str = "",
    race_date: str = "",
    race_type: str = "jra",
) -> dict:
    """Record or update a user's honmei pick for a race. Returns the saved record."""
    sb = get_client()

    data = {
        "user_profile_id": user_profile_id,
        "race_id": race_id,
        "horse_number": horse_number,
        "horse_name": horse_name,
        "race_name": race_name,
        "venue": venue,
        "race_type": race_type,
    }
    if race_date:
        data["race_date"] = race_date

    # UPSERT: one pick per user per race
    res = sb.table("user_predictions") \
        .upsert(data, on_conflict="user_profile_id,race_id") \
        .execute()

    logger.info(f"Prediction recorded: user={user_profile_id[:8]}... race={race_id} horse={horse_number} {horse_name}")
    return res.data[0] if res.data else data


def check_prediction(user_profile_id: str, race_id: str) -> dict | None:
    """Check if a user already has a prediction for a race. Returns the record or None."""
    sb = get_client()
    res = sb.table("user_predictions") \
        .select("*") \
        .eq("user_profile_id", user_profile_id) \
        .eq("race_id", race_id) \
        .limit(1) \
        .execute()
    return res.data[0] if res.data else None


def get_user_predictions(user_profile_id: str, limit: int = 20) -> list[dict]:
    """Get a user's recent predictions."""
    sb = get_client()
    res = sb.table("user_predictions") \
        .select("*") \
        .eq("user_profile_id", user_profile_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return res.data
