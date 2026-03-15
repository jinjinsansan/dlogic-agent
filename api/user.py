"""User profile API — view/update profile, upload icon.

GET  /api/user/profile       — Get full user profile
PUT  /api/user/profile       — Update user profile fields
POST /api/user/upload-icon   — Upload user avatar icon
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from api.auth import verify_auth_header
from db.supabase_client import get_client

logger = logging.getLogger(__name__)

bp = Blueprint("user", __name__)


@bp.route("/api/user/profile", methods=["GET"])
def get_profile():
    """Get full user profile with login history, MYBOT settings, and follows."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()

    # User profile
    profile_result = (
        sb.table("user_profiles")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not profile_result.data:
        return jsonify({"error": "Profile not found"}), 404

    profile = profile_result.data[0]

    # Login history (last 10)
    login_result = (
        sb.table("login_history")
        .select("id, logged_in_at, ip_address, user_agent")
        .eq("user_id", user_id)
        .order("logged_in_at", desc=True)
        .limit(10)
        .execute()
    )

    # MYBOT settings (basic info)
    mybot_result = (
        sb.table("mybot_settings")
        .select("bot_name, icon_url, chat_theme, is_public, updated_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    mybot = mybot_result.data[0] if mybot_result.data else None

    # MYBOT LINE connection
    line_result = (
        sb.table("mybot_line_channels")
        .select("webhook_url, bot_name, connected_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    mybot_line = None
    if mybot:
        mybot_line = line_result.data[0] if line_result.data else None

    # Followed bots
    follows_result = (
        sb.table("mybot_follows")
        .select("bot_user_id, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    follows_data = follows_result.data or []

    followed_bots = []
    if follows_data:
        bot_ids = [f["bot_user_id"] for f in follows_data]
        bots_result = (
            sb.table("mybot_settings")
            .select("bot_name, icon_url, user_id")
            .in_("user_id", bot_ids)
            .execute()
        )
        bots_map = {b["user_id"]: b for b in (bots_result.data or [])}

        # Get owner profiles for display names
        owners_result = (
            sb.table("user_profiles")
            .select("id, display_name")
            .in_("id", bot_ids)
            .execute()
        )
        owners_map = {o["id"]: o for o in (owners_result.data or [])}

        for f in follows_data:
            bid = f["bot_user_id"]
            bot = bots_map.get(bid, {})
            owner = owners_map.get(bid, {})
            followed_bots.append({
                "user_id": bid,
                "bot_name": bot.get("bot_name", ""),
                "icon_url": bot.get("icon_url"),
                "owner_name": owner.get("display_name", ""),
                "followed_at": f["created_at"],
            })

    # Build structured mybot response
    mybot_info = None
    if mybot:
        mybot_info = {
            "bot_name": mybot.get("bot_name", "MYBOT"),
            "chat_url": f"https://www.dlogicai.in/mybot/{user_id}",
            "line_connected": mybot_line is not None,
            "line_bot_name": mybot_line.get("bot_name") if mybot_line else None,
        }

    return jsonify({
        "profile": profile,
        "login_history": login_result.data or [],
        "mybot": mybot_info,
        "follows": followed_bots,
    })


@bp.route("/api/user/profile", methods=["PUT"])
def update_profile():
    """Update user profile fields (display_name, x_account, icon_url)."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    # Only allow specific fields
    allowed_fields = {"display_name", "x_account", "icon_url"}
    update = {}
    for field in allowed_fields:
        if field in data:
            value = data[field]
            # Validate
            if field == "display_name":
                if not value or not isinstance(value, str) or len(value.strip()) == 0:
                    return jsonify({"error": "display_name must not be empty"}), 400
                value = value.strip()[:50]
            elif field == "x_account":
                if value is not None:
                    value = str(value).strip().lstrip("@")[:30] if value else None
            elif field == "icon_url":
                if value is not None:
                    value = str(value).strip()[:500] if value else None
            update[field] = value

    if not update:
        return jsonify({"error": "No valid fields to update"}), 400

    update["last_seen_at"] = datetime.now(timezone.utc).isoformat()

    sb = get_client()
    result = sb.table("user_profiles").update(update).eq("id", user_id).execute()

    logger.info(f"Profile updated for user {user_id}: {list(update.keys())}")
    return jsonify({"status": "updated", "profile": result.data[0] if result.data else update})


@bp.route("/api/user/upload-icon", methods=["POST"])
def upload_user_icon():
    """Upload user avatar image to Supabase Storage."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]

    if "icon" not in request.files:
        return jsonify({"error": "No icon file provided"}), 400

    file = request.files["icon"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Validate file type
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed:
        return jsonify({"error": "Only JPG, PNG, WebP allowed"}), 400

    # Read and check size (500KB max)
    file_data = file.read()
    if len(file_data) > 500 * 1024:
        return jsonify({"error": "File too large (max 500KB)"}), 400

    # Upload to Supabase Storage
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    storage_path = f"{user_id}.{ext}"

    sb = get_client()
    try:
        # Try to remove old files first (ignore errors)
        try:
            sb.storage.from_("user-icons").remove([
                f"{user_id}.png", f"{user_id}.jpg", f"{user_id}.webp"
            ])
        except Exception:
            pass

        sb.storage.from_("user-icons").upload(
            storage_path,
            file_data,
            {"content-type": file.content_type},
        )

        # Get public URL
        public_url = sb.storage.from_("user-icons").get_public_url(storage_path)

        # Update user profile with icon URL
        sb.table("user_profiles").update({
            "icon_url": public_url,
        }).eq("id", user_id).execute()

        logger.info(f"User icon uploaded for {user_id}")
        return jsonify({"icon_url": public_url})

    except Exception:
        logger.exception(f"User icon upload failed for {user_id}")
        return jsonify({"error": "Upload failed"}), 500
