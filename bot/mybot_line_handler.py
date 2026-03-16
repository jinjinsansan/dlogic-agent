"""MYBOT LINE webhook handler — per-user custom bot via LINE."""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime

from flask import request

import re

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction,
)

from agent.mybot_chat import run_mybot_agent
from agent.engine import format_tool_notification
from agent.response_cache import find_race_id
from config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_CHAT_ID
from db.supabase_client import get_client
from db.encryption import decrypt_value
from db.redis_client import get_redis
from db.user_manager import get_user_status, get_or_create_user as db_get_or_create_user
from db.prediction_manager import (
    record_prediction as db_record_prediction,
    check_prediction as db_check_prediction,
)

logger = logging.getLogger(__name__)

_redis = get_redis()
_HISTORY_TTL = 3 * 3600  # 3 hours
_HISTORY_MAX = 20
_TOOL_NOTICE_DELAY = 5

# Inquiry mode key prefix
_INQUIRY_MODE_PREFIX = "mybot:inquiry_mode:"
_INQUIRY_MODE_TTL = 300  # 5 minutes

# Active race tracking (for honmei selection)
_ACTIVE_RACE_PREFIX = "mybot:active_race:"
_ACTIVE_RACE_TTL = 3600  # 1 hour

# Profile cache (in-memory, per session)
_profile_cache: dict[str, dict] = {}


def _set_active_race(user_id: str, sender_id: str, race_id: str):
    if _redis:
        try:
            _redis.setex(f"{_ACTIVE_RACE_PREFIX}{user_id}:{sender_id}", _ACTIVE_RACE_TTL, race_id)
        except Exception:
            pass


def _get_active_race(user_id: str, sender_id: str) -> str | None:
    if _redis:
        try:
            val = _redis.get(f"{_ACTIVE_RACE_PREFIX}{user_id}:{sender_id}")
            return val.decode() if val else None
        except Exception:
            pass
    return None


def _clear_active_race(user_id: str, sender_id: str):
    if _redis:
        try:
            _redis.delete(f"{_ACTIVE_RACE_PREFIX}{user_id}:{sender_id}")
        except Exception:
            pass


def _has_pending_honmei(user_id: str, sender_id: str, profile_id: str) -> bool:
    """Check if user has a pending honmei pick."""
    race_id = _get_active_race(user_id, sender_id)
    if not race_id:
        return False
    try:
        existing = db_check_prediction(profile_id, race_id)
        return existing is None
    except Exception:
        return False


def get_mybot_quick_reply(tools_used: list[str]) -> QuickReply | None:
    """Get context-appropriate quick reply buttons for MYBOT (engine-independent tools only)."""
    used_set = set(tools_used)

    # Tools that are post-analysis (already got predictions/odds/etc)
    post_prediction_tools = {
        "get_odds_probability", "get_realtime_odds", "get_horse_weights",
        "get_stable_comments", "get_training_comments",
    }

    items = []

    if used_set & post_prediction_tools:
        # After analysis — show remaining engine-independent tools
        if "get_odds_probability" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="📊 予測勝率", text="予測勝率見せて")))
        if "get_realtime_odds" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="💰 オッズ", text="オッズ見せて")))
        if "get_horse_weights" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="⚖️ 馬体重", text="馬体重は？")))
        if "get_stable_comments" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="🗣️ 関係者情報", text="関係者情報は？")))
        if "get_training_comments" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="📝 調教評価", text="調教評価は？")))
        items.append(QuickReplyItem(action=MessageAction(label="💬 どう思う？", text="お前はどう思う？")))

    elif "get_predictions" in used_set:
        # After IMLogic prediction — deep dive options
        items = [
            QuickReplyItem(action=MessageAction(label="📊 予測勝率", text="予測勝率見せて")),
            QuickReplyItem(action=MessageAction(label="💰 オッズ", text="オッズ見せて")),
            QuickReplyItem(action=MessageAction(label="⚖️ 馬体重", text="馬体重は？")),
            QuickReplyItem(action=MessageAction(label="🗣️ 関係者情報", text="関係者情報は？")),
            QuickReplyItem(action=MessageAction(label="📝 調教評価", text="調教評価は？")),
            QuickReplyItem(action=MessageAction(label="💬 どう思う？", text="お前はどう思う？")),
        ]

    elif "get_race_entries" in used_set:
        # After entry list — prediction + info tools
        items = [
            QuickReplyItem(action=MessageAction(label="🎯 予想して", text="予想して")),
            QuickReplyItem(action=MessageAction(label="📊 予測勝率", text="予測勝率見せて")),
            QuickReplyItem(action=MessageAction(label="💰 オッズ", text="オッズ見せて")),
            QuickReplyItem(action=MessageAction(label="⚖️ 馬体重", text="馬体重は？")),
            QuickReplyItem(action=MessageAction(label="🗣️ 関係者情報", text="関係者情報は？")),
        ]

    elif "get_today_races" in used_set:
        # After race list — offer main race
        items = [
            QuickReplyItem(action=MessageAction(label="🏇 メインレース", text="メインレースの出馬表見せて")),
        ]

    if items:
        return QuickReply(items=items)
    return None


def get_honmei_quick_reply(race_id: str) -> QuickReply | None:
    """Generate Quick Reply buttons for honmei selection."""
    from tools.executor import _race_cache, execute_tool

    if race_id not in _race_cache or "entries" not in _race_cache[race_id]:
        try:
            execute_tool("get_race_entries", {"race_id": race_id})
        except Exception:
            logger.exception(f"Failed to populate entries for honmei: {race_id}")

    if race_id not in _race_cache or "entries" not in _race_cache[race_id]:
        return None

    entries = _race_cache[race_id]["entries"]
    horses = entries.get("horses", [])
    horse_numbers = entries.get("horse_numbers", [])
    if not horses or not horse_numbers:
        return None

    items = []
    for i in range(min(len(horses), len(horse_numbers))):
        num = horse_numbers[i]
        name = horses[i]
        label = f"{num}.{name}"
        if len(label) > 20:
            label = f"{num}.{name[:17]}"
        items.append(QuickReplyItem(
            action=MessageAction(label=label, text=f"本命 {num}番 {name}")
        ))
        if len(items) >= 13:
            break

    return QuickReply(items=items) if items else None


# Honmei blocking: keywords
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


def _is_same_race_query(text: str) -> bool:
    return any(kw in text for kw in _SAME_RACE_KEYWORDS)


def _get_mybot_profile(user_id: str, sender_id: str, access_token: str) -> dict:
    """Get or create a Supabase user profile for a MYBOT LINE user."""
    cache_key = f"{user_id}:{sender_id}"
    if cache_key in _profile_cache:
        return _profile_cache[cache_key]

    display_name = _get_sender_name(access_token, sender_id)
    try:
        profile = db_get_or_create_user(sender_id, display_name)
    except Exception:
        logger.exception(f"Failed to get/create profile for MYBOT user {sender_id}")
        profile = {"id": f"mybot_{user_id}_{sender_id}", "display_name": display_name, "fallback": True}

    _profile_cache[cache_key] = profile
    return profile


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    """Verify X-Line-Signature using per-channel secret."""
    mac = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    )
    expected = base64.b64encode(mac.digest()).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Redis conversation history
# ---------------------------------------------------------------------------

def _redis_key(user_id: str, sender_id: str) -> str:
    return f"mybot:history:{user_id}:{sender_id}"


def _load_history(user_id: str, sender_id: str) -> list[dict]:
    if _redis:
        try:
            raw = _redis.get(_redis_key(user_id, sender_id))
            if raw:
                history = json.loads(raw)
                # Guard: discard history containing Anthropic-format tool_result
                # blocks that are incompatible with OpenAI API
                for msg in history:
                    content = msg.get("content")
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_result":
                                logger.info("Discarding old Anthropic-format MYBOT history")
                                return []
                return history
        except Exception:
            logger.exception("Failed to load MYBOT history from Redis")
    return []


def _save_history(user_id: str, sender_id: str, history: list[dict]) -> None:
    # Normalize content blocks
    normalized = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            content = [_normalize_block(b) for b in content]
        normalized.append({"role": role, "content": content})

    # Trim to last N messages
    if len(normalized) > _HISTORY_MAX:
        normalized = normalized[-_HISTORY_MAX:]

    if _redis:
        try:
            _redis.setex(
                _redis_key(user_id, sender_id),
                _HISTORY_TTL,
                json.dumps(normalized, ensure_ascii=False),
            )
        except Exception:
            logger.exception("Failed to save MYBOT history to Redis")


def _normalize_block(block):
    if isinstance(block, dict):
        return block
    if hasattr(block, "type"):
        if block.type == "text":
            return {"type": "text", "text": block.text}
        if block.type == "tool_use":
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        if block.type == "tool_result":
            return {
                "type": "tool_result",
                "tool_use_id": getattr(block, "tool_use_id", ""),
                "content": getattr(block, "content", ""),
            }
    if isinstance(block, str):
        return {"type": "text", "text": block}
    return {"type": "text", "text": str(block)}


# ---------------------------------------------------------------------------
# LINE messaging helpers (per-channel access_token)
# ---------------------------------------------------------------------------

def _send_with_retry(send_fn, request_obj, retries: int = 1) -> bool:
    for attempt in range(retries + 1):
        try:
            send_fn(request_obj)
            return True
        except Exception:
            if attempt < retries:
                time.sleep(1)
                continue
            logger.exception("MYBOT LINE API send failed")
            return False


def _reply(access_token: str, reply_token: str, text: str, quick_reply: QuickReply = None):
    """Send a reply message using the channel's own access_token."""
    config = Configuration(access_token=access_token)
    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        messages = []
        if len(text) > 4500:
            chunks = [text[i:i + 4500] for i in range(0, len(text), 4500)]
            for i, chunk in enumerate(chunks):
                msg = TextMessage(text=chunk)
                if quick_reply and i == len(chunks) - 1:
                    msg.quick_reply = quick_reply
                messages.append(msg)
        else:
            msg = TextMessage(text=text)
            if quick_reply:
                msg.quick_reply = quick_reply
            messages.append(msg)

        req = ReplyMessageRequest(
            reply_token=reply_token,
            messages=messages[:5],
        )
        _send_with_retry(api.reply_message, req)


def _push(access_token: str, sender_id: str, text: str, quick_reply: QuickReply = None):
    """Send a push message using the channel's own access_token."""
    config = Configuration(access_token=access_token)
    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        messages = []
        if len(text) > 4500:
            chunks = [text[i:i + 4500] for i in range(0, len(text), 4500)]
            for chunk in chunks:
                messages.append(TextMessage(text=chunk))
        else:
            messages.append(TextMessage(text=text))

        if quick_reply:
            messages[-1].quick_reply = quick_reply

        req = PushMessageRequest(
            to=sender_id,
            messages=messages[:5],
        )
        _send_with_retry(api.push_message, req)


# ---------------------------------------------------------------------------
# MYBOT tool notification (IMLogic label override)
# ---------------------------------------------------------------------------

def _format_mybot_tool_notification(tool_names: list[str], bot_name: str) -> str:
    """Like format_tool_notification but replaces get_predictions label with IMLogic."""
    from agent.engine import TOOL_LABELS, HEAVY_TOOLS

    labels = []
    for name in tool_names:
        if name == "get_predictions":
            labels.append(f"IMLogicエンジン ({bot_name})")
        else:
            labels.append(TOOL_LABELS.get(name, name))

    has_heavy = any(name in HEAVY_TOOLS for name in tool_names)

    if has_heavy:
        msg = "⚡ エンジン起動中...\n"
        msg += "\n".join(f"  → {l}" for l in labels)
        msg += "\n少し待ってな（10〜30秒くらい）"
    else:
        msg = "🔍 データ取得中...\n"
        msg += "\n".join(f"  → {l}" for l in labels)

    return msg


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

def _process_message(
    user_id: str,
    sender_id: str,
    user_text: str,
    access_token: str,
    bot_settings: dict,
    profile: dict,
):
    """Run MYBOT agent loop in a background thread and push the result."""
    try:
        history = _load_history(user_id, sender_id)
        _bot_name = bot_settings.get("bot_name", "MYBOT")

        notified_tools: set[str] = set()
        pending_notice_tools: list[str] = []
        pending_notice_timer: threading.Timer | None = None
        notice_lock = threading.Lock()

        for chunk in run_mybot_agent(
            user_message=user_text,
            history=history,
            profile=profile,
            bot_settings=bot_settings,
            active_race_id_hint=_get_active_race(user_id, sender_id),
        ):
            chunk_type = chunk.get("type")

            if chunk_type == "tool":
                tool_name = chunk.get("name", "")
                if tool_name and tool_name not in notified_tools:
                    notified_tools.add(tool_name)
                    with notice_lock:
                        pending_notice_tools.append(tool_name)

                    if pending_notice_timer is None:
                        def _send_delayed_notice():
                            with notice_lock:
                                tools = list(dict.fromkeys(pending_notice_tools))
                            if not tools:
                                return
                            try:
                                notice = _format_mybot_tool_notification(tools, _bot_name)
                                _push(access_token, sender_id, notice)
                            except Exception:
                                logger.exception("Failed to send MYBOT tool notification")

                        pending_notice_timer = threading.Timer(
                            _TOOL_NOTICE_DELAY, _send_delayed_notice
                        )
                        pending_notice_timer.daemon = True
                        pending_notice_timer.start()

            elif chunk_type == "done":
                if pending_notice_timer and pending_notice_timer.is_alive():
                    pending_notice_timer.cancel()

                full_text = chunk["text"]
                tools_used = chunk.get("tools_used", [])
                active_race_id = chunk.get("active_race_id")
                updated_history = chunk.get("history", history)
                _save_history(user_id, sender_id, updated_history)

                # Always save active_race_id so next message has context
                if active_race_id:
                    _set_active_race(user_id, sender_id, active_race_id)

                # Honmei (みんなの予想) integration
                qr = None
                used_set = set(tools_used)
                if used_set & {"get_race_entries", "get_predictions"} and active_race_id:
                    if profile.get("fallback"):
                        already_picked = True
                    else:
                        try:
                            already_picked = db_check_prediction(profile["id"], active_race_id)
                        except Exception:
                            already_picked = True
                    if not already_picked:
                        honmei_qr = get_honmei_quick_reply(active_race_id)
                        if honmei_qr:
                            full_text += (
                                "\n\n━━━━━━━━\n"
                                "📢 みんなの予想\n"
                                "━━━━━━━━\n\n"
                                "お前の本命を教えてくれ！👇"
                            )
                            qr = honmei_qr

                # Context quick replies (if no honmei QR)
                if not qr:
                    qr = get_mybot_quick_reply(tools_used)

                _push(access_token, sender_id, full_text, quick_reply=qr)

    except Exception:
        logger.exception(f"Error in MYBOT background processing user_id={user_id}")
        try:
            _push(access_token, sender_id, "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？")
        except Exception:
            logger.exception("Failed to send MYBOT error message")


# ---------------------------------------------------------------------------
# Inquiry mode helpers
# ---------------------------------------------------------------------------

def _get_inquiry_mode_key(user_id: str, sender_id: str) -> str:
    return f"{_INQUIRY_MODE_PREFIX}{user_id}:{sender_id}"


def _is_inquiry_mode(user_id: str, sender_id: str) -> bool:
    if not _redis:
        return False
    try:
        return _redis.exists(_get_inquiry_mode_key(user_id, sender_id)) > 0
    except Exception:
        return False


def _set_inquiry_mode(user_id: str, sender_id: str):
    if _redis:
        try:
            _redis.setex(_get_inquiry_mode_key(user_id, sender_id), _INQUIRY_MODE_TTL, "1")
        except Exception:
            pass


def _clear_inquiry_mode(user_id: str, sender_id: str):
    if _redis:
        try:
            _redis.delete(_get_inquiry_mode_key(user_id, sender_id))
        except Exception:
            pass


def _send_mybot_inquiry(
    user_id: str,
    sender_id: str,
    sender_name: str,
    bot_name: str,
    content: str,
    access_token: str,
):
    """Save MYBOT inquiry to Supabase and notify admin via Telegram."""
    import requests as http_req
    from datetime import timezone, timedelta
    jst = timezone(timedelta(hours=9))

    sb = get_client()
    now = datetime.now(jst)

    # Save to mybot_inquiries table
    inquiry_id = None
    try:
        row = {
            "bot_owner_id": user_id,
            "bot_name": bot_name,
            "sender_line_id": sender_id,
            "sender_name": sender_name,
            "content": content,
            "status": "open",
        }
        res = sb.table("mybot_inquiries").insert(row).execute()
        if res.data:
            inquiry_id = res.data[0]["id"]
    except Exception:
        logger.exception("Failed to save MYBOT inquiry")

    # Telegram notification
    text = (
        f"📩 [MYBOT問い合わせ]\n"
        f"━━━━━━━━━━━━\n"
    )
    if inquiry_id:
        text += f"ID: #{inquiry_id}\n"
    text += (
        f"BOT: {bot_name}\n"
        f"BOTオーナー: {user_id[:8]}...\n"
        f"ユーザー: {sender_name}\n"
        f"内容: {content}\n"
        f"時刻: {now.strftime('%Y-%m-%d %H:%M')} JST\n\n"
        f"/resolve_mybot {inquiry_id} で対応"
    )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        http_req.post(url, json={
            "chat_id": ADMIN_TELEGRAM_CHAT_ID,
            "text": text,
        }, timeout=10)
        logger.info(f"MYBOT inquiry #{inquiry_id} sent to admin Telegram")
    except Exception:
        logger.exception("Failed to send MYBOT inquiry to Telegram")

    # Confirm to user
    _push(access_token, sender_id,
          f"Dlogic運営本部にお問い合わせを送信しました！\n\n"
          f"内容: {content[:100]}\n\n"
          f"運営から回答がありましたらこちらでお知らせします。")


def _get_sender_name(access_token: str, sender_id: str) -> str:
    """Get LINE user display name via Messaging API."""
    import requests as http_req
    try:
        resp = http_req.get(
            f"https://api.line.me/v2/bot/profile/{sender_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("displayName", "不明")
    except Exception:
        pass
    return "不明"


# ---------------------------------------------------------------------------
# Webhook entry point
# ---------------------------------------------------------------------------

def handle_mybot_webhook(user_id: str):
    """Handle incoming LINE webhook for a MYBOT channel.

    Called from the Flask route with the bot owner's user_id.
    Returns a tuple of (response_body, status_code).
    """
    body = request.get_data(as_text=False)
    signature = request.headers.get("X-Line-Signature", "")

    if not signature:
        return "Missing signature", 400

    # Load channel credentials from Supabase
    supabase = get_client()
    try:
        ch_resp = (
            supabase.table("mybot_line_channels")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        channel = ch_resp.data
    except Exception:
        logger.exception(f"Failed to load MYBOT LINE channel for user_id={user_id}")
        return "Channel not found", 404

    if not channel:
        return "Channel not found", 404

    channel_secret = decrypt_value(channel["channel_secret_enc"])
    access_token = decrypt_value(channel["access_token_enc"])

    # Verify signature
    if not _verify_signature(channel_secret, body, signature):
        logger.warning(f"Invalid signature for MYBOT user_id={user_id}")
        return "Invalid signature", 403

    # Parse events
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return "Invalid JSON", 400

    events = payload.get("events", [])

    # Load bot settings
    try:
        settings_resp = (
            supabase.table("mybot_settings")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        bot_settings = settings_resp.data or {}
    except Exception:
        logger.exception(f"Failed to load MYBOT settings for user_id={user_id}")
        bot_settings = {}

    bot_name = bot_settings.get("bot_name", "MYBOT")

    # ── Waitlist gate: BOT owner must be active ──
    try:
        owner_status = get_user_status(user_id)
    except Exception:
        logger.exception(f"Failed to check owner status for user_id={user_id}")
        owner_status = "active"  # fail-open to avoid blocking on DB errors

    if owner_status == "waitlist":
        # Reply to the first event with a waitlist message
        for ev in events:
            rt = ev.get("replyToken", "")
            if rt:
                _reply(
                    access_token, rt,
                    f"ただいま {bot_name} はウェイトリスト待機中です。\n\n"
                    "BOTオーナーのアカウントがアクティベートされ次第、"
                    "自動的に稼働を開始します。\n"
                    "もうしばらくお待ちください！🙏",
                )
                break
        return "OK", 200

    if owner_status == "suspended":
        for ev in events:
            rt = ev.get("replyToken", "")
            if rt:
                _reply(
                    access_token, rt,
                    f"{bot_name} は現在ご利用いただけません。\n"
                    "詳細はDlogic運営までお問い合わせください。",
                )
                break
        return "OK", 200

    for event in events:
        event_type = event.get("type")

        if event_type == "message":
            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            sender_id = event.get("source", {}).get("userId", "")
            reply_token = event.get("replyToken", "")
            user_text = message.get("text", "").strip()

            if not sender_id or not user_text:
                continue

            # --- Inquiry mode: user is composing an inquiry ---
            if _is_inquiry_mode(user_id, sender_id):
                _clear_inquiry_mode(user_id, sender_id)

                if user_text in ("キャンセル", "やめる", "cancel"):
                    _reply(access_token, reply_token, "お問い合わせをキャンセルしました。")
                    continue

                # Send inquiry
                sender_name = _get_sender_name(access_token, sender_id)
                _reply(access_token, reply_token, "お問い合わせを送信中...")
                _send_mybot_inquiry(
                    user_id, sender_id, sender_name,
                    bot_name, user_text, access_token,
                )
                continue

            # --- Rich menu keyword: inquiry ---
            if user_text in ("Dlogic運営に問い合わせ", "問い合わせしたい", "お問い合わせ"):
                _set_inquiry_mode(user_id, sender_id)
                _reply(
                    access_token, reply_token,
                    "Dlogic運営本部へお問い合わせですね！\n\n"
                    "お問い合わせ内容をメッセージで送ってください。\n"
                    "（キャンセルする場合は「キャンセル」と送信）"
                )
                continue

            # --- Get user profile from Supabase ---
            profile = _get_mybot_profile(user_id, sender_id, access_token)

            # --- Transfer code display ---
            if user_text in ("引き継ぎコード", "引継ぎコード", "連携コード", "アカウント連携", "記憶コピー", "記憶コピーコード"):
                if profile.get("fallback"):
                    _reply(access_token, reply_token, "今ちょっと不安定みたいだ。少し時間おいてくれ！")
                    continue
                code = profile.get("transfer_code", "")
                if not code:
                    from db.user_manager import get_transfer_code as _get_code
                    try:
                        code = _get_code(profile["id"])
                    except Exception:
                        pass
                if code:
                    _reply(access_token, reply_token,
                           f"お前の記憶コピーコードはこれだ👇\n\n"
                           f"🔑 記憶コピー {code}\n\n"
                           "他のBOTにこのコードを送ると、\n"
                           "ここでの記憶や成績がコピーされるぜ！\n\n"
                           "逆に他のBOTのコードをここで送れば、\n"
                           "そっちの記憶をこっちにコピーできるぞ！")
                else:
                    _reply(access_token, reply_token, "コードが取得できなかった。もう一回試してくれ！")
                continue

            # --- Transfer code input: 「引き継ぎ XXXXXX」or「記憶コピー XXXXXX」 ---
            transfer_match = re.match(r"(?:引き継ぎ|記憶コピー)\s+([A-Za-z0-9]{4,8})", user_text)
            if transfer_match:
                input_code = transfer_match.group(1).strip().upper()
                if profile.get("fallback"):
                    _reply(access_token, reply_token, "今ちょっと不安定みたいだ。少し時間おいてくれ！")
                    continue

                own_code = profile.get("transfer_code", "")
                if own_code and own_code == input_code:
                    _reply(access_token, reply_token, "それはお前自身のコードだぜ！別のアカウントのコードを入力してくれ。")
                    continue

                sb = get_client()
                try:
                    res = sb.table("user_profiles") \
                        .select("*") \
                        .eq("transfer_code", input_code) \
                        .limit(1) \
                        .execute()
                except Exception:
                    _reply(access_token, reply_token, "ごめん、エラーが出ちゃった。もう一回試してくれ！")
                    continue

                if not res.data:
                    _reply(access_token, reply_token, "そのコードは見つからなかった。もう一回確認してくれ！")
                    continue

                source_profile = res.data[0]
                source_id = source_profile["id"]

                # Bidirectional sync: copy memories/stats between both profiles
                from db.user_manager import sync_profiles as _sync

                try:
                    synced = _sync(profile["id"], source_id)
                except Exception:
                    synced = False

                if synced:
                    _profile_cache.pop(f"{user_id}:{sender_id}", None)
                    _reply(access_token, reply_token,
                           "🎉 アカウント連携完了！\n\n"
                           "データを統合したぜ。記憶や成績が引き継がれたぞ！")
                    logger.info(f"MYBOT LINE account sync: {profile['id'][:10]}... <-> {source_id[:10]}...")
                else:
                    _reply(access_token, reply_token, "ごめん、連携でエラーが出ちゃった。もう一回試してくれ！")
                continue

            # --- Honmei (本命) selection handler ---
            if user_text.startswith("本命 ") or user_text.startswith("本命:"):
                match = re.match(r"本命[:\s]+(\d+)番?\s*(.*)", user_text)
                if not match:
                    _reply(access_token, reply_token, "馬番がわからなかった...もう一回タップしてくれ！")
                    continue

                horse_number = int(match.group(1))
                horse_name = match.group(2).strip() or f"{horse_number}番"

                race_id = _get_active_race(user_id, sender_id)
                if not race_id:
                    history = _load_history(user_id, sender_id)
                    race_id = find_race_id(history)

                if not race_id:
                    _reply(access_token, reply_token,
                           "どのレースの本命か分からなかった。先にレースを見てから選んでくれ！")
                    continue

                if profile.get("fallback"):
                    _reply(access_token, reply_token,
                           "今ちょっと登録が不安定みたいだ。少し時間おいてもう一回お願い！")
                    continue

                from tools.executor import _race_cache
                venue = ""
                if race_id in _race_cache and "entries" in _race_cache[race_id]:
                    venue = _race_cache[race_id]["entries"].get("venue", "")

                try:
                    record = db_record_prediction(
                        user_profile_id=profile["id"],
                        race_id=race_id,
                        horse_number=horse_number,
                        horse_name=horse_name,
                        race_name="",
                        venue=venue,
                    )
                except Exception:
                    logger.exception("Failed to record MYBOT honmei")
                    record = None

                if record:
                    _clear_active_race(user_id, sender_id)
                    _reply(access_token, reply_token,
                           f"👊 {horse_number}番 {horse_name} を本命で登録したぜ！\n\n"
                           "みんなの予想に追加したからな。結果出たら回収率も計算してやるよ。")
                    logger.info(f"MYBOT honmei: user={sender_id} race={race_id} horse={horse_number} {horse_name}")
                else:
                    _reply(access_token, reply_token,
                           "ごめん、登録でエラーが出ちゃった。もう一回試してくれ！")
                continue

            # --- Honmei blocking: pending pick ---
            if _has_pending_honmei(user_id, sender_id, profile["id"]):
                if not _is_same_race_query(user_text):
                    pending_race = _get_active_race(user_id, sender_id) or ""
                    honmei_qr = get_honmei_quick_reply(pending_race)
                    if honmei_qr:
                        _reply(
                            access_token, reply_token,
                            "おっと、ちょっと待ってくれ！\n\n"
                            "「みんなの予想」を集めてるんだ。\n"
                            "みんなの本命を集計して、回収率ランキングを出していく予定なんだよ。\n\n"
                            "どうか協力してやってくれ🙏\n\n"
                            "👇 下のボタンから本命をタップ！",
                            quick_reply=honmei_qr,
                        )
                        continue

            # --- Normal message: reply with thinking + run agent ---
            _reply(access_token, reply_token, "考え中...")

            # Process in background thread
            thread = threading.Thread(
                target=_process_message,
                args=(user_id, sender_id, user_text, access_token, bot_settings, profile),
                daemon=True,
            )
            thread.start()

    return "OK", 200
