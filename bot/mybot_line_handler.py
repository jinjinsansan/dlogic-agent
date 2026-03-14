"""MYBOT LINE webhook handler — per-user custom bot via LINE."""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time

from flask import request

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)

from agent.mybot_chat import run_mybot_agent
from agent.engine import format_tool_notification
from db.supabase_client import get_client
from db.encryption import decrypt_value
from db.redis_client import get_redis

logger = logging.getLogger(__name__)

_redis = get_redis()
_HISTORY_TTL = 3 * 3600  # 3 hours
_HISTORY_MAX = 20
_TOOL_NOTICE_DELAY = 5


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
                return json.loads(raw)
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


def _reply(access_token: str, reply_token: str, text: str):
    """Send a reply message using the channel's own access_token."""
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

        req = ReplyMessageRequest(
            reply_token=reply_token,
            messages=messages[:5],
        )
        _send_with_retry(api.reply_message, req)


def _push(access_token: str, sender_id: str, text: str):
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

        req = PushMessageRequest(
            to=sender_id,
            messages=messages[:5],
        )
        _send_with_retry(api.push_message, req)


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

def _process_message(
    user_id: str,
    sender_id: str,
    user_text: str,
    access_token: str,
    bot_settings: dict,
):
    """Run MYBOT agent loop in a background thread and push the result."""
    try:
        history = _load_history(user_id, sender_id)
        profile = {"id": f"mybot_{user_id}_{sender_id}", "display_name": "ユーザー"}

        notified_tools: set[str] = set()
        pending_notice_tools: list[str] = []
        pending_notice_timer: threading.Timer | None = None
        notice_lock = threading.Lock()

        for chunk in run_mybot_agent(
            user_message=user_text,
            history=history,
            profile=profile,
            bot_settings=bot_settings,
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
                                notice = format_tool_notification(tools)
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
                updated_history = chunk.get("history", history)
                _save_history(user_id, sender_id, updated_history)
                _push(access_token, sender_id, full_text)

    except Exception:
        logger.exception(f"Error in MYBOT background processing user_id={user_id}")
        try:
            _push(access_token, sender_id, "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？")
        except Exception:
            logger.exception("Failed to send MYBOT error message")


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

            # Reply immediately with thinking indicator
            _reply(access_token, reply_token, "考え中...")

            # Process in background thread
            thread = threading.Thread(
                target=_process_message,
                args=(user_id, sender_id, user_text, access_token, bot_settings),
                daemon=True,
            )
            thread.start()

    return "OK", 200
