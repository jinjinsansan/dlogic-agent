"""User profile and memory management via Supabase."""

import logging
import random
import string
from datetime import datetime, timezone
from db.supabase_client import get_client

logger = logging.getLogger(__name__)


def _generate_transfer_code() -> str:
    """Generate a unique 6-character alphanumeric transfer code (uppercase)."""
    sb = get_client()
    for _ in range(10):  # retry to avoid collision
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        # Check uniqueness
        res = sb.table("user_profiles") \
            .select("id") \
            .eq("transfer_code", code) \
            .limit(1) \
            .execute()
        if not res.data:
            return code
    # Fallback: 8 chars if 6-char collisions (extremely unlikely)
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


# ---------------------------------------------------------------------------
# User profile CRUD
# ---------------------------------------------------------------------------

def get_or_create_user(line_user_id: str, display_name: str) -> dict:
    """Get existing user or create new one. Returns profile dict."""
    sb = get_client()

    # Try to fetch existing
    res = sb.table("user_profiles") \
        .select("*") \
        .eq("line_user_id", line_user_id) \
        .limit(1) \
        .execute()

    if res.data:
        profile = res.data[0]
        update_fields = {
            "visit_count": profile["visit_count"] + 1,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "display_name": display_name,
        }
        # Generate transfer code for existing users who don't have one yet
        if not profile.get("transfer_code"):
            code = _generate_transfer_code()
            update_fields["transfer_code"] = code
            profile["transfer_code"] = code
            logger.info(f"Generated transfer code for existing user: {display_name}")

        sb.table("user_profiles") \
            .update(update_fields) \
            .eq("id", profile["id"]) \
            .execute()
        profile["visit_count"] += 1
        return profile

    # Create new user with transfer code
    code = _generate_transfer_code()
    new_user = {
        "line_user_id": line_user_id,
        "display_name": display_name,
        "visit_count": 1,
        "transfer_code": code,
    }
    res = sb.table("user_profiles").insert(new_user).execute()
    logger.info(f"New LINE user created: {display_name} ({line_user_id[:10]}...) code={code}")
    return res.data[0]


def update_profile_field(profile_id: str, field: str, value) -> None:
    """Update a single profile field."""
    sb = get_client()
    sb.table("user_profiles") \
        .update({field: value}) \
        .eq("id", profile_id) \
        .execute()


def increment_predictions(profile_id: str) -> None:
    """Increment total_predictions counter."""
    sb = get_client()
    # Fetch current value then increment
    res = sb.table("user_profiles") \
        .select("total_predictions") \
        .eq("id", profile_id) \
        .limit(1) \
        .execute()
    if res.data:
        current = res.data[0]["total_predictions"] or 0
        sb.table("user_profiles") \
            .update({"total_predictions": current + 1}) \
            .eq("id", profile_id) \
            .execute()


# ---------------------------------------------------------------------------
# Transfer (account migration)
# ---------------------------------------------------------------------------

def get_transfer_code(profile_id: str) -> str:
    """Get user's transfer code."""
    sb = get_client()
    res = sb.table("user_profiles") \
        .select("transfer_code") \
        .eq("id", profile_id) \
        .limit(1) \
        .execute()
    if res.data and res.data[0].get("transfer_code"):
        return res.data[0]["transfer_code"]
    # Generate if missing
    code = _generate_transfer_code()
    sb.table("user_profiles") \
        .update({"transfer_code": code}) \
        .eq("id", profile_id) \
        .execute()
    return code


def transfer_account(new_line_user_id: str, transfer_code: str, new_display_name: str) -> dict | None:
    """Transfer old account data to new LINE user ID using transfer code.

    Returns the migrated profile dict, or None if code is invalid.
    """
    sb = get_client()

    # Find profile by transfer code
    res = sb.table("user_profiles") \
        .select("*") \
        .eq("transfer_code", transfer_code.upper().strip()) \
        .limit(1) \
        .execute()

    if not res.data:
        return None

    old_profile = res.data[0]

    # Prevent self-transfer
    if old_profile["line_user_id"] == new_line_user_id:
        return old_profile  # Already the same user

    # Check if the new LINE user already has a profile (fresh follow)
    new_res = sb.table("user_profiles") \
        .select("id") \
        .eq("line_user_id", new_line_user_id) \
        .limit(1) \
        .execute()

    if new_res.data:
        # Delete the empty new profile (it was just created on follow)
        new_id = new_res.data[0]["id"]
        sb.table("user_memories").delete().eq("user_profile_id", new_id).execute()
        sb.table("prediction_history").delete().eq("user_profile_id", new_id).execute()
        sb.table("user_profiles").delete().eq("id", new_id).execute()
        logger.info(f"Deleted empty new profile {new_id} for transfer")

    # Update old profile with new LINE user ID and generate new transfer code
    new_code = _generate_transfer_code()
    sb.table("user_profiles") \
        .update({
            "line_user_id": new_line_user_id,
            "display_name": new_display_name,
            "transfer_code": new_code,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }) \
        .eq("id", old_profile["id"]) \
        .execute()

    old_profile["line_user_id"] = new_line_user_id
    old_profile["display_name"] = new_display_name
    old_profile["transfer_code"] = new_code
    logger.info(f"Account transferred: {old_profile['id']} → new LINE user {new_line_user_id[:10]}...")
    return old_profile


# ---------------------------------------------------------------------------
# User memories CRUD
# ---------------------------------------------------------------------------

def get_memories(profile_id: str, limit: int = 20) -> list[dict]:
    """Get user's memories, most recent first."""
    sb = get_client()
    res = sb.table("user_memories") \
        .select("*") \
        .eq("user_profile_id", profile_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return res.data


def add_memory(profile_id: str, content: str, category: str = "general") -> None:
    """Add a memory, skip if duplicate content exists."""
    sb = get_client()

    # Check for duplicate
    existing = sb.table("user_memories") \
        .select("id") \
        .eq("user_profile_id", profile_id) \
        .eq("content", content) \
        .limit(1) \
        .execute()

    if existing.data:
        return  # Already exists

    sb.table("user_memories").insert({
        "user_profile_id": profile_id,
        "content": content,
        "category": category,
    }).execute()


def add_memories(profile_id: str, memories: list[str]) -> None:
    """Add multiple memories at once."""
    for mem in memories:
        if mem and len(mem) > 2:
            add_memory(profile_id, mem)


def clear_memories(profile_id: str) -> None:
    """Delete all memories for a user."""
    sb = get_client()
    sb.table("user_memories") \
        .delete() \
        .eq("user_profile_id", profile_id) \
        .execute()


# ---------------------------------------------------------------------------
# Prediction history
# ---------------------------------------------------------------------------

def log_prediction(profile_id: str, race_id: str, race_name: str = "", venue: str = "") -> None:
    """Log a prediction request."""
    sb = get_client()
    sb.table("prediction_history").insert({
        "user_profile_id": profile_id,
        "race_id": race_id,
        "race_name": race_name,
        "venue": venue,
    }).execute()
    increment_predictions(profile_id)


# ---------------------------------------------------------------------------
# Build system prompt context
# ---------------------------------------------------------------------------

def build_user_context(profile: dict, memories: list[dict]) -> str:
    """Build user context string for the system prompt from Supabase data."""
    lines = []
    name = profile.get("display_name", "ゲスト")
    visits = profile.get("visit_count", 1)

    lines.append(f"【このユーザーについて】")
    lines.append(f"名前: {name}")

    if visits == 1:
        lines.append("初めての訪問。歓迎して、どんな競馬が好きか自然に聞いてみて。")
    elif visits <= 5:
        lines.append(f"まだ {visits} 回目の訪問。少しずつ打ち解けていこう。")
    elif visits <= 20:
        lines.append(f"{visits} 回目の訪問。もう顔なじみ。気軽に話そう。")
    else:
        lines.append(f"{visits} 回目の常連！親友レベルで話そう。")

    # Structured preferences
    prefs = []
    venues = profile.get("favorite_venues") or []
    if venues:
        prefs.append(f"よく見る競馬場: {', '.join(venues)}")
    horses = profile.get("favorite_horses") or []
    if horses:
        prefs.append(f"推し馬: {', '.join(horses)}")
    jockeys = profile.get("favorite_jockeys") or []
    if jockeys:
        prefs.append(f"推し騎手: {', '.join(jockeys)}")
    if profile.get("bet_style"):
        prefs.append(f"馬券スタイル: {profile['bet_style']}")
    if profile.get("risk_level"):
        prefs.append(f"リスク傾向: {profile['risk_level']}")

    if prefs:
        lines.append("")
        lines.append("【好み・傾向】")
        for p in prefs:
            lines.append(f"- {p}")

    # Free-form memories
    if memories:
        lines.append("")
        lines.append("【覚えていること（自然に会話に活かして）】")
        for m in memories:
            lines.append(f"- {m['content']}")

    total_preds = profile.get("total_predictions", 0)
    if total_preds > 0:
        lines.append(f"\n累計予想リクエスト: {total_preds}回")

    return "\n".join(lines)
