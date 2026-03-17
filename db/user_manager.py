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
        }
        # Only overwrite display_name if user hasn't customized it
        if not profile.get("custom_name"):
            update_fields["display_name"] = display_name
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


def get_or_create_user_by_login(line_login_id: str, display_name: str) -> dict:
    """Get or create user by LINE Login ID (website authentication).

    LINE Login gives a different userId than LINE Messaging API.
    This function uses `line_login_id` column to avoid creating duplicates.
    """
    sb = get_client()

    # 1. Search by line_login_id
    res = sb.table("user_profiles") \
        .select("*") \
        .eq("line_login_id", line_login_id) \
        .limit(1) \
        .execute()

    if res.data:
        profile = res.data[0]
        update_fields = {
            "visit_count": profile["visit_count"] + 1,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        # Only overwrite display_name if user hasn't customized it
        if not profile.get("custom_name"):
            update_fields["display_name"] = display_name
        sb.table("user_profiles") \
            .update(update_fields) \
            .eq("id", profile["id"]) \
            .execute()
        profile["visit_count"] += 1
        return profile

    # 2. Not found — create new profile with line_login_id
    code = _generate_transfer_code()
    new_user = {
        "line_user_id": f"login_{line_login_id}",  # placeholder (not a real Messaging API ID)
        "line_login_id": line_login_id,
        "display_name": display_name,
        "visit_count": 1,
        "transfer_code": code,
    }
    res = sb.table("user_profiles").insert(new_user).execute()
    logger.info(f"New web user created: {display_name} (login_id={line_login_id[:10]}...)")
    return res.data[0]


def link_login_to_profile(profile_id: str, line_login_id: str) -> bool:
    """Link a LINE Login ID to an existing profile (account linking).

    Used when a user who already has a Dlogic LINE Bot profile
    logs into the website and wants to link their accounts.
    Skips gracefully if the profile already has a line_login_id set.
    """
    sb = get_client()
    try:
        # Check if profile already has a line_login_id
        res = sb.table("user_profiles") \
            .select("line_login_id") \
            .eq("id", profile_id) \
            .limit(1) \
            .execute()
        if res.data and res.data[0].get("line_login_id"):
            logger.info(f"Profile {profile_id[:10]}... already has login_id, skipping link")
            return True

        # Check if this login_id is already used by another profile
        existing = sb.table("user_profiles") \
            .select("id") \
            .eq("line_login_id", line_login_id) \
            .limit(1) \
            .execute()
        if existing.data:
            logger.info(f"login_id={line_login_id[:10]}... already used by another profile, skipping")
            return True

        sb.table("user_profiles") \
            .update({"line_login_id": line_login_id}) \
            .eq("id", profile_id) \
            .execute()
        logger.info(f"Linked login_id={line_login_id[:10]}... to profile={profile_id[:10]}...")
        return True
    except Exception:
        logger.exception(f"Failed to link login_id to profile {profile_id}")
        return False


def sync_profiles(profile_a_id: str, profile_b_id: str) -> bool:
    """Bidirectional sync: copy memories and profile fields between two profiles.

    Both profiles survive. Neither is deleted.
    - Memories are duplicated to both sides (skipping exact duplicates).
    - visit_count and total_predictions are summed on both.
    - Preferences are copied to whichever side is missing them.
    """
    if profile_a_id == profile_b_id:
        logger.info("sync_profiles: same ID, nothing to do")
        return True

    sb = get_client()
    try:
        # 1. Fetch both profiles
        a_res = sb.table("user_profiles").select("*").eq("id", profile_a_id).limit(1).execute()
        b_res = sb.table("user_profiles").select("*").eq("id", profile_b_id).limit(1).execute()
        if not a_res.data or not b_res.data:
            logger.warning("sync_profiles: one or both profiles not found")
            return False

        prof_a = a_res.data[0]
        prof_b = b_res.data[0]

        # 2. Sum visit_count and total_predictions
        total_visits = (prof_a.get("visit_count") or 0) + (prof_b.get("visit_count") or 0)
        total_preds = (prof_a.get("total_predictions") or 0) + (prof_b.get("total_predictions") or 0)

        # 3. Build update fields for each side
        update_a = {"visit_count": total_visits, "total_predictions": total_preds}
        update_b = {"visit_count": total_visits, "total_predictions": total_preds}

        # Copy preferences bidirectionally (fill in blanks)
        for field in ("favorite_venues", "favorite_horses", "favorite_jockeys"):
            if prof_b.get(field) and not prof_a.get(field):
                update_a[field] = prof_b[field]
            if prof_a.get(field) and not prof_b.get(field):
                update_b[field] = prof_a[field]
        for field in ("bet_style", "risk_level"):
            if prof_b.get(field) and not prof_a.get(field):
                update_a[field] = prof_b[field]
            if prof_a.get(field) and not prof_b.get(field):
                update_b[field] = prof_a[field]

        # NOTE: line_login_id has UNIQUE constraint — cannot copy to both sides
        # Each profile keeps its own line_login_id

        sb.table("user_profiles").update(update_a).eq("id", profile_a_id).execute()
        sb.table("user_profiles").update(update_b).eq("id", profile_b_id).execute()

        # 4. Copy memories bidirectionally (skip duplicates by content)
        mems_a = sb.table("user_memories").select("content, category") \
            .eq("user_profile_id", profile_a_id).execute().data or []
        mems_b = sb.table("user_memories").select("content, category") \
            .eq("user_profile_id", profile_b_id).execute().data or []

        contents_a = {m["content"] for m in mems_a}
        contents_b = {m["content"] for m in mems_b}

        # B→A: copy memories B has that A doesn't
        for m in mems_b:
            if m["content"] not in contents_a:
                sb.table("user_memories").insert({
                    "user_profile_id": profile_a_id,
                    "content": m["content"],
                    "category": m.get("category", "general"),
                }).execute()

        # A→B: copy memories A has that B doesn't
        for m in mems_a:
            if m["content"] not in contents_b:
                sb.table("user_memories").insert({
                    "user_profile_id": profile_b_id,
                    "content": m["content"],
                    "category": m.get("category", "general"),
                }).execute()

        copied_a_to_b = sum(1 for m in mems_a if m["content"] not in contents_b)
        copied_b_to_a = sum(1 for m in mems_b if m["content"] not in contents_a)
        logger.info(
            f"Synced profiles {profile_a_id[:10]}... <-> {profile_b_id[:10]}... "
            f"(visits={total_visits}, mems A→B={copied_a_to_b}, B→A={copied_b_to_a})"
        )
        return True
    except Exception:
        logger.exception(f"Failed to sync profiles {profile_a_id} <-> {profile_b_id}")
        return False


# Keep merge_profiles as alias for backward compatibility
merge_profiles = sync_profiles


def update_profile_field(profile_id: str, field: str, value) -> None:
    """Update a single profile field."""
    sb = get_client()
    sb.table("user_profiles") \
        .update({field: value}) \
        .eq("id", profile_id) \
        .execute()


def increment_predictions(profile_id: str) -> None:
    """Increment total_predictions counter (atomic via RPC, fallback to read-then-write)."""
    sb = get_client()
    try:
        # Try atomic increment via Supabase RPC (requires increment_field function)
        sb.rpc("increment_field", {
            "row_id": profile_id,
            "table_name": "user_profiles",
            "field_name": "total_predictions",
        }).execute()
    except Exception:
        # Fallback: read-then-write (acceptable race window for a counter)
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


# ---------------------------------------------------------------------------
# Maintenance & Waitlist management
# ---------------------------------------------------------------------------

def get_bot_config(key: str) -> dict:
    """Get a bot_config value by key. Returns empty dict if not found."""
    sb = get_client()
    try:
        res = sb.table("bot_config") \
            .select("value") \
            .eq("key", key) \
            .limit(1) \
            .execute()
        if res.data:
            return res.data[0]["value"]
    except Exception:
        logger.exception(f"Failed to get bot_config: {key}")
    return {}


def set_bot_config(key: str, value: dict) -> None:
    """Upsert a bot_config value."""
    sb = get_client()
    sb.table("bot_config") \
        .upsert({"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .execute()


def is_maintenance_mode() -> bool:
    """Check if maintenance mode is enabled."""
    config = get_bot_config("maintenance")
    return config.get("enabled", False)


def get_maintenance_message() -> str:
    """Get the maintenance message."""
    config = get_bot_config("maintenance")
    return config.get("message", "ただいまメンテナンス中です。しばらくお待ちください。")


def set_maintenance(enabled: bool, message: str = None) -> None:
    """Toggle maintenance mode."""
    config = get_bot_config("maintenance")
    config["enabled"] = enabled
    if message:
        config["message"] = message
    set_bot_config("maintenance", config)


def get_user_status(profile_id: str) -> str:
    """Get user's status (active/waitlist/suspended)."""
    sb = get_client()
    res = sb.table("user_profiles") \
        .select("status") \
        .eq("id", profile_id) \
        .limit(1) \
        .execute()
    if res.data:
        return res.data[0].get("status") or "active"
    return "active"


def set_user_status(profile_id: str, status: str) -> None:
    """Set user's status."""
    sb = get_client()
    sb.table("user_profiles") \
        .update({"status": status}) \
        .eq("id", profile_id) \
        .execute()


def activate_users(count: int) -> list[dict]:
    """Activate `count` waitlisted users (oldest first). Returns activated profiles."""
    sb = get_client()
    res = sb.table("user_profiles") \
        .select("id, display_name, line_user_id") \
        .eq("status", "waitlist") \
        .order("first_seen_at", desc=False) \
        .limit(count) \
        .execute()

    activated = []
    for profile in res.data:
        sb.table("user_profiles") \
            .update({"status": "active"}) \
            .eq("id", profile["id"]) \
            .execute()
        activated.append(profile)
    return activated


def get_waitlist_count() -> int:
    """Get number of users in waitlist."""
    sb = get_client()
    res = sb.table("user_profiles") \
        .select("id", count="exact") \
        .eq("status", "waitlist") \
        .execute()
    return res.count or 0


def get_active_count() -> int:
    """Get number of active users."""
    sb = get_client()
    res = sb.table("user_profiles") \
        .select("id", count="exact") \
        .eq("status", "active") \
        .execute()
    return res.count or 0


def get_total_user_count() -> int:
    """Get total number of users."""
    sb = get_client()
    res = sb.table("user_profiles") \
        .select("id", count="exact") \
        .execute()
    return res.count or 0


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
