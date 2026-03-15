"""MYBOT API — settings CRUD, icon upload, chat, and LINE integration.

GET  /api/mybot/settings          — Get user's MYBOT settings
POST /api/mybot/settings          — Create or update MYBOT settings
GET  /api/mybot/settings/history  — Get settings edit history
POST /api/mybot/settings/restore  — Restore from history snapshot
POST /api/mybot/upload-icon       — Upload bot icon image
GET  /api/mybot/public/<user_id>  — Get public bot info (no auth)
POST /api/mybot/chat              — MYBOT chat (SSE)
POST /api/mybot/line/connect      — Connect LINE channel
POST /api/mybot/line/disconnect   — Disconnect LINE channel
GET  /api/mybot/line/status       — Get LINE connection status
POST /api/mybot/line/test         — Send LINE broadcast test message
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import requests as http_requests
from flask import Blueprint, request, jsonify, Response

from api.auth import verify_auth_header
from db.encryption import encrypt_value, decrypt_value
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
        "prediction_style": data.get("prediction_style", "balanced"),
        "analysis_depth": data.get("analysis_depth", "standard"),
        "bet_suggestion": data.get("bet_suggestion", "basic"),
        "risk_level": data.get("risk_level", "moderate"),
        "analysis_focus": data.get("analysis_focus", "general"),
        "custom_instructions": (data.get("custom_instructions") or "")[:500],
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
            "prediction_style": old.get("prediction_style", "balanced"),
            "analysis_depth": old.get("analysis_depth", "standard"),
            "bet_suggestion": old.get("bet_suggestion", "basic"),
            "risk_level": old.get("risk_level", "moderate"),
            "analysis_focus": old.get("analysis_focus", "general"),
            "custom_instructions": old.get("custom_instructions", ""),
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
                "prediction_style": old.get("prediction_style", "balanced"),
                "analysis_depth": old.get("analysis_depth", "standard"),
                "bet_suggestion": old.get("bet_suggestion", "basic"),
                "risk_level": old.get("risk_level", "moderate"),
                "analysis_focus": old.get("analysis_focus", "general"),
                "custom_instructions": old.get("custom_instructions", ""),
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
        "prediction_style": snapshot.get("prediction_style", "balanced"),
        "analysis_depth": snapshot.get("analysis_depth", "standard"),
        "bet_suggestion": snapshot.get("bet_suggestion", "basic"),
        "risk_level": snapshot.get("risk_level", "moderate"),
        "analysis_focus": snapshot.get("analysis_focus", "general"),
        "custom_instructions": snapshot.get("custom_instructions", ""),
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


# ---------------------------------------------------------------------------
# LINE Integration
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/line/connect", methods=["POST"])
def line_connect():
    """Connect a LINE channel to the user's MYBOT."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    channel_id = data.get("channel_id", "").strip()
    channel_secret = data.get("channel_secret", "").strip()
    if not channel_id or not channel_secret:
        return jsonify({"error": "channel_id and channel_secret are required"}), 400

    # 1. Issue access token
    token_resp = http_requests.post(
        "https://api.line.me/v2/oauth/accessToken",
        data={
            "grant_type": "client_credentials",
            "client_id": channel_id,
            "client_secret": channel_secret,
        },
    )
    if token_resp.status_code != 200:
        logger.warning(f"LINE token issue failed for user {user_id}: {token_resp.text}")
        return jsonify({"error": "LINE認証に失敗しました。Channel IDとChannel Secretを確認してください。"}), 400

    access_token = token_resp.json().get("access_token")
    if not access_token:
        return jsonify({"error": "アクセストークンの取得に失敗しました。"}), 400

    # 2. Verify token works by fetching bot info
    bot_info_resp = http_requests.get(
        "https://api.line.me/v2/bot/info",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if bot_info_resp.status_code != 200:
        logger.warning(f"LINE bot info failed for user {user_id}: {bot_info_resp.text}")
        return jsonify({"error": "LINE Botの情報取得に失敗しました。Messaging API チャネルか確認してください。"}), 400

    bot_info = bot_info_resp.json()

    # 3. Set webhook URL
    webhook_url = f"https://bot.dlogicai.in/mybot/webhook/{user_id}"
    webhook_resp = http_requests.put(
        "https://api.line.me/v2/bot/channel/webhook/endpoint",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"endpoint": webhook_url},
    )
    if webhook_resp.status_code != 200:
        logger.warning(f"LINE webhook set failed for user {user_id}: {webhook_resp.text}")
        return jsonify({"error": "Webhook URLの設定に失敗しました。"}), 400

    # 4. Encrypt secrets and upsert
    encrypted_secret = encrypt_value(channel_secret)
    encrypted_token = encrypt_value(access_token)

    sb = get_client()
    row = {
        "user_id": user_id,
        "channel_id": channel_id,
        "channel_secret_enc": encrypted_secret,
        "access_token_enc": encrypted_token,
        "webhook_url": webhook_url,
        "bot_name": bot_info.get("displayName", ""),
        "bot_picture_url": bot_info.get("pictureUrl", ""),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }
    sb.table("mybot_line_channels").upsert(row, on_conflict="user_id").execute()

    logger.info(f"LINE channel connected for user {user_id} (channel_id={channel_id})")

    # Auto-set rich menu (non-blocking, best-effort)
    try:
        from scripts.setup_mybot_richmenu import setup_mybot_richmenu
        rm_id = setup_mybot_richmenu(access_token)
        if rm_id:
            logger.info(f"MYBOT rich menu set for user {user_id}: {rm_id}")
        else:
            logger.warning(f"MYBOT rich menu setup failed for user {user_id}")
    except Exception:
        logger.exception(f"MYBOT rich menu setup error for user {user_id}")

    return jsonify({
        "status": "connected",
        "bot_name": bot_info.get("displayName"),
        "bot_picture_url": bot_info.get("pictureUrl"),
        "webhook_url": webhook_url,
    })


@bp.route("/api/mybot/line/disconnect", methods=["POST"])
def line_disconnect():
    """Disconnect the user's LINE channel."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()
    sb.table("mybot_line_channels").delete().eq("user_id", user_id).execute()

    logger.info(f"LINE channel disconnected for user {user_id}")
    return jsonify({"status": "disconnected"})


@bp.route("/api/mybot/line/status", methods=["GET"])
def line_status():
    """Get LINE connection status for the authenticated user."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()

    result = (
        sb.table("mybot_line_channels")
        .select("channel_id, webhook_url, bot_name, bot_picture_url, connected_at")
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        return jsonify({"connected": False})

    ch = result.data[0]
    # Mask channel_id: show first 4 and last 2 chars
    cid = ch["channel_id"]
    masked_id = f"{cid[:4]}{'*' * max(len(cid) - 6, 0)}{cid[-2:]}" if len(cid) > 6 else cid

    return jsonify({
        "connected": True,
        "channel_id": masked_id,
        "webhook_url": ch["webhook_url"],
        "bot_name": ch.get("bot_name"),
        "bot_picture_url": ch.get("bot_picture_url"),
        "connected_at": ch["connected_at"],
    })


@bp.route("/api/mybot/line/test", methods=["POST"])
def line_test():
    """Send a broadcast test message via the connected LINE channel."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()

    result = (
        sb.table("mybot_line_channels")
        .select("access_token_enc")
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return jsonify({"error": "LINE連携が設定されていません。先に連携してください。"}), 404

    access_token = decrypt_value(result.data[0]["access_token_enc"])

    broadcast_resp = http_requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "messages": [
                {
                    "type": "text",
                    "text": "\U0001f916 MYBOTのLINE連携テストです！正常に動作しています。",
                }
            ]
        },
    )

    if broadcast_resp.status_code != 200:
        logger.warning(f"LINE broadcast failed for user {user_id}: {broadcast_resp.text}")
        return jsonify({"error": "テストメッセージの送信に失敗しました。"}), 400

    logger.info(f"LINE test broadcast sent for user {user_id}")
    return jsonify({"status": "sent", "message": "テストメッセージを送信しました。"})
