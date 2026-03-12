"""LINE Bot handlers with agentic loop, tool notifications, and quick reply buttons."""

import logging
import re
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
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent

from agent.engine import trim_history
from agent.chat_core import run_agent
from agent.response_cache import find_race_id
from config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, ONBOARDING_TEXT
from db.user_manager import (
    get_or_create_user as db_get_or_create_user,
    get_memories as db_get_memories,
    clear_memories as db_clear_memories,
    get_transfer_code as db_get_transfer_code,
    transfer_account as db_transfer_account,
    is_maintenance_mode,
    get_maintenance_message,
    get_user_status,
)
from db.prediction_manager import (
    record_prediction as db_record_prediction,
    check_prediction as db_check_prediction,
)
from tools.executor import execute_tool

logger = logging.getLogger(__name__)

# LINE SDK setup
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# In-memory conversation storage (keyed by LINE user ID)
user_conversations: dict[str, list[dict]] = {}

# In-memory cache of profile_id per LINE user (avoids repeated DB lookups within session)
_profile_cache: dict[str, dict] = {}

# Track active race_id per user for honmei selection
_user_active_race: dict[str, str] = {}

# Track daily greeting per user (in-memory, resets on service restart = OK)
_daily_greeted: dict[str, str] = {}  # user_id → "YYYY-MM-DD" (JST)

JST = timezone(timedelta(hours=9))


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


def _has_pending_honmei(user_id: str, profile_id: str) -> bool:
    """Check if user has a pending honmei pick (viewed race but hasn't picked)."""
    race_id = _user_active_race.get(user_id)
    if not race_id:
        return False
    existing = db_check_prediction(profile_id, race_id)
    return existing is None


# ---------------------------------------------------------------------------
# LINE Quick Reply buttons
# ---------------------------------------------------------------------------

def get_quick_reply(tools_used: list[str]) -> QuickReply | None:
    """Get context-appropriate quick reply buttons based on tools used."""
    used_set = set(tools_used)
    analysis_tools = {"get_race_flow", "get_jockey_analysis", "get_bloodline_analysis", "get_recent_runs", "get_stable_comments"}

    items = []

    if used_set & analysis_tools:
        # After analysis — show remaining + opinion
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
        items.append(QuickReplyItem(action=MessageAction(label="💬 どう思う？", text="お前はどう思う？")))

    elif "get_predictions" in used_set:
        # After predictions — deep dive options
        items = [
            QuickReplyItem(action=MessageAction(label="🔄 展開予想", text="展開は？")),
            QuickReplyItem(action=MessageAction(label="🏇 騎手分析", text="騎手の成績は？")),
            QuickReplyItem(action=MessageAction(label="🧬 血統分析", text="血統は？")),
            QuickReplyItem(action=MessageAction(label="📈 過去走", text="過去の成績は？")),
            QuickReplyItem(action=MessageAction(label="🗣️ 関係者情報", text="関係者情報は？")),
            QuickReplyItem(action=MessageAction(label="🔥 全部見る", text="全部掘り下げて")),
            QuickReplyItem(action=MessageAction(label="💬 どう思う？", text="お前はどう思う？")),
        ]

    elif "get_race_entries" in used_set:
        # After entry list — prediction + odds + probability + weight + training
        items = [
            QuickReplyItem(action=MessageAction(label="🎯 予想して", text="予想して")),
            QuickReplyItem(action=MessageAction(label="📊 予測勝率", text="予測勝率見せて")),
            QuickReplyItem(action=MessageAction(label="💰 オッズは？", text="オッズ見せて")),
            QuickReplyItem(action=MessageAction(label="⚖️ 馬体重", text="馬体重は？")),
            QuickReplyItem(action=MessageAction(label="🗣️ 関係者情報", text="関係者情報は？")),
        ]

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

        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages[:5],
            )
        )


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

        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=messages[:5],
            )
        )


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

    race_id = _user_active_race.get(user_id)
    if not race_id:
        history = user_conversations.get(user_id, [])
        race_id = find_race_id(history)

    if not race_id:
        _reply(event.reply_token, "どのレースの本命か分からなかった。先にレースを見てから選んでくれ！",
               quick_reply=get_start_quick_reply())
        return

    from tools.executor import _race_cache
    race_name = ""
    venue = ""
    if race_id in _race_cache and "entries" in _race_cache[race_id]:
        venue = _race_cache[race_id]["entries"].get("venue", "")

    try:
        db_record_prediction(
            user_profile_id=profile["id"],
            race_id=race_id,
            horse_number=horse_number,
            horse_name=horse_name,
            race_name=race_name,
            venue=venue,
        )
        # Clear pending state
        _user_active_race.pop(user_id, None)

        _reply(event.reply_token,
               f"👊 {horse_number}番 {horse_name} を本命で登録したぜ！\n\nみんなの予想に追加したからな。結果出たら回収率も計算してやるよ。",
               quick_reply=get_quick_reply(["get_race_entries"]))
        logger.info(f"Honmei recorded: user={user_id} race={race_id} horse={horse_number} {horse_name}")
    except Exception:
        logger.exception(f"Failed to record honmei for user {user_id}")
        _reply(event.reply_token, "ごめん、登録でエラーが出ちゃった。もう一回試してくれ！")


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _get_profile(user_id: str, display_name: str) -> dict:
    """Get or create user profile, with in-memory caching."""
    if user_id not in _profile_cache:
        _profile_cache[user_id] = db_get_or_create_user(user_id, display_name)
    return _profile_cache[user_id]


@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    """Handle when user adds/follows the bot — register as waitlist."""
    user_id = event.source.user_id
    display_name = _get_display_name(user_id)
    profile = _get_profile(user_id, display_name)

    # Check user status — new users default to 'waitlist'
    status = get_user_status(profile["id"])
    if status == "waitlist":
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


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    """Handle incoming text messages with agentic loop."""
    user_id = event.source.user_id
    user_text = event.message.text
    display_name = _get_display_name(user_id)

    if not user_text:
        return

    # ── Gate 1: Emergency maintenance check ($0 — no Claude API call) ──
    if is_maintenance_mode():
        msg = get_maintenance_message()
        _reply(event.reply_token, f"🔧 {msg}")
        return

    # ── Gate 2: User status check (waitlist / suspended) ──
    profile = _get_profile(user_id, display_name)
    status = get_user_status(profile["id"])
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
        user_conversations.pop(user_id, None)
        _user_active_race.pop(user_id, None)
        _reply(event.reply_token, "了解、会話リセットしたよ！記憶は残してるからね。",
               quick_reply=get_start_quick_reply())
        return

    if user_text in ("メモリ", "メモリ確認"):
        profile = _get_profile(user_id, display_name)
        memories = db_get_memories(profile["id"])
        if memories:
            text = f"覚えていること ({len(memories)}件):\n\n"
            for i, m in enumerate(memories, 1):
                text += f"{i}. {m['content']}\n"
        else:
            text = "まだあなたのことはあまり知らないな。もっと話そう！"
        _reply(event.reply_token, text)
        return

    if user_text in ("記憶リセット", "忘れて"):
        profile = _get_profile(user_id, display_name)
        db_clear_memories(profile["id"])
        _reply(event.reply_token, "了解、記憶をリセットしたよ。またイチから覚えていくね！",
               quick_reply=get_start_quick_reply())
        return

    if user_text in ("ディーロジって？", "ディーロジとは", "使い方"):
        _reply(event.reply_token, ONBOARDING_TEXT, quick_reply=get_start_quick_reply())
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
        pending_race = _user_active_race.get(user_id, "")
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
    history = user_conversations.get(user_id, [])

    # Use shared agentic loop
    active_rid = _user_active_race.get(user_id)
    replied = False

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

            elif chunk_type == "done":
                if not replied:
                    _reply(event.reply_token, "了解👍")
                    replied = True

                full_text = chunk["text"]
                tools_used = chunk.get("tools_used", [])
                active_race_id = chunk.get("active_race_id")
                user_conversations[user_id] = chunk.get("history", history)

                # Integrate honmei into same message to save push quota
                qr = get_quick_reply(tools_used)
                used_set = set(tools_used)

                if used_set & {"get_race_entries", "get_predictions"} and active_race_id:
                    already_picked = db_check_prediction(profile["id"], active_race_id)
                    if not already_picked:
                        _user_active_race[user_id] = active_race_id
                        honmei_qr = get_honmei_quick_reply(active_race_id)
                        if honmei_qr:
                            full_text += (
                                "\n\n━━━━━━━━━━━━━━━\n"
                                "📢 みんなの予想\n"
                                "━━━━━━━━━━━━━━━\n\n"
                                "お前の本命を教えてくれ！👇"
                            )
                            qr = honmei_qr

                _push(user_id, full_text, quick_reply=qr)

    except Exception as e:
        logger.exception(f"Error processing LINE message for user {user_id}")
        _push(user_id, "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？")
