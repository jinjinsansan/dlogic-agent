"""LINE Bot handlers with agentic loop, tool notifications, and quick reply buttons."""

import json
import logging
import re
import time
import threading
import requests
from datetime import datetime, timezone, timedelta

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    MessageAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, AccountLinkEvent

from agent.engine import trim_history, format_tool_notification
from agent.chat_core import run_agent
from agent.response_cache import find_race_id, detect_query_type
from config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, ONBOARDING_TEXT
from db.user_manager import (
    get_or_create_user as db_get_or_create_user,
    get_memories as db_get_memories,
    clear_memories as db_clear_memories,
    get_transfer_code as db_get_transfer_code,
    transfer_account as db_transfer_account,
    sync_profiles as db_sync_profiles,
    get_link_code_login_id,
    touch_link_code,
    consume_link_code,
    link_login_id_to_profile,
    migrate_mybot_owner,
    is_maintenance_mode,
    get_maintenance_message,
    get_user_status,
)
from db.prediction_manager import (
    record_prediction as db_record_prediction,
    check_prediction as db_check_prediction,
)
from db.redis_client import get_redis
from tools.executor import execute_tool, resolve_race_id_from_text

logger = logging.getLogger(__name__)

# LINE SDK setup
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Rich Menu IDs (set via setup_richmenus_all.py → .env.local)
import os as _os
RICHMENU_NORMAL_ID = _os.environ.get("RICHMENU_NORMAL_ID", "")
RICHMENU_WAITLIST_ID = _os.environ.get("RICHMENU_WAITLIST_ID", "")
RICHMENU_MAINTENANCE_ID = _os.environ.get("RICHMENU_MAINTENANCE_ID", "")

# In-memory conversation storage (keyed by LINE user ID)
user_conversations: dict[str, list[dict]] = {}

# In-memory cache of profile_id per LINE user (avoids repeated DB lookups within session)
_profile_cache: dict[str, dict] = {}
_MAX_PROFILE_CACHE = 500

# Track active race_id per user for honmei selection
_user_active_race: dict[str, str] = {}

# Track daily greeting per user (in-memory, resets on service restart = OK)
_daily_greeted: dict[str, str] = {}  # user_id → "YYYY-MM-DD" (JST)

JST = timezone(timedelta(hours=9))

_redis = get_redis()
_HISTORY_TTL = 12 * 3600
_ACTIVE_RACE_TTL = 24 * 3600
_TOOL_NOTICE_DELAY = 5


def _redis_key(prefix: str, user_id: str) -> str:
    return f"line:{prefix}:{user_id}"


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


def _normalize_history(history: list[dict]) -> list[dict]:
    normalized = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            content = [_normalize_block(b) for b in content]
        normalized.append({"role": role, "content": content})
    return normalized


def _issue_link_token(user_id: str) -> str | None:
    url = f"https://api.line.me/v2/bot/user/{user_id}/linkToken"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"LINE linkToken failed: {resp.status_code} {resp.text[:200]}")
            return None
        return resp.json().get("linkToken")
    except Exception:
        logger.exception("Failed to issue LINE linkToken")
        return None


def _load_history(user_id: str) -> list[dict]:
    if _redis:
        try:
            raw = _redis.get(_redis_key("history", user_id))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.exception("Failed to load history from Redis")
    return user_conversations.get(user_id, [])


def _save_history(user_id: str, history: list[dict]) -> None:
    normalized = _normalize_history(history)
    if _redis:
        try:
            _redis.setex(_redis_key("history", user_id), _HISTORY_TTL,
                         json.dumps(normalized, ensure_ascii=False))
        except Exception:
            logger.exception("Failed to save history to Redis")
    user_conversations[user_id] = normalized
    _evict_conversations()


def _get_active_race(user_id: str) -> str | None:
    if _redis:
        try:
            val = _redis.get(_redis_key("active_race", user_id))
            if val:
                return val
        except Exception:
            logger.exception("Failed to load active race from Redis")
    return _user_active_race.get(user_id)


def _set_active_race(user_id: str, race_id: str) -> None:
    if _redis:
        try:
            _redis.setex(_redis_key("active_race", user_id), _ACTIVE_RACE_TTL, race_id)
        except Exception:
            logger.exception("Failed to save active race to Redis")
    _user_active_race[user_id] = race_id
    if len(_user_active_race) > _MAX_ACTIVE_RACE:
        to_remove = list(_user_active_race.keys())[:200]
        for k in to_remove:
            del _user_active_race[k]
    if len(_daily_greeted) > _MAX_DAILY_GREETED:
        _daily_greeted.clear()


def _clear_active_race(user_id: str) -> None:
    if _redis:
        try:
            _redis.delete(_redis_key("active_race", user_id))
        except Exception:
            logger.exception("Failed to clear active race from Redis")
    _user_active_race.pop(user_id, None)


def _safe_db_call(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception(f"DB error in {getattr(fn, '__name__', 'unknown')}")
        return default


def _should_daily_greet(user_id: str, profile: dict) -> bool:
    """Check if this is the user's first message today (JST)."""
    today_jst = datetime.now(JST).strftime("%Y-%m-%d")

    # Already greeted today in this process
    if _daily_greeted.get(user_id) == today_jst:
        return False

    # Check last_seen_at from profile (set BEFORE update, so it's the previous visit)
    last_seen = profile.get("last_seen_at")
    if last_seen:
        try:
            if isinstance(last_seen, str):
                # Parse ISO format, handle timezone
                last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            else:
                last_dt = last_seen
            last_date_jst = last_dt.astimezone(JST).strftime("%Y-%m-%d")
            if last_date_jst == today_jst:
                # Already visited today (from DB), don't greet
                _daily_greeted[user_id] = today_jst
                return False
        except Exception:
            pass

    _daily_greeted[user_id] = today_jst
    return True


# ---------------------------------------------------------------------------
# Honmei (本命) blocking logic
# ---------------------------------------------------------------------------

# Keywords that indicate user is trying to move to a DIFFERENT race/topic
_RACE_CHANGE_KEYWORDS = [
    "他のレース", "別のレース", "次のレース",
    "船橋", "大井", "川崎", "浦和", "園田", "姫路", "金沢", "名古屋", "笠松", "高知", "佐賀",
    "中山", "阪神", "東京", "京都", "小倉", "新潟", "福島", "札幌", "函館",
    "今日のJRA", "今日の地方", "地方競馬", "JRA",
    "メインレース",
]

# Keywords that are about the SAME race (allowed even with pending honmei)
_SAME_RACE_KEYWORDS = [
    "予想して", "オッズ", "馬体重", "関係者", "展開", "騎手", "血統", "過去", "直近",
    "どう思う", "全部", "掘り下げ",
]


def _is_race_change(text: str) -> bool:
    """Check if user message indicates moving to a different race."""
    for kw in _RACE_CHANGE_KEYWORDS:
        if kw in text:
            return True
    # Pattern: "Xレース" or "XR" (changing race number)
    if re.search(r"\d+[Rレース]", text):
        return True
    return False


def _is_same_race_query(text: str) -> bool:
    """Check if user message is about the current race (deep dive)."""
    for kw in _SAME_RACE_KEYWORDS:
        if kw in text:
            return True
    return False


def _needs_race_prompt(text: str) -> bool:
    if detect_query_type(text):
        return True
    return any(kw in text for kw in (
        "予想", "展開", "騎手", "血統", "オッズ", "馬体重", "調教",
        "関係者", "結果", "勝率", "出馬表", "本命比率",
    ))


def _should_prompt_honmei(race_id: str) -> bool:
    if not race_id:
        return False
    try:
        from tools.executor import is_future_or_today_race
        return is_future_or_today_race(race_id)
    except Exception:
        return False


def _has_pending_honmei(user_id: str, profile_id: str) -> bool:
    """Check if user has a pending honmei pick (viewed race but hasn't picked)."""
    race_id = _get_active_race(user_id)
    if not race_id:
        return False
    if not _should_prompt_honmei(race_id):
        return False
    existing = _safe_db_call(db_check_prediction, profile_id, race_id, default="error")
    if existing == "error":
        return False
    return existing is None


# ---------------------------------------------------------------------------
# LINE Quick Reply buttons
# ---------------------------------------------------------------------------

def get_quick_reply(tools_used: list[str]) -> QuickReply | None:
    """Get context-appropriate quick reply buttons based on tools used."""
    used_set = set(tools_used)

    # All race-related tools — if any was used, user is analyzing a race
    race_tools = {
        "get_predictions", "get_race_entries", "get_race_flow",
        "get_jockey_analysis", "get_bloodline_analysis", "get_recent_runs",
        "get_stable_comments", "get_realtime_odds", "get_odds_probability",
        "get_horse_weights", "get_training_comments", "get_honmei_ratio",
    }

    items = []

    if used_set & race_tools:
        # User is analyzing a race — show all unused tools
        if "get_predictions" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="🎯 予想して", text="予想して")))
        if "get_race_flow" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="🔄 展開予想", text="展開は？")))
        if "get_jockey_analysis" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="🏇 騎手分析", text="騎手の成績は？")))
        if "get_bloodline_analysis" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="🧬 血統分析", text="血統は？")))
        if "get_recent_runs" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="📈 過去走", text="過去の成績は？")))
        if "get_stable_comments" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="🗣️ 関係者情報", text="関係者情報は？")))
        if "get_odds_probability" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="📊 予測勝率", text="予測勝率見せて")))
        if "get_realtime_odds" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="💰 オッズは？", text="オッズ見せて")))
        if "get_horse_weights" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="⚖️ 馬体重", text="馬体重は？")))
        items.append(QuickReplyItem(action=MessageAction(label="🗳️ みんなの本命", text="みんなの本命比率")))
        items.append(QuickReplyItem(action=MessageAction(label="💬 どう思う？", text="お前はどう思う？")))

    elif "get_today_races" in used_set:
        # After race list — offer to pick main race
        items = [
            QuickReplyItem(action=MessageAction(label="🏇 メインレース", text="メインレースの出馬表見せて")),
        ]

    if items:
        return QuickReply(items=items)
    return None


def get_honmei_quick_reply(race_id: str) -> QuickReply | None:
    """Generate Quick Reply buttons for honmei (本命) horse selection."""
    from tools.executor import _race_cache

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
        if len(items) >= 13:  # LINE limit
            break

    return QuickReply(items=items) if items else None


def get_start_quick_reply() -> QuickReply:
    """Default quick reply buttons (fallback for text messages)."""
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🏇 今日のJRA", text="今日のJRA")),
        QuickReplyItem(action=MessageAction(label="🏇 今日の地方", text="今日の地方競馬")),
        QuickReplyItem(action=MessageAction(label="📊 俺の成績", text="俺の成績は？")),
        QuickReplyItem(action=MessageAction(label="🏆 ランキング", text="ランキング見せて")),
        QuickReplyItem(action=MessageAction(label="❓ ディーロジって？", text="ディーロジって？")),
        QuickReplyItem(action=MessageAction(label="📩 問い合わせ", text="問い合わせしたい")),
    ])




# ---------------------------------------------------------------------------
# Rich Menu switching
# ---------------------------------------------------------------------------

def _link_richmenu(user_id: str, richmenu_id: str):
    """Link a specific rich menu to a user."""
    if not richmenu_id:
        return
    try:
        import requests as _req
        _req.post(
            f"https://api.line.me/v2/bot/user/{user_id}/richmenu/{richmenu_id}",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=5,
        )
        logger.info(f"Rich menu linked: {user_id[:10]}... → {richmenu_id[:10]}...")
    except Exception:
        logger.exception("Failed to link rich menu")


def _unlink_richmenu(user_id: str):
    """Unlink user's rich menu (reverts to default)."""
    try:
        import requests as _req
        _req.delete(
            f"https://api.line.me/v2/bot/user/{user_id}/richmenu",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=5,
        )
        logger.info(f"Rich menu unlinked: {user_id[:10]}... (back to default)")
    except Exception:
        logger.exception("Failed to unlink rich menu")


def set_default_richmenu(richmenu_id: str):
    """Set a rich menu as default for ALL users."""
    if not richmenu_id:
        return
    try:
        import requests as _req
        _req.post(
            f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=5,
        )
        logger.info(f"Default rich menu set: {richmenu_id[:10]}...")
    except Exception:
        logger.exception("Failed to set default rich menu")


def switch_to_waitlist_menu(user_id: str):
    """Switch a user to the waitlist rich menu."""
    if RICHMENU_WAITLIST_ID:
        _link_richmenu(user_id, RICHMENU_WAITLIST_ID)


def switch_to_normal_menu(user_id: str):
    """Switch a user back to the normal rich menu (unlink = use default)."""
    _unlink_richmenu(user_id)


def enable_maintenance_menu():
    """Switch ALL users to maintenance rich menu."""
    if RICHMENU_MAINTENANCE_ID:
        set_default_richmenu(RICHMENU_MAINTENANCE_ID)


def disable_maintenance_menu():
    """Restore ALL users to normal rich menu."""
    if RICHMENU_NORMAL_ID:
        set_default_richmenu(RICHMENU_NORMAL_ID)


# ---------------------------------------------------------------------------
# LINE messaging helpers
# ---------------------------------------------------------------------------

def _get_display_name(user_id: str) -> str:
    """Get LINE user's display name via API."""
    try:
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)
            profile = api.get_profile(user_id)
            return profile.display_name
    except Exception:
        return "ゲスト"


def _send_with_retry(send_fn, request_obj, retries: int = 1) -> bool:
    for attempt in range(retries + 1):
        try:
            send_fn(request_obj)
            return True
        except Exception:
            if attempt < retries:
                time.sleep(1)
                continue
            logger.exception("LINE API send failed")
            return False


def _reply(reply_token: str, text: str, quick_reply: QuickReply = None):
    """Send a reply message with optional quick reply."""
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        messages = []
        if len(text) > 4500:
            chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
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


def _push(user_id: str, text: str, quick_reply: QuickReply = None):
    """Send a push message with optional quick reply."""
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        messages = []

        if len(text) > 4500:
            chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
            for chunk in chunks:
                messages.append(TextMessage(text=chunk))
        else:
            messages.append(TextMessage(text=text))

        if quick_reply:
            messages[-1].quick_reply = quick_reply

        req = PushMessageRequest(
            to=user_id,
            messages=messages[:5],
        )
        _send_with_retry(api.push_message, req)


# ---------------------------------------------------------------------------
# Honmei (本命) selection handler
# ---------------------------------------------------------------------------

def _handle_honmei_selection(event, user_id: str, text: str, profile: dict):
    """Handle '本命 X番 馬名' messages — record to Supabase."""
    match = re.match(r"本命[:\s]+(\d+)番?\s*(.*)", text)
    if not match:
        _reply(event.reply_token, "馬番がわからなかった...もう一回タップしてくれ！")
        return

    horse_number = int(match.group(1))
    horse_name = match.group(2).strip() or f"{horse_number}番"

    race_id = _get_active_race(user_id)
    if not race_id:
        history = _load_history(user_id)
        race_id = find_race_id(history)

    if not race_id:
        _reply(event.reply_token, "どのレースの本命か分からなかった。先にレースを見てから選んでくれ！",
               quick_reply=get_start_quick_reply())
        return

    if profile.get("fallback"):
        _reply(event.reply_token, "今ちょっと登録が不安定みたいだ。少し時間おいてもう一回お願い！")
        return

    from tools.executor import _race_cache
    race_name = ""
    venue = ""
    if race_id in _race_cache and "entries" in _race_cache[race_id]:
        venue = _race_cache[race_id]["entries"].get("venue", "")

    record = _safe_db_call(
        db_record_prediction,
        user_profile_id=profile["id"],
        race_id=race_id,
        horse_number=horse_number,
        horse_name=horse_name,
        race_name=race_name,
        venue=venue,
        default=None,
    )
    if record:
        # アクティブレースはクリアしない（本命登録後も分析を続けられるようにする）

        _reply(event.reply_token,
               f"👊 {horse_number}番 {horse_name} を本命で登録したぜ！\n\nみんなの予想に追加したからな。結果出たら回収率も計算してやるよ。",
               quick_reply=get_quick_reply(["get_predictions"]))
        logger.info(f"Honmei recorded: user={user_id} race={race_id} horse={horse_number} {horse_name}")
        return

    _reply(event.reply_token, "ごめん、登録でエラーが出ちゃった。もう一回試してくれ！")


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _evict_profile_cache():
    """Evict oldest entries when profile cache exceeds limit."""
    if len(_profile_cache) <= _MAX_PROFILE_CACHE:
        return
    # Remove ~20% of entries (no timestamp, just trim arbitrarily)
    to_remove = list(_profile_cache.keys())[:len(_profile_cache) - _MAX_PROFILE_CACHE + 50]
    for key in to_remove:
        del _profile_cache[key]
    logger.info(f"Profile cache evicted {len(to_remove)} entries, now {len(_profile_cache)}")


_MAX_CONVERSATIONS = 500  # limit in-memory fallback conversation store


def _evict_conversations():
    """Evict oldest entries when user_conversations exceeds limit."""
    if len(user_conversations) <= _MAX_CONVERSATIONS:
        return
    to_remove = list(user_conversations.keys())[:len(user_conversations) - _MAX_CONVERSATIONS + 50]
    for key in to_remove:
        del user_conversations[key]
    logger.info(f"Conversations evicted {len(to_remove)} entries, now {len(user_conversations)}")


_MAX_ACTIVE_RACE = 1000
_MAX_DAILY_GREETED = 1000


def _get_profile(user_id: str, display_name: str) -> dict:
    """Get or create user profile, with in-memory caching."""
    if user_id not in _profile_cache:
        _evict_profile_cache()
        try:
            _profile_cache[user_id] = db_get_or_create_user(user_id, display_name)
        except Exception:
            logger.exception("Failed to fetch profile from DB; using fallback profile")
            _profile_cache[user_id] = {
                "id": f"local_{user_id}",
                "display_name": display_name,
                "visit_count": 1,
                "fallback": True,
            }
    return _profile_cache[user_id]


@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    """Handle when user adds/follows the bot — register as waitlist."""
    user_id = event.source.user_id
    display_name = _get_display_name(user_id)
    profile = _get_profile(user_id, display_name)

    # Check user status — new users default to 'waitlist'
    status = "active"
    if not profile.get("fallback"):
        status = _safe_db_call(get_user_status, profile["id"], default="active") or "active"
    if status == "waitlist":
        switch_to_waitlist_menu(user_id)
        _reply(
            event.reply_token,
            f"よう、{display_name}！はじめまして！\n\n"
            "俺はディーロジ。お前の競馬の相棒だ。\n\n"
            "ありがてえ、登録してくれたんだな！\n"
            "ただ今めちゃくちゃ人が集まっててよ、順番に案内してるところなんだ。\n\n"
            "お前の番が来たらすぐ連絡するから、もうちょい待っててくれ！💪",
        )
        return

    _reply(
        event.reply_token,
        f"よう、{display_name}！はじめまして！\n\n"
        "俺はディーロジ。お前の競馬の相棒だ。\n\n"
        + ONBOARDING_TEXT,
        quick_reply=get_start_quick_reply(),
    )


@handler.add(AccountLinkEvent)
def handle_account_link(event: AccountLinkEvent):
    """Handle LINE Account Link completion event."""
    user_id = event.source.user_id
    link = event.link
    result = getattr(link, "result", None)
    nonce = getattr(link, "nonce", None)

    if result != "ok" or not nonce:
        _reply(event.reply_token, "連携に失敗したみたいだ。もう一回やってみてくれ！")
        return

    line_login_id = consume_link_code(nonce)
    if not line_login_id:
        _reply(event.reply_token, "連携コードの期限が切れてるみたいだ。もう一回やってくれ！")
        return

    display_name = _get_display_name(user_id)
    profile = _get_profile(user_id, display_name)

    previous_id = link_login_id_to_profile(profile["id"], line_login_id)
    if previous_id:
        db_sync_profiles(profile["id"], previous_id)
        migrate_mybot_owner(previous_id, profile["id"])

    _reply(event.reply_token, "連携完了！これでWebとLINEが一緒になったぜ。")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    """Handle incoming text messages with agentic loop."""
    user_id = event.source.user_id
    user_text = event.message.text
    display_name = _get_display_name(user_id)

    if not user_text:
        return

    logger.info(f"[MSG] {display_name} ({user_id}): {user_text[:200]}")

    # ── Gate 1: Emergency maintenance check ($0 — no Claude API call) ──
    if _safe_db_call(is_maintenance_mode, default=False):
        msg = _safe_db_call(get_maintenance_message, default="ただいまメンテナンス中です。")
        _reply(event.reply_token, f"🔧 {msg}")
        return

    # ── Account link flow (allowed even if waitlist) ──
    link_match = re.match(r"^(?:連携|アカウント連携)\s*([A-Za-z0-9]{4,10})?$", user_text)
    if link_match:
        code = link_match.group(1)
        if not code:
            _reply(
                event.reply_token,
                "連携コードを送ってくれ！\n"
                "Webで発行したコードを『連携 ABC123』の形で送ればOKだ。",
            )
            return

        line_login_id = get_link_code_login_id(code)
        if not line_login_id:
            _reply(event.reply_token, "連携コードが見つからないか期限切れだ。もう一回発行してくれ！")
            return

        link_token = _issue_link_token(user_id)
        if not link_token:
            _reply(event.reply_token, "今ちょっと連携に失敗した。時間をおいてもう一回頼む！")
            return

        touch_link_code(code)
        link_url = f"https://access.line.me/dialog/bot/accountLink?linkToken={link_token}&nonce={code}"
        _reply(
            event.reply_token,
            "このリンクを開いて連携を完了してくれ👇\n" + link_url,
        )
        return

    # ── Gate 2: User status check (waitlist / suspended) ──
    profile = _get_profile(user_id, display_name)
    status = "active"
    if not profile.get("fallback"):
        status = _safe_db_call(get_user_status, profile["id"], default="active") or "active"
    if status == "waitlist":
        _reply(
            event.reply_token,
            "おっと、すまねえ！\n\n"
            "今めちゃくちゃ登録が殺到しててよ、順番に案内してるんだ。\n"
            "お前の番が来たらすぐ連絡するから、もうちょい待っててくれ！💪",
        )
        return
    if status == "suspended":
        _reply(
            event.reply_token,
            "悪いな、お前のアカウントは今ちょっと止まってるんだ。\n"
            "何かあったらここから連絡してくれ👇\n"
            "https://lin.ee/73wrNkv",
        )
        return

    # Handle honmei (本命) selection — intercept before agentic loop
    if user_text.startswith("本命 ") or user_text.startswith("本命:"):
        profile = _get_profile(user_id, display_name)
        _handle_honmei_selection(event, user_id, user_text, profile)
        return

    # Handle special commands
    if user_text in ("リセット", "会話リセット"):
        _save_history(user_id, [])
        _clear_active_race(user_id)
        _reply(event.reply_token, "了解、会話リセットしたよ！記憶は残してるからね。",
               quick_reply=get_start_quick_reply())
        return

    if user_text in ("メモリ", "メモリ確認"):
        profile = _get_profile(user_id, display_name)
        if profile.get("fallback"):
            _reply(event.reply_token, "今ちょっと記憶が不安定みたいだ。少し時間おいてくれ！")
            return
        memories = _safe_db_call(db_get_memories, profile["id"], default=[])
        if memories:
            text = f"覚えていること ({len(memories)}件):\n\n"
            for i, m in enumerate(memories, 1):
                text += f"{i}. {m['content']}\n"
        else:
            text = "まだあなたのことはあまり知らないな。もっと話そう！"
        _reply(event.reply_token, text)
        return

    if user_text in ("引き継ぎコード", "引継ぎコード", "連携コード", "アカウント連携", "記憶コピー", "記憶コピーコード"):
        profile = _get_profile(user_id, display_name)
        if profile.get("fallback"):
            _reply(event.reply_token, "今ちょっと不安定みたいだ。少し時間おいてくれ！")
            return
        code = _safe_db_call(db_get_transfer_code, profile["id"], default=None)
        if code:
            _reply(event.reply_token,
                   f"お前の連携コードはこれだ👇\n\n"
                   f"🔑 {code}\n\n"
                   "━━━━━━━━━━━━\n"
                   "📱 Webマイページで入力してね！\n"
                   "━━━━━━━━━━━━\n\n"
                   "Webのマイページにこのコードを\n"
                   "入力すると、記憶・予想・回収率が\n"
                   "すべて統合されるぜ！（1回でOK）\n\n"
                   "※ コードは他の人に教えないように！")
        else:
            _reply(event.reply_token, "コードが取得できなかった。もう一回試してくれ！")
        return

    # Handle transfer code input: 「引き継ぎ XXXXXX」or「記憶コピー XXXXXX」
    transfer_match = re.match(r"(?:引き継ぎ|記憶コピー)\s+([A-Za-z0-9]{4,8})", user_text)
    if transfer_match:
        input_code = transfer_match.group(1).strip().upper()
        profile = _get_profile(user_id, display_name)
        if profile.get("fallback"):
            _reply(event.reply_token, "今ちょっと不安定みたいだ。少し時間おいてくれ！")
            return

        # Don't let user link to their own code
        own_code = profile.get("transfer_code", "")
        if own_code and own_code == input_code:
            _reply(event.reply_token, "それはお前自身のコードだぜ！別のアカウントのコードを入力してくれ。")
            return

        # Look up the profile with this code
        from db.supabase_client import get_client
        sb = get_client()
        try:
            res = sb.table("user_profiles") \
                .select("*") \
                .eq("transfer_code", input_code) \
                .limit(1) \
                .execute()
        except Exception:
            _reply(event.reply_token, "ごめん、エラーが出ちゃった。もう一回試してくれ！")
            return

        if not res.data:
            _reply(event.reply_token, "そのコードは見つからなかった。もう一回確認してくれ！")
            return

        source_profile = res.data[0]
        source_id = source_profile["id"]

        # Bidirectional sync: copy memories/stats between both profiles
        synced = _safe_db_call(db_sync_profiles, profile["id"], source_id, default=False)
        if synced:
            _profile_cache.pop(user_id, None)  # Clear cache to refresh profile fields
            _reply(event.reply_token,
                   "🎉 アカウント連携完了！\n\n"
                   "データを統合したぜ。記憶や成績が引き継がれたぞ！")
            logger.info(f"LINE Bot account sync: {profile['id'][:10]}... <-> {source_id[:10]}...")
        else:
            _reply(event.reply_token, "ごめん、連携でエラーが出ちゃった。もう一回試してくれ！")
        return

    if user_text in ("記憶リセット", "忘れて"):
        profile = _get_profile(user_id, display_name)
        if profile.get("fallback"):
            _reply(event.reply_token, "今ちょっと記憶が不安定みたいだ。少し時間おいてくれ！")
            return
        _safe_db_call(db_clear_memories, profile["id"])
        _reply(event.reply_token, "了解、記憶をリセットしたよ。またイチから覚えていくね！",
               quick_reply=get_start_quick_reply())
        return

    if user_text in ("ディーロジって？", "ディーロジとは", "使い方"):
        _reply(event.reply_token, ONBOARDING_TEXT, quick_reply=get_start_quick_reply())
        return

    # Auto-resolve explicit race hints (venue + R, race_id)
    resolved_race = resolve_race_id_from_text(user_text)
    if resolved_race:
        _set_active_race(user_id, resolved_race)

    # Ask for race if missing context
    # 「メインレース」はClaude APIに渡して判断させる
    if not _get_active_race(user_id) and _needs_race_prompt(user_text) and "メインレース" not in user_text:
        _reply(
            event.reply_token,
            "どのレースの話だ？\n\n例: 中山11R / 阪神10レース / 20260319-中山-11",
        )
        return

    # Handle ranking directly (no Claude API call needed — always returns "no data")
    if user_text in ("ランキング見せて", "ランキング", "みんなの成績"):
        _reply(
            event.reply_token,
            "まだランキングのデータが集まっていないみたいだ〜\n\n"
            "みんなの予想がもっと集まったら、ランキングを発表するぜ！\n"
            "まずはレースの本命を登録してくれ！",
            quick_reply=get_start_quick_reply(),
        )
        return

    # NOTE: 引き継ぎコード機能は保留中（コードはDB生成済みだが会話には出さない）

    # ── Daily greeting disabled to save push message quota ──
    # _should_daily_greet(user_id, profile) — skipped

    # ── Honmei blocking: if user has pending pick and tries to change race ──
    if _has_pending_honmei(user_id, profile["id"]):
        pending_race = _get_active_race(user_id) or ""
        # Allow same-race queries (展開, オッズ, etc.) to pass through
        if not _is_same_race_query(user_text):
            # Block and re-show honmei buttons
            honmei_qr = get_honmei_quick_reply(pending_race)
            if honmei_qr:
                _reply(event.reply_token,
                       "おっと、ちょっと待ってくれ！\n\n"
                       "今Dlogicじゃ「みんなの予想」を集めてるんだ。\n"
                       "みんなの本命を集計して、回収率ランキングとか出していく予定なんだよ。\n\n"
                       "どうか協力してやってくれ🙏\n"
                       "これ押してもらわねーと俺も次に進めねーんだ…頼むよ！\n\n"
                       "👇 下のボタンから本命をタップ！",
                       quick_reply=honmei_qr)
                return

    # Get or create conversation history
    history = _load_history(user_id)

    # Use shared agentic loop
    active_rid = _get_active_race(user_id)
    replied = False
    notified_tools: set[str] = set()
    pending_notice_tools: list[str] = []
    pending_notice_timer: threading.Timer | None = None
    notice_lock = threading.Lock()

    try:
        for chunk in run_agent(
            user_message=user_text,
            history=history,
            profile=profile,
            active_race_id_hint=active_rid,
        ):
            chunk_type = chunk.get("type")

            if chunk_type == "thinking" and not replied:
                # Reply immediately (LINE reply tokens expire quickly)
                _reply(event.reply_token, "考え中...")
                replied = True

            elif chunk_type == "tool":
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
                                _push(user_id, notice)
                            except Exception:
                                logger.exception("Failed to send tool notification")

                        pending_notice_timer = threading.Timer(_TOOL_NOTICE_DELAY, _send_delayed_notice)
                        pending_notice_timer.daemon = True
                        pending_notice_timer.start()

            elif chunk_type == "done":
                if pending_notice_timer and pending_notice_timer.is_alive():
                    pending_notice_timer.cancel()

                full_text = chunk["text"]
                tools_used = chunk.get("tools_used", [])
                active_race_id = chunk.get("active_race_id")
                _save_history(user_id, chunk.get("history", history))

                # Always save active_race_id so next message has context
                if active_race_id:
                    _set_active_race(user_id, active_race_id)

                # Integrate honmei into same message to save push quota
                qr = get_quick_reply(tools_used)
                used_set = set(tools_used)

                if used_set & {"get_predictions"} and active_race_id:
                    if profile.get("fallback"):
                        already_picked = True
                    else:
                        already_picked = _safe_db_call(db_check_prediction, profile["id"], active_race_id, default="error")
                        if already_picked == "error":
                            already_picked = True
                    if not already_picked and _should_prompt_honmei(active_race_id):
                        honmei_qr = get_honmei_quick_reply(active_race_id)
                        if honmei_qr:
                            full_text += (
                                "\n\n━━━━━━━━━━━━━━━\n"
                                "📢 みんなの予想\n"
                                "━━━━━━━━━━━━━━━\n\n"
                                "お前の本命を教えてくれ！👇"
                            )
                            qr = honmei_qr

                if not replied:
                    # Cache hit等で即完了 — reply tokenで直接返す（Quick Reply確実）
                    _reply(event.reply_token, full_text, quick_reply=qr)
                    replied = True
                else:
                    _push(user_id, full_text, quick_reply=qr)

    except Exception as e:
        if pending_notice_timer and pending_notice_timer.is_alive():
            pending_notice_timer.cancel()
        logger.exception(f"Error processing LINE message for user {user_id}")
        _push(user_id, "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？")
