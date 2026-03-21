"""MYBOT API — settings CRUD, icon upload, chat, and LINE integration.

GET  /api/mybot/settings          — Get user's MYBOT settings
POST /api/mybot/settings          — Create or update MYBOT settings
GET  /api/mybot/settings/history  — Get settings edit history
POST /api/mybot/settings/restore  — Restore from history snapshot
POST /api/mybot/upload-icon       — Upload bot icon image
GET  /api/mybot/public/<user_id>  — Get public bot info (no auth)
GET  /api/mybot/public/list       — List all public bots
POST /api/mybot/follow            — Follow a bot
DELETE /api/mybot/follow          — Unfollow a bot
GET  /api/mybot/follows           — Get user's followed bots
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
from agent.chat_core import get_mybot_web_quick_replies
from agent.response_cache import find_race_id
from db.encryption import encrypt_value, decrypt_value
from db.supabase_client import get_client
from db.redis_client import get_redis
from db.user_manager import get_user_status
from api.web_chat import load_session, save_session
from tools.executor import resolve_race_id_from_text

logger = logging.getLogger(__name__)

bp = Blueprint("mybot", __name__)

_redis = get_redis()
_INQUIRY_MODE_PREFIX = "mybot:inquiry_mode:web:"
_INQUIRY_MODE_TTL = 300  # 5 minutes
_INQUIRY_KEYWORDS = {"Dlogic運営に問い合わせ", "問い合わせしたい", "お問い合わせ"}

# Rate limiting
_RATE_LIMIT_PREFIX = "mybot:ratelimit:"
_RATE_LIMITS = {
    "chat": (10, 60),       # 10 requests per 60 seconds
    "settings": (5, 60),    # 5 per 60s
    "follow": (10, 60),     # 10 per 60s
    "upload": (3, 60),      # 3 per 60s
    "inquiry": (3, 300),    # 3 per 5 minutes
}

_QUERY_ROUTE_MAP = {
    "prediction": ("predictions", {}),
    "predictions": ("predictions", {}),
    "odds": ("odds", {}),
    "weights": ("weights", {}),
    "odds_probability": ("odds_probability", {}),
    "stable_comments": ("stable_comments", {}),
    "training": ("training", {}),
    "race_results": ("race_results", {}),
    "my_stats": ("my_stats", {}),
    "honmei_ratio": ("honmei_ratio", {}),
    "today_races_jra": ("today_races", {"race_type": "jra"}),
    "today_races_nar": ("today_races", {"race_type": "nar"}),
}


def _route_from_query_type(query_type: str) -> tuple[str, dict] | None:
    if not query_type:
        return None
    return _QUERY_ROUTE_MAP.get(query_type.strip().lower())

# Honmei (本命) blocking keywords (same as LINE)
_RACE_CHANGE_KEYWORDS = [
    "他のレース", "別のレース", "次のレース",
    "船橋", "大井", "川崎", "浦和", "園田", "姫路", "金沢", "名古屋", "笠松", "高知", "佐賀",
    "中山", "阪神", "東京", "京都", "小倉", "新潟", "福島", "札幌", "函館",
    "今日のJRA", "今日の地方", "地方競馬", "JRA", "メインレース",
]

_SAME_RACE_KEYWORDS = [
    "予想して", "オッズ", "馬体重", "関係者", "展開", "騎手", "血統", "過去", "直近",
    "どう思う", "全部", "掘り下げ",
]

_OPINION_KEYWORDS = [
    "どう思う", "見解", "意見",
]


def _is_same_race_query(text: str) -> bool:
    return any(kw in text for kw in _SAME_RACE_KEYWORDS)


def _is_opinion_query(text: str) -> bool:
    return any(kw in text for kw in _OPINION_KEYWORDS)


def _needs_race_prompt(text: str) -> bool:
    return any(kw in text for kw in (
        "予想", "展開", "騎手", "血統", "オッズ", "馬体重", "調教",
        "関係者", "結果", "勝率", "出馬表", "本命比率",
    ))


def _build_honmei_quick_replies(race_id: str) -> list[dict]:
    from tools.executor import _race_cache, execute_tool

    if race_id not in _race_cache or "entries" not in _race_cache[race_id]:
        try:
            execute_tool("get_race_entries", {"race_id": race_id})
        except Exception:
            logger.exception(f"Failed to populate entries for honmei: {race_id}")

    entries = _race_cache.get(race_id, {}).get("entries", {})
    horses = entries.get("horses", [])
    horse_numbers = entries.get("horse_numbers", [])
    if not horses or not horse_numbers:
        return []

    items = []
    for i in range(min(len(horses), len(horse_numbers), 18)):
        num = horse_numbers[i]
        name = horses[i]
        items.append({
            "label": f"{num}.{name}"[:20],
            "text": f"本命 {num}番 {name}",
        })
    return items


def _should_prompt_honmei(race_id: str) -> bool:
    if not race_id:
        return False
    try:
        from tools.executor import is_future_or_today_race
        return is_future_or_today_race(race_id)
    except Exception:
        return False


def _has_pending_honmei(session: dict, profile_id: str) -> bool:
    race_id = session.get("pending_honmei_race")
    if not race_id:
        return False
    if not _should_prompt_honmei(race_id):
        session.pop("pending_honmei_race", None)
        return False
    try:
        from db.prediction_manager import check_prediction
        existing = check_prediction(profile_id, race_id)
    except Exception:
        return False
    if existing:
        session.pop("pending_honmei_race", None)
        return False
    return True


def _check_rate_limit(user_id: str, action: str) -> bool:
    """Check rate limit. Returns True if allowed, False if exceeded."""
    if not _redis:
        return True  # fail-open if Redis unavailable
    limit, window = _RATE_LIMITS.get(action, (30, 60))
    key = f"{_RATE_LIMIT_PREFIX}{action}:{user_id}"
    try:
        current = _redis.incr(key)
        if current == 1:
            _redis.expire(key, window)
        return current <= limit
    except Exception:
        return True  # fail-open

# Official Dlogic bot identifier (used for follow system)
DLOGIC_OFFICIAL_BOT_ID = "00000000-0000-0000-0000-000000000000"
_RESERVED_UUIDS = {DLOGIC_OFFICIAL_BOT_ID}

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
    if user_id in _RESERVED_UUIDS:
        return jsonify({"error": "この操作は許可されていません"}), 403
    if not _check_rate_limit(user_id, "settings"):
        return jsonify({"error": "リクエストが多すぎます。少し待ってからお試しください。"}), 429

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

    # Prevent impersonation of official bot
    _FORBIDDEN_NAMES = ["dロジ", "dlogic公式", "ディーロジ", "d-logic"]
    bot_name_lower = bot_name.lower()
    if any(fn in bot_name_lower for fn in _FORBIDDEN_NAMES):
        return jsonify({"error": "この名前は使用できません"}), 400

    sb = get_client()

    # Check if settings already exist
    existing = sb.table("mybot_settings").select("*").eq("user_id", user_id).execute()

    row = {
        "bot_name": bot_name,
        "personality": data.get("personality", "friendly"),
        "tone": data.get("tone", "casual"),
        "description": data.get("description", ""),
        "catchphrase": (data.get("catchphrase") or "")[:100],
        "self_introduction": (data.get("self_introduction") or "")[:500],
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
        "chat_theme": data.get("chat_theme", "default"),
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
            "catchphrase": old.get("catchphrase", ""),
            "self_introduction": old.get("self_introduction", ""),
            "icon_url": old.get("icon_url"),
            "prediction_style": old.get("prediction_style", "balanced"),
            "analysis_depth": old.get("analysis_depth", "standard"),
            "bet_suggestion": old.get("bet_suggestion", "basic"),
            "risk_level": old.get("risk_level", "moderate"),
            "analysis_focus": old.get("analysis_focus", "general"),
            "custom_instructions": old.get("custom_instructions", ""),
            "chat_theme": old.get("chat_theme", "default"),
        }
        sb.table("mybot_settings_history").insert({
            "user_id": user_id,
            "snapshot": snapshot,
            "label": data.get("history_label"),
        }).execute()

        # Clear conversation history if personality/tone changed
        _BEHAVIOR_KEYS = ("personality", "tone", "prediction_style", "custom_instructions")
        behavior_changed = any(old.get(k) != row.get(k) for k in _BEHAVIOR_KEYS)
        if behavior_changed:
            try:
                import redis
                r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
                keys = r.keys(f"mybot:history:{user_id}:*")
                if keys:
                    r.delete(*keys)
                    logger.info(f"Cleared {len(keys)} MYBOT sessions for {user_id} (behavior changed)")
            except Exception:
                pass  # Redis unavailable — sessions will expire naturally

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
                "catchphrase": old.get("catchphrase", ""),
                "self_introduction": old.get("self_introduction", ""),
                "icon_url": old.get("icon_url"),
                "prediction_style": old.get("prediction_style", "balanced"),
                "analysis_depth": old.get("analysis_depth", "standard"),
                "bet_suggestion": old.get("bet_suggestion", "basic"),
                "risk_level": old.get("risk_level", "moderate"),
                "analysis_focus": old.get("analysis_focus", "general"),
                "custom_instructions": old.get("custom_instructions", ""),
                "chat_theme": old.get("chat_theme", "default"),
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
        "catchphrase": snapshot.get("catchphrase", ""),
        "self_introduction": snapshot.get("self_introduction", ""),
        "prediction_style": snapshot.get("prediction_style", "balanced"),
        "analysis_depth": snapshot.get("analysis_depth", "standard"),
        "bet_suggestion": snapshot.get("bet_suggestion", "basic"),
        "risk_level": snapshot.get("risk_level", "moderate"),
        "analysis_focus": snapshot.get("analysis_focus", "general"),
        "custom_instructions": snapshot.get("custom_instructions", ""),
        "chat_theme": snapshot.get("chat_theme", "default"),
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
    if not _check_rate_limit(user_id, "upload"):
        return jsonify({"error": "リクエストが多すぎます"}), 429

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
        .select("bot_name, personality, tone, icon_url, description, catchphrase, self_introduction, horse_weight, jockey_weight, item_weights, is_public, user_id, chat_theme, updated_at")
        .eq("user_id", bot_user_id)
        .execute()
    )

    if not result.data:
        return jsonify({"error": "Bot not found"}), 404

    bot = result.data[0]
    if not bot.get("is_public"):
        return jsonify({"error": "This bot is private"}), 403

    # Get owner profile info
    owner = (
        sb.table("user_profiles")
        .select("display_name, icon_url, x_account")
        .eq("id", bot_user_id)
        .limit(1)
        .execute()
    )
    if owner.data:
        bot["owner_name"] = owner.data[0].get("display_name", "")
        bot["owner_icon_url"] = owner.data[0].get("icon_url")
        bot["owner_x_account"] = owner.data[0].get("x_account")

    # Get follower count
    follows = (
        sb.table("mybot_follows")
        .select("id", count="exact")
        .eq("bot_user_id", bot_user_id)
        .execute()
    )
    bot["follower_count"] = follows.count or 0

    return jsonify({"bot": bot})


# ---------------------------------------------------------------------------
# Public BOT listing (みんなのAIBOT)
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/public/list", methods=["GET"])
def list_public_bots():
    """List all public bots for the みんなのAIBOT page."""
    sort = request.args.get("sort", "new")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))

    sb = get_client()

    # Get total count of public bots
    count_result = (
        sb.table("mybot_settings")
        .select("user_id", count="exact")
        .eq("is_public", True)
        .execute()
    )
    total = count_result.count or 0

    # Fetch public bots (always order by updated_at as base)
    bots_result = (
        sb.table("mybot_settings")
        .select("bot_name, catchphrase, self_introduction, icon_url, user_id, chat_theme, updated_at")
        .eq("is_public", True)
        .order("updated_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    bots = [b for b in (bots_result.data or []) if b["user_id"] not in _RESERVED_UUIDS]

    if not bots:
        return jsonify({"bots": [], "total": total})

    # Collect user_ids to batch-fetch owner profiles and follower counts
    user_ids = [b["user_id"] for b in bots]

    # Fetch owner profiles
    profiles_result = (
        sb.table("user_profiles")
        .select("id, display_name, icon_url, x_account")
        .in_("id", user_ids)
        .execute()
    )
    profiles_map = {p["id"]: p for p in (profiles_result.data or [])}

    # Fetch follower counts per bot
    follows_result = (
        sb.table("mybot_follows")
        .select("bot_user_id")
        .in_("bot_user_id", user_ids)
        .execute()
    )
    follower_counts = {}
    for f in (follows_result.data or []):
        bid = f["bot_user_id"]
        follower_counts[bid] = follower_counts.get(bid, 0) + 1

    # Fetch MYBOT stats (recovery rate)
    stats_result = (
        sb.table("mybot_stats")
        .select("bot_user_id, recovery_rate, win_rate, total_predictions")
        .in_("bot_user_id", user_ids)
        .execute()
    )
    stats_map = {s["bot_user_id"]: s for s in (stats_result.data or [])}

    # Fetch LINE channel info (basic_id for friend add URL)
    line_result = (
        sb.table("mybot_line_channels")
        .select("user_id, basic_id")
        .in_("user_id", user_ids)
        .execute()
    )
    line_map = {l["user_id"]: l.get("basic_id", "") for l in (line_result.data or [])}

    # Enrich bot data
    for bot in bots:
        uid = bot["user_id"]
        owner = profiles_map.get(uid, {})
        bot["owner_name"] = owner.get("display_name", "")
        bot["owner_icon_url"] = owner.get("icon_url")
        bot["owner_x_account"] = owner.get("x_account")
        bot["follower_count"] = follower_counts.get(uid, 0)
        stats = stats_map.get(uid, {})
        bot["recovery_rate"] = stats.get("recovery_rate", 0)
        bot["win_rate"] = stats.get("win_rate", 0)
        bot["total_predictions"] = stats.get("total_predictions", 0)
        basic_id = line_map.get(uid, "")
        # basic_id may already include @ prefix
        clean_id = basic_id.lstrip("@") if basic_id else ""
        bot["line_url"] = f"https://line.me/R/ti/p/@{clean_id}" if clean_id else ""

    # Sort
    if sort == "popular":
        bots.sort(key=lambda b: b["follower_count"], reverse=True)
    elif sort == "recovery":
        bots.sort(key=lambda b: (b["total_predictions"] > 0, b["recovery_rate"]), reverse=True)

    # Prepend Dlogic official bot (always at top)
    dlogic_card = _get_dlogic_stats(sb)

    # Dlogic follower count
    dlogic_follows = (
        sb.table("mybot_follows")
        .select("id", count="exact")
        .eq("bot_user_id", DLOGIC_OFFICIAL_BOT_ID)
        .execute()
    )
    dlogic_card["follower_count"] = dlogic_follows.count or 0

    return jsonify({"bots": bots, "total": total, "dlogic": dlogic_card})


def _get_dlogic_stats(sb) -> dict:
    """Compute Dlogic engine recovery rate from engine_hit_rates + race_results."""
    try:
        # Get dlogic engine hit rates (last 30 days)
        from datetime import datetime, timezone, timedelta
        jst = timezone(timedelta(hours=9))
        cutoff = (datetime.now(jst) - timedelta(days=30)).strftime("%Y-%m-%d")

        hits_res = (
            sb.table("engine_hit_rates")
            .select("race_id, hit_win")
            .eq("engine", "dlogic")
            .gte("date", cutoff)
            .execute()
        )
        rows = hits_res.data or []
        if not rows:
            return {
                "recovery_rate": 0, "win_rate": 0,
                "total_predictions": 0, "total_wins": 0,
            }

        total = len(rows)
        win_race_ids = [r["race_id"] for r in rows if r["hit_win"]]
        total_wins = len(win_race_ids)
        win_rate = round(total_wins / total * 100, 1) if total else 0

        # Get payouts for winning races
        total_payout = 0
        if win_race_ids:
            results_res = (
                sb.table("race_results")
                .select("race_id, win_payout")
                .in_("race_id", win_race_ids)
                .execute()
            )
            for r in (results_res.data or []):
                total_payout += r.get("win_payout", 0) or 0

        total_bet = total * 100
        recovery_rate = round(total_payout / total_bet * 100, 1) if total_bet else 0

        return {
            "recovery_rate": recovery_rate,
            "win_rate": win_rate,
            "total_predictions": total,
            "total_wins": total_wins,
        }
    except Exception:
        logger.exception("Failed to compute Dlogic stats")
        return {
            "recovery_rate": 0, "win_rate": 0,
            "total_predictions": 0, "total_wins": 0,
        }


# ---------------------------------------------------------------------------
# Prompt Refinement (AI変換)
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/refine-prompt", methods=["POST"])
def refine_prompt():
    """Convert casual user instructions into an optimized system prompt."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    raw_text = (data.get("text") or "").strip()
    if not raw_text:
        return jsonify({"error": "テキストを入力してください"}), 400
    if len(raw_text) > 500:
        return jsonify({"error": "500文字以内で入力してください"}), 400

    import anthropic
    from config import ANTHROPIC_API_KEY

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": f"""以下はAI競馬予想BOTのオーナーが書いた「カスタム指示」です。
これをAIが理解しやすい明確なシステムプロンプト指示に変換してください。

ルール:
- 日本語で出力
- 箇条書きで簡潔に（3〜5項目）
- 競馬予想BOTへの指示として自然な形に
- 元の意図を忠実に保つ
- 200文字以内

入力: {raw_text}

変換後:""",
            }],
        )
        refined = resp.content[0].text.strip()
        return jsonify({"refined": refined})
    except Exception:
        logger.exception("Prompt refinement failed")
        return jsonify({"error": "変換に失敗しました。もう一度お試しください。"}), 500


# ---------------------------------------------------------------------------
# Follow / Unfollow
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/follow", methods=["POST"])
def follow_bot():
    """Follow a public bot."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    if not _check_rate_limit(user_id, "follow"):
        return jsonify({"error": "リクエストが多すぎます"}), 429

    data = request.get_json(silent=True)
    if not data or not data.get("bot_user_id"):
        return jsonify({"error": "bot_user_id required"}), 400

    bot_user_id = data["bot_user_id"]

    # Cannot follow yourself
    if user_id == bot_user_id:
        return jsonify({"error": "Cannot follow your own bot"}), 400

    sb = get_client()

    # Official Dlogic bot — skip follow (not in user_profiles, FK would fail)
    if bot_user_id == DLOGIC_OFFICIAL_BOT_ID:
        return jsonify({"status": "followed"})

    if bot_user_id != DLOGIC_OFFICIAL_BOT_ID:
        # Verify bot exists and is public
        bot_check = (
            sb.table("mybot_settings")
            .select("is_public")
            .eq("user_id", bot_user_id)
            .limit(1)
            .execute()
        )
        if not bot_check.data:
            return jsonify({"error": "Bot not found"}), 404
        if not bot_check.data[0].get("is_public"):
            return jsonify({"error": "This bot is private"}), 403

    # Insert follow (handle duplicate gracefully)
    try:
        result = sb.table("mybot_follows").upsert(
            {"user_id": user_id, "bot_user_id": bot_user_id},
            on_conflict="user_id,bot_user_id",
        ).execute()
        logger.info(f"User {user_id} followed bot {bot_user_id}, result={result.data}")
    except Exception as e:
        logger.error(f"Follow upsert failed for user={user_id} bot={bot_user_id}: {e}")
        return jsonify({"error": "フォローに失敗しました", "detail": str(e)}), 500

    return jsonify({"status": "followed"})


@bp.route("/api/mybot/follow", methods=["DELETE"])
def unfollow_bot():
    """Unfollow a bot."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    data = request.get_json(silent=True)
    if not data or not data.get("bot_user_id"):
        return jsonify({"error": "bot_user_id required"}), 400

    bot_user_id = data["bot_user_id"]
    sb = get_client()

    sb.table("mybot_follows").delete().eq("user_id", user_id).eq("bot_user_id", bot_user_id).execute()

    logger.info(f"User {user_id} unfollowed bot {bot_user_id}")
    return jsonify({"status": "unfollowed"})


@bp.route("/api/mybot/follows", methods=["GET"])
def get_follows():
    """Get user's followed bots list."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["pid"]
    sb = get_client()

    # Get user's follows
    follows_result = (
        sb.table("mybot_follows")
        .select("bot_user_id, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    follows_data = follows_result.data or []
    if not follows_data:
        return jsonify({"follows": []})

    bot_user_ids = [f["bot_user_id"] for f in follows_data]

    # Fetch bot settings
    bots_result = (
        sb.table("mybot_settings")
        .select("bot_name, icon_url, user_id, chat_theme, catchphrase, self_introduction, is_public")
        .in_("user_id", bot_user_ids)
        .execute()
    )
    bots_map = {b["user_id"]: b for b in (bots_result.data or [])}

    # Fetch owner profiles
    profiles_result = (
        sb.table("user_profiles")
        .select("id, display_name, icon_url, x_account")
        .in_("id", bot_user_ids)
        .execute()
    )
    profiles_map = {p["id"]: p for p in (profiles_result.data or [])}

    # Build response
    follows = []
    for f in follows_data:
        bid = f["bot_user_id"]
        bot = bots_map.get(bid, {})
        owner = profiles_map.get(bid, {})
        follows.append({
            "bot_user_id": bid,
            "bot_name": bot.get("bot_name", ""),
            "icon_url": bot.get("icon_url"),
            "chat_theme": bot.get("chat_theme", "default"),
            "catchphrase": bot.get("catchphrase", ""),
            "self_introduction": bot.get("self_introduction", ""),
            "is_public": bot.get("is_public", False),
            "owner_name": owner.get("display_name", ""),
            "owner_icon_url": owner.get("icon_url"),
            "owner_x_account": owner.get("x_account"),
            "followed_at": f["created_at"],
        })

    return jsonify({"follows": follows})


# ---------------------------------------------------------------------------
# MYBOT Web Inquiry helpers
# ---------------------------------------------------------------------------

def _inquiry_key(user_lid: str, bot_user_id: str) -> str:
    return f"{_INQUIRY_MODE_PREFIX}{user_lid}:{bot_user_id}"


def _is_web_inquiry_mode(user_lid: str, bot_user_id: str) -> bool:
    if not _redis:
        return False
    try:
        return _redis.exists(_inquiry_key(user_lid, bot_user_id)) > 0
    except Exception:
        return False


def _set_web_inquiry_mode(user_lid: str, bot_user_id: str):
    if _redis:
        try:
            _redis.setex(_inquiry_key(user_lid, bot_user_id), _INQUIRY_MODE_TTL, "1")
        except Exception:
            pass


def _clear_web_inquiry_mode(user_lid: str, bot_user_id: str):
    if _redis:
        try:
            _redis.delete(_inquiry_key(user_lid, bot_user_id))
        except Exception:
            pass


def _send_web_inquiry(bot_user_id: str, bot_name: str, sender_name: str, sender_lid: str, content: str):
    """Save inquiry to Supabase and notify admin via Telegram."""
    from datetime import timedelta
    from config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_CHAT_ID

    sb = get_client()
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)

    inquiry_id = None
    try:
        row = {
            "bot_owner_id": bot_user_id,
            "bot_name": bot_name,
            "sender_line_id": sender_lid,
            "sender_name": sender_name,
            "content": content,
            "status": "open",
        }
        res = sb.table("mybot_inquiries").insert(row).execute()
        if res.data:
            inquiry_id = res.data[0]["id"]
    except Exception:
        logger.exception("Failed to save web MYBOT inquiry")

    # Telegram notification
    text = f"📩 [MYBOT問い合わせ (Web)]\n━━━━━━━━━━━━\n"
    if inquiry_id:
        text += f"ID: #{inquiry_id}\n"
    text += (
        f"BOT: {bot_name}\n"
        f"BOTオーナー: {bot_user_id[:8]}...\n"
        f"ユーザー: {sender_name}\n"
        f"内容: {content}\n"
        f"時刻: {now.strftime('%Y-%m-%d %H:%M')} JST\n\n"
        f"/resolve_mybot {inquiry_id} で対応"
    )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        http_requests.post(url, json={
            "chat_id": ADMIN_TELEGRAM_CHAT_ID,
            "text": text,
        }, timeout=10)
        logger.info(f"Web MYBOT inquiry #{inquiry_id} sent to admin Telegram")
    except Exception:
        logger.exception("Failed to send web MYBOT inquiry to Telegram")

    return inquiry_id


def _sse_text_response(text: str, session_id: str = "", quick_replies: list[dict] | None = None):
    """Return SSE response with a simple text message (no agent loop)."""
    if quick_replies is None:
        quick_replies = []

    def generate():
        yield f"data: {json.dumps({'type': 'text', 'content': text}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': quick_replies}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# MYBOT Chat (SSE)
# ---------------------------------------------------------------------------

@bp.route("/api/mybot/chat", methods=["POST"])
def mybot_chat():
    """SSE streaming chat for MYBOT — uses user's IMLogic weights.

    Supports both authenticated and anonymous access:
    - Authenticated: full features including inquiry system
    - Anonymous: public bots only, session_id-based sessions
    """
    payload = verify_auth_header()  # None if not logged in (anonymous OK)

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    message = data.get("message", "").strip()
    query_type = (data.get("query_type") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    # Rate limit
    rate_user = payload["pid"] if payload else request.remote_addr or "anon"
    if not _check_rate_limit(rate_user, "chat"):
        return jsonify({"error": "リクエストが多すぎます。少し待ってからお試しください。"}), 429

    session_id = data.get("session_id", str(uuid.uuid4()))
    bot_user_id = data.get("bot_user_id", "")

    if not bot_user_id:
        if payload:
            bot_user_id = payload["pid"]
        else:
            return jsonify({"error": "bot_user_id is required"}), 400

    # Load bot settings
    sb = get_client()
    bot_result = sb.table("mybot_settings").select("*").eq("user_id", bot_user_id).execute()
    if not bot_result.data:
        return jsonify({"error": "Bot not found. Create your bot first."}), 404

    bot_settings = bot_result.data[0]
    is_owner = payload and payload["pid"] == bot_user_id

    # ── Waitlist gate: BOT owner must be active ──
    try:
        owner_status = get_user_status(bot_user_id)
    except Exception:
        logger.exception(f"Failed to check owner status for bot_user_id={bot_user_id}")
        owner_status = "active"

    if owner_status == "waitlist":
        bot_name = bot_settings.get("bot_name", "MYBOT")
        msg = (
            f"ただいま {bot_name} はウェイトリスト待機中です。\n\n"
            "BOTオーナーのアカウントがアクティベートされ次第、"
            "自動的に稼働を開始します。\nもうしばらくお待ちください！🙏"
        )
        return _sse_text_response(msg, session_id)

    if owner_status == "suspended":
        bot_name = bot_settings.get("bot_name", "MYBOT")
        return _sse_text_response(
            f"{bot_name} は現在ご利用いただけません。\n"
            "詳細はDlogic運営までお問い合わせください。",
            session_id,
        )

    # Anonymous or non-owner must use public bots only
    if not is_owner and not bot_settings.get("is_public"):
        return jsonify({"error": "This bot is private"}), 403

    # Identity: authenticated user or anonymous session
    user_lid = payload["lid"] if payload else f"anon_{session_id}"
    user_name = payload.get("name", "Webユーザー") if payload else "匿名ユーザー"
    bot_name = bot_settings.get("bot_name", "MYBOT")
    auth_key = f"mybot_{user_lid}_{bot_user_id}"

    def _get_or_create_session():
        session = load_session(auth_key)
        if session:
            session["last_active"] = datetime.now(timezone.utc).timestamp()
            return session

        if payload:
            from db.user_manager import get_or_create_user_by_login
            profile = get_or_create_user_by_login(payload["lid"], payload["name"])
        else:
            profile = {"id": f"anon_{session_id}", "display_name": "匿名ユーザー"}

        session = {
            "profile": profile,
            "history": [],
            "active_race_id": None,
            "created_at": datetime.now(timezone.utc).timestamp(),
            "last_active": datetime.now(timezone.utc).timestamp(),
        }
        save_session(auth_key, session)
        return session

    # --- Inquiry mode handling ---
    if _is_web_inquiry_mode(user_lid, bot_user_id):
        _clear_web_inquiry_mode(user_lid, bot_user_id)
        if message in ("キャンセル", "やめる", "戻る"):
            return _sse_text_response("お問い合わせをキャンセルしました。", session_id)
        # Send inquiry
        _send_web_inquiry(bot_user_id, bot_name, user_name, user_lid, message)
        return _sse_text_response(
            f"Dlogic運営本部にお問い合わせを送信しました！\n\n"
            f"内容: {message[:100]}\n\n"
            f"運営から回答がありましたらお知らせします。",
            session_id,
        )

    if message in _INQUIRY_KEYWORDS:
        _set_web_inquiry_mode(user_lid, bot_user_id)
        return _sse_text_response(
            "Dlogic運営本部へお問い合わせですね！\n\n"
            "お問い合わせ内容をメッセージで送ってください。\n"
            "（「キャンセル」で取り消せます）",
            session_id,
        )

    # --- Transfer code handler for MYBOT Web ---
    import re as _re
    _transfer_match = _re.match(r"(?:引き継ぎ|記憶コピー)\s+([A-Za-z0-9]{4,8})", message)
    if _transfer_match and payload:
        input_code = _transfer_match.group(1).strip().upper()
        from db.user_manager import get_or_create_user_by_login as _get_user_link
        from db.user_manager import sync_profiles as _sync_prof
        current_profile = _get_user_link(payload["lid"], payload["name"])
        own_code = current_profile.get("transfer_code", "")

        if own_code and own_code == input_code:
            return _sse_text_response("それはあなた自身のコードです！別のアカウントのコードを入力してください。", session_id)

        sb = get_client()
        try:
            res = sb.table("user_profiles").select("*").eq("transfer_code", input_code).limit(1).execute()
        except Exception:
            return _sse_text_response("エラーが発生しました。もう一度試してください。", session_id)

        if not res.data:
            return _sse_text_response("そのコードは見つかりませんでした。もう一度確認してください。", session_id)

        source = res.data[0]
        # Bidirectional sync: copy memories/stats between both profiles
        try:
            synced = _sync_prof(current_profile["id"], source["id"])
        except Exception:
            synced = False

        if synced:
            # Refresh session profile to pick up synced fields
            try:
                refreshed = sb.table("user_profiles").select("*").eq("id", current_profile["id"]).limit(1).execute()
                if refreshed.data:
                    session = load_session(auth_key)
                    if session:
                        session["profile"] = refreshed.data[0]
                        save_session(auth_key, session)
            except Exception:
                pass
            return _sse_text_response("🎉 アカウント連携完了！データが統合されました。", session_id)
        else:
            return _sse_text_response("連携でエラーが発生しました。もう一度試してください。", session_id)

    # Auto-resolve explicit race hints (venue + R, race_id)
    resolved_race = resolve_race_id_from_text(message)
    if resolved_race:
        session = load_session(auth_key)
        if session:
            session["active_race_id"] = resolved_race
            save_session(auth_key, session)

    session = load_session(auth_key)
    if session and not session.get("active_race_id") and _is_opinion_query(message):
        restored_race = find_race_id(session.get("history", []))
        if restored_race:
            session["active_race_id"] = restored_race
            save_session(auth_key, session)
        else:
            return _sse_text_response(
                "どのレースの話だ？\n\n例: 中山11R / 阪神10レース / 20260319-中山-11",
                session_id,
            )

    if session and not session.get("active_race_id") and _needs_race_prompt(message):
        return _sse_text_response(
            "どのレースの話だ？\n\n例: 中山11R / 阪神10レース / 20260319-中山-11",
            session_id,
        )

    # --- Honmei (本命) selection handler for Web ---
    if message.startswith("本命 ") or message.startswith("本命:"):
        import re as _re
        match = _re.match(r"本命[:\s]+(\d+)番?\s*(.*)", message)
        if match and payload:
            from db.prediction_manager import record_prediction as _rec_pred
            from db.user_manager import get_or_create_user_by_login as _get_user
            horse_number = int(match.group(1))
            horse_name = match.group(2).strip() or f"{horse_number}番"

            profile = _get_user(payload["lid"], payload["name"])
            # Find race_id from session
            race_id = None
            session = load_session(auth_key)
            if session:
                race_id = session.get("pending_honmei_race") or session.get("active_race_id")

            if race_id and not profile.get("fallback"):
                venue = ""
                try:
                    from tools.executor import _race_cache
                    if race_id in _race_cache and "entries" in _race_cache[race_id]:
                        venue = _race_cache[race_id]["entries"].get("venue", "")
                    _rec_pred(
                        user_profile_id=profile["id"],
                        race_id=race_id,
                        horse_number=horse_number,
                        horse_name=horse_name,
                        race_name="",
                        venue=venue,
                    )
                    session = load_session(auth_key)
                    if session:
                        session.pop("pending_honmei_race", None)
                        save_session(auth_key, session)
                    return _sse_text_response(
                        f"👊 {horse_number}番 {horse_name} を本命で登録したぜ！\n\n"
                        "みんなの予想に追加したからな。結果出たら回収率も計算してやるよ。",
                        session_id,
                        quick_replies=get_mybot_web_quick_replies(["get_predictions"]),
                    )
                except Exception:
                    logger.exception("Failed to record MYBOT web honmei")
                    return _sse_text_response("ごめん、登録でエラーが出ちゃった。もう一回試してくれ！", session_id)
            else:
                return _sse_text_response("レースを先に見てから本命を選んでくれ！", session_id)

    # --- Honmei blocking: pending pick ---
    session = load_session(auth_key)
    if session:
        profile_id = session.get("profile", {}).get("id", "")
        if profile_id and not profile_id.startswith("anon_"):
            if _has_pending_honmei(session, profile_id) and not _is_same_race_query(message):
                pending_race = session.get("pending_honmei_race") or session.get("active_race_id")
                honmei_items = _build_honmei_quick_replies(pending_race) if pending_race else []
                if honmei_items:
                    save_session(auth_key, session)
                    return _sse_text_response(
                        "おっと、ちょっと待ってくれ！\n\n"
                        "「みんなの予想」を集計してるんだ。\n"
                        "本命を登録してくれたら次に進めるぜ！\n\n"
                        "👇 下のボタンから本命をタップ！",
                        session_id,
                        honmei_items,
                    )

    # --- Fast path: query_type provided (skip LLM where possible) ---
    route = _route_from_query_type(query_type)
    if route:
        from agent.template_router import route_and_respond, _build_history_entries
        from agent.mybot_chat import _execute_imlogic_prediction, format_imlogic_predictions, _format_mybot_footer
        from agent.response_cache import find_race_id
        from agent.engine import trim_history

        session = _get_or_create_session()
        history = trim_history(session["history"])
        profile = session["profile"]

        route_name, route_params = route
        if route_name == "predictions":
            race_id = find_race_id(history) or session.get("active_race_id")
            if race_id:
                result_str = _execute_imlogic_prediction(race_id, bot_settings, context={"user_profile_id": profile.get("id", "")})
                data = json.loads(result_str)
                text = format_imlogic_predictions(data)
                tools_used = ["get_predictions"]
                footer = _format_mybot_footer(tools_used, bot_settings)
                full_text = text + ("\n\n" + footer if footer else "")

                history.append({"role": "user", "content": message})
                history.extend(_build_history_entries(
                    tool_name="get_predictions",
                    tool_input={"race_id": race_id},
                    tool_result=result_str,
                    final_text=text,
                ))
                session["history"] = history
                session["active_race_id"] = race_id

                # Honmei prompt after predictions (fast path)
                honmei_qr = None
                profile_id = profile.get("id", "")
                if profile_id and not profile_id.startswith("anon_"):
                    try:
                        from db.prediction_manager import check_prediction as _check_pred
                        already_picked = _check_pred(profile_id, race_id)
                    except Exception:
                        already_picked = True
                    if not already_picked and _should_prompt_honmei(race_id):
                        session["pending_honmei_race"] = race_id
                        honmei_qr = _build_honmei_quick_replies(race_id)
                        if honmei_qr:
                            full_text += (
                                "\n\n━━━━━━━━\n"
                                "📢 みんなの予想\n"
                                "━━━━━━━━\n\n"
                                "お前の本命を教えてくれ！👇"
                            )

                save_session(auth_key, session)
                return _sse_text_response(full_text, session_id,
                                          quick_replies=honmei_qr or get_mybot_web_quick_replies(tools_used))
        else:
            history.append({"role": "user", "content": message})
            result = route_and_respond(
                route_name,
                route_params,
                profile.get("id", ""),
                history,
                profile,
                active_race_id_hint=session.get("active_race_id"),
            )
            if result:
                for entry in result.get("history_entries", []):
                    history.append(entry)

                full_text = result["text"]
                footer = _format_mybot_footer(result["tools_used"], bot_settings)
                if footer:
                    full_text += "\n\n" + footer

                if result.get("active_race_id"):
                    session["active_race_id"] = result["active_race_id"]
                session["history"] = history
                save_session(auth_key, session)
                return _sse_text_response(full_text, session_id,
                                          quick_replies=get_mybot_web_quick_replies(result["tools_used"]))
            else:
                history.pop()

    from agent.engine import TOOL_LABELS, trim_history
    from agent.mybot_chat import run_mybot_agent

    # Session management (similar to web_chat)
    from api.web_chat import _cleanup_old_sessions

    _cleanup_old_sessions()
    session = _get_or_create_session()

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
                    # MYBOT uses IMLogic, not the 4-engine label
                    if tool_name == "get_predictions":
                        label = f"IMLogicエンジン ({bot_name})"
                    yield f"data: {json.dumps({'type': 'tool', 'name': tool_name, 'label': label}, ensure_ascii=False)}\n\n"

                elif chunk_type == "done":
                    session["history"] = chunk.get("history", history)
                    if chunk.get("active_race_id"):
                        session["active_race_id"] = chunk["active_race_id"]

                    full_text = chunk["text"]
                    quick_replies = chunk.get("quick_replies", [])
                    tools_used = chunk.get("tools_used", [])
                    active_race_id = chunk.get("active_race_id")

                    # Honmei (みんなの予想) for Web
                    used_set = set(tools_used)
                    if used_set & {"get_predictions"} and active_race_id:
                        profile_id = profile.get("id", "")
                        if not profile_id.startswith("anon_"):
                            try:
                                from db.prediction_manager import check_prediction as _check_pred
                                already_picked = _check_pred(profile_id, active_race_id)
                            except Exception:
                                already_picked = True
                            if not already_picked and _should_prompt_honmei(active_race_id):
                                session["pending_honmei_race"] = active_race_id
                                # Build honmei quick replies from race cache
                                from tools.executor import _race_cache
                                if active_race_id in _race_cache and "entries" in _race_cache[active_race_id]:
                                    entries = _race_cache[active_race_id]["entries"]
                                    horses = entries.get("horses", [])
                                    horse_numbers = entries.get("horse_numbers", [])
                                    if horses and horse_numbers:
                                        honmei_items = []
                                        for i in range(min(len(horses), len(horse_numbers), 18)):
                                            num = horse_numbers[i]
                                            name = horses[i]
                                            honmei_items.append({
                                                "label": f"{num}.{name}"[:20],
                                                "text": f"本命 {num}番 {name}",
                                            })
                                        if honmei_items:
                                            full_text += (
                                                "\n\n━━━━━━━━\n"
                                                "📢 みんなの予想\n"
                                                "━━━━━━━━\n\n"
                                                "お前の本命を教えてくれ！👇"
                                            )
                                            quick_replies = honmei_items

                    save_session(auth_key, session)
                    yield f"data: {json.dumps({'type': 'text', 'content': full_text}, ensure_ascii=False)}\n\n"
                    done_data = {
                        "type": "done",
                        "session_id": session_id,
                        "quick_replies": quick_replies,
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
        json={"endpoint": webhook_url, "active": True},
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
        "basic_id": bot_info.get("basicId", ""),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }
    sb.table("mybot_line_channels").upsert(row, on_conflict="user_id").execute()

    logger.info(f"LINE channel connected for user {user_id} (channel_id={channel_id})")

    # Auto-set rich menu (non-blocking, best-effort)
    try:
        from scripts.setup_mybot_richmenu import setup_mybot_richmenu
        # Fetch owner's x_account for rich menu
        _owner = sb.table("user_profiles").select("x_account").eq("id", user_id).execute()
        _x_account = _owner.data[0].get("x_account") if _owner.data else None
        rm_id = setup_mybot_richmenu(access_token, x_account=_x_account)
        if rm_id:
            logger.info(f"MYBOT rich menu set for user {user_id}: {rm_id}")
        else:
            logger.warning(f"MYBOT rich menu setup failed for user {user_id}")
    except Exception:
        logger.exception(f"MYBOT rich menu setup error for user {user_id}")

    # Check webhook active status
    webhook_active = True
    try:
        wr = http_requests.get(
            "https://api.line.me/v2/bot/channel/webhook/endpoint",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        )
        if wr.status_code == 200:
            webhook_active = wr.json().get("active", True)
    except Exception:
        pass

    return jsonify({
        "status": "connected",
        "bot_name": bot_info.get("displayName"),
        "bot_picture_url": bot_info.get("pictureUrl"),
        "webhook_url": webhook_url,
        "webhook_active": webhook_active,
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

    # Check webhook active status from LINE API
    webhook_active = True  # default optimistic
    try:
        from bot.mybot_line_handler import decrypt_value
        access_token_enc = (
            sb.table("mybot_line_channels")
            .select("access_token_enc")
            .eq("user_id", user_id)
            .execute()
        ).data[0]["access_token_enc"]
        token = decrypt_value(access_token_enc)
        wr = http_requests.get(
            "https://api.line.me/v2/bot/channel/webhook/endpoint",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if wr.status_code == 200:
            webhook_active = wr.json().get("active", True)
    except Exception:
        pass  # fail-open

    return jsonify({
        "connected": True,
        "channel_id": masked_id,
        "webhook_url": ch["webhook_url"],
        "webhook_active": webhook_active,
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
