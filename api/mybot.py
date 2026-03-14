"""MYBOT API — settings CRUD, icon upload, and chat endpoints.

GET  /api/mybot/settings          — Get user's MYBOT settings
POST /api/mybot/settings          — Create or update MYBOT settings
GET  /api/mybot/settings/history  — Get settings edit history
POST /api/mybot/settings/restore  — Restore from history snapshot
POST /api/mybot/upload-icon       — Upload bot icon image
GET  /api/mybot/public/<user_id>  — Get public bot info (no auth)
POST /api/mybot/chat              — MYBOT chat (SSE)
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, Response

from api.auth import verify_auth_header
from db.supabase_client import get_client

logger = logging.getLogger(__name__)

bp = Blueprint("mybot", __name__)

# Default IMLogic weights
DEFAULT_ITEM_WEIGHTS = {
    "1_distance_aptitude": 8.33,
    "2_bloodline_evaluation": 8.33,
    "3_jockey_compatibility": 8.33,
    "4_trainer_evaluation": 8.33,
    "5_track_aptitude": 8.33,
    "6_weather_aptitude": 8.33,
    "7_popularity_factor": 8.33,
    "8_weight_impact": 8.33,
    "9_horse_weight_impact": 8.33,
    "10_corner_specialist": 8.33,
    "11_margin_analysis": 8.33,
    "12_time_index": 8.37,
}

VALID_ITEM_KEYS = set(DEFAULT_ITEM_WEIGHTS.keys())


def _validate_weights(data: dict) -> str | None:
    """Validate horse/jockey weights and item_weights. Returns error message or None."""
    hw = data.get("horse_weight", 70)
    jw = data.get("jockey_weight", 30)
    if not isinstance(hw, int) or not isinstance(jw, int):
        return "horse_weight and jockey_weight must be integers"
    if hw + jw != 100:
        return f"horse_weight + jockey_weight must equal 100 (got {hw + jw})"
    if hw < 0 or jw < 0:
        return "weights must be non-negative"

    iw = data.get("item_weights")
    if iw:
        if not isinstance(iw, dict):
            return "item_weights must be a dict"
        for key in iw:
            if key not in VALID_ITEM_KEYS:
                return f"Invalid item_weight key: {key}"
        total = sum(iw.values())
        if abs(total - 100) > 0.5:
            return f"item_weights must sum to 100 (got {total:.2f})"

    return None


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/settings", methods=["GET"])
def get_settings():
    """Get the authenticated user's MYBOT settings."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()

    result = sb.table("mybot_settings").select("*").eq("user_id", user_id).execute()
    if result.data:
        return jsonify({"settings": result.data[0]})
    else:
        return jsonify({"settings": None})


@bp.route("/api/mybot/settings", methods=["POST"])
def save_settings():
    """Create or update MYBOT settings. Saves history on update."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    # Validate weights
    err = _validate_weights(data)
    if err:
        return jsonify({"error": err}), 400

    # Validate bot_name
    bot_name = data.get("bot_name", "MYBOT").strip()
    if not bot_name or len(bot_name) > 20:
        return jsonify({"error": "bot_name must be 1-20 characters"}), 400

    sb = get_client()

    # Check if settings already exist
    existing = sb.table("mybot_settings").select("*").eq("user_id", user_id).execute()

    row = {
        "bot_name": bot_name,
        "personality": data.get("personality", "friendly"),
        "tone": data.get("tone", "casual"),
        "description": data.get("description", ""),
        "horse_weight": data.get("horse_weight", 70),
        "jockey_weight": data.get("jockey_weight", 30),
        "item_weights": data.get("item_weights", DEFAULT_ITEM_WEIGHTS),
        "is_public": data.get("is_public", False),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if existing.data:
        # Save current state to history before updating
        old = existing.data[0]
        snapshot = {
            "bot_name": old["bot_name"],
            "personality": old["personality"],
            "tone": old["tone"],
            "horse_weight": old["horse_weight"],
            "jockey_weight": old["jockey_weight"],
            "item_weights": old["item_weights"],
            "is_public": old["is_public"],
            "description": old.get("description", ""),
            "icon_url": old.get("icon_url"),
        }
        sb.table("mybot_settings_history").insert({
            "user_id": user_id,
            "snapshot": snapshot,
            "label": data.get("history_label"),
        }).execute()

        # Update
        result = sb.table("mybot_settings").update(row).eq("user_id", user_id).execute()
        action = "updated"
    else:
        # Create
        row["user_id"] = user_id
        result = sb.table("mybot_settings").insert(row).execute()
        action = "created"

    logger.info(f"MYBOT settings {action} for user {user_id}")
    return jsonify({"status": action, "settings": result.data[0] if result.data else row})


# ---------------------------------------------------------------------------
# Settings History
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/settings/history", methods=["GET"])
def get_history():
    """Get edit history for authenticated user's MYBOT."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()

    result = (
        sb.table("mybot_settings_history")
        .select("id, snapshot, label, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )

    return jsonify({"history": result.data})


@bp.route("/api/mybot/settings/restore", methods=["POST"])
def restore_settings():
    """Restore settings from a history snapshot."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    data = request.get_json(silent=True)
    if not data or not data.get("history_id"):
        return jsonify({"error": "history_id required"}), 400

    sb = get_client()

    # Fetch the history entry
    hist = (
        sb.table("mybot_settings_history")
        .select("*")
        .eq("id", data["history_id"])
        .eq("user_id", user_id)
        .execute()
    )
    if not hist.data:
        return jsonify({"error": "History entry not found"}), 404

    snapshot = hist.data[0]["snapshot"]

    # Save current state to history first
    existing = sb.table("mybot_settings").select("*").eq("user_id", user_id).execute()
    if existing.data:
        old = existing.data[0]
        sb.table("mybot_settings_history").insert({
            "user_id": user_id,
            "snapshot": {
                "bot_name": old["bot_name"],
                "personality": old["personality"],
                "tone": old["tone"],
                "horse_weight": old["horse_weight"],
                "jockey_weight": old["jockey_weight"],
                "item_weights": old["item_weights"],
                "is_public": old["is_public"],
                "description": old.get("description", ""),
                "icon_url": old.get("icon_url"),
            },
            "label": "復元前の自動バックアップ",
        }).execute()

    # Restore from snapshot
    update_data = {
        "bot_name": snapshot.get("bot_name", "MYBOT"),
        "personality": snapshot.get("personality", "friendly"),
        "tone": snapshot.get("tone", "casual"),
        "horse_weight": snapshot.get("horse_weight", 70),
        "jockey_weight": snapshot.get("jockey_weight", 30),
        "item_weights": snapshot.get("item_weights", DEFAULT_ITEM_WEIGHTS),
        "is_public": snapshot.get("is_public", False),
        "description": snapshot.get("description", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Restore icon_url if present in snapshot
    if "icon_url" in snapshot:
        update_data["icon_url"] = snapshot["icon_url"]

    result = sb.table("mybot_settings").update(update_data).eq("user_id", user_id).execute()

    logger.info(f"MYBOT settings restored from history for user {user_id}")
    return jsonify({"status": "restored", "settings": result.data[0] if result.data else update_data})


# ---------------------------------------------------------------------------
# Icon Upload
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/upload-icon", methods=["POST"])
def upload_icon():
    """Upload bot icon image to Supabase Storage."""
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
    storage_path = f"mybot-icons/{user_id}.{ext}"

    sb = get_client()
    try:
        # Try to remove old file first (ignore errors)
        try:
            sb.storage.from_("mybot-icons").remove([f"{user_id}.png", f"{user_id}.jpg", f"{user_id}.webp"])
        except Exception:
            pass

        sb.storage.from_("mybot-icons").upload(
            storage_path.replace("mybot-icons/", ""),
            file_data,
            {"content-type": file.content_type},
        )

        # Get public URL
        public_url = sb.storage.from_("mybot-icons").get_public_url(
            storage_path.replace("mybot-icons/", "")
        )

        # Update settings with icon URL
        sb.table("mybot_settings").update({
            "icon_url": public_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).execute()

        logger.info(f"Icon uploaded for user {user_id}")
        return jsonify({"icon_url": public_url})

    except Exception as e:
        logger.exception(f"Icon upload failed for {user_id}")
        return jsonify({"error": "Upload failed"}), 500


# ---------------------------------------------------------------------------
# Public BOT info (no auth)
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/public/<bot_user_id>", methods=["GET"])
def get_public_bot(bot_user_id):
    """Get public bot info (for viewing other users' bots)."""
    sb = get_client()

    result = (
        sb.table("mybot_settings")
        .select("bot_name, personality, tone, icon_url, description, horse_weight, jockey_weight, item_weights, is_public, user_id")
        .eq("user_id", bot_user_id)
        .execute()
    )

    if not result.data:
        return jsonify({"error": "Bot not found"}), 404

    bot = result.data[0]
    if not bot.get("is_public"):
        return jsonify({"error": "This bot is private"}), 403

    return jsonify({"bot": bot})


# ---------------------------------------------------------------------------
# MYBOT Chat (SSE)
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/chat", methods=["POST"])
def mybot_chat():
    """SSE streaming chat for MYBOT — uses user's IMLogic weights."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    session_id = data.get("session_id", str(uuid.uuid4()))
    # bot_user_id: whose bot settings to use (own or public bot)
    bot_user_id = data.get("bot_user_id", payload["pid"])

    # Load bot settings
    sb = get_client()
    bot_result = sb.table("mybot_settings").select("*").eq("user_id", bot_user_id).execute()
    if not bot_result.data:
        return jsonify({"error": "Bot not found. Create your bot first."}), 404

    bot_settings = bot_result.data[0]

    # If not owner, check public
    if bot_user_id != payload["pid"] and not bot_settings.get("is_public"):
        return jsonify({"error": "This bot is private"}), 403

    from agent.engine import TOOL_LABELS, trim_history
    from agent.mybot_chat import run_mybot_agent

    # Session management (similar to web_chat)
    from api.web_chat import _sessions, _cleanup_old_sessions, _SESSION_MAX_AGE
    from db.user_manager import get_or_create_user

    if len(_sessions) > 100:
        _cleanup_old_sessions()

    auth_key = f"mybot_{payload['lid']}_{bot_user_id}"
    if auth_key in _sessions:
        session = _sessions[auth_key]
        session["last_active"] = datetime.now(timezone.utc).timestamp()
    else:
        profile = get_or_create_user(payload["lid"], payload["name"])
        session = {
            "profile": profile,
            "history": [],
            "active_race_id": None,
            "created_at": datetime.now(timezone.utc).timestamp(),
            "last_active": datetime.now(timezone.utc).timestamp(),
        }
        _sessions[auth_key] = session

    history = trim_history(session["history"])
    session["history"] = history
    profile = session["profile"]

    def generate():
        try:
            for chunk in run_mybot_agent(
                user_message=message,
                history=history,
                profile=profile,
                bot_settings=bot_settings,
                active_race_id_hint=session.get("active_race_id"),
            ):
                chunk_type = chunk.get("type")

                if chunk_type == "thinking":
                    yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

                elif chunk_type == "tool":
                    tool_name = chunk.get("name", "")
                    label = TOOL_LABELS.get(tool_name, tool_name)
                    yield f"data: {json.dumps({'type': 'tool', 'name': tool_name, 'label': label}, ensure_ascii=False)}\n\n"

                elif chunk_type == "done":
                    session["history"] = chunk.get("history", history)
                    if chunk.get("active_race_id"):
                        session["active_race_id"] = chunk["active_race_id"]

                    yield f"data: {json.dumps({'type': 'text', 'content': chunk['text']}, ensure_ascii=False)}\n\n"
                    done_data = {
                        "type": "done",
                        "session_id": session_id,
                        "quick_replies": chunk.get("quick_replies", []),
                    }
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception:
            logger.exception(f"MYBOT chat error for {auth_key}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'エラーが発生しました。'}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
