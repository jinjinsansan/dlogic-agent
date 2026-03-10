"""LINE Bot handlers with agentic loop, tool notifications, and quick reply buttons."""

import json
import logging
import os
from datetime import datetime
from functools import partial

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

from agent.engine import (
    call_claude, build_system_prompt, extract_text, get_tool_blocks,
    format_tool_notification, format_tools_used_footer,
    trim_history, extract_memories, HEAVY_TOOLS,
)
from config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, MAX_TOOL_TURNS, ONBOARDING_TEXT
from tools.executor import execute_tool

logger = logging.getLogger(__name__)

# LINE SDK setup
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# In-memory conversation storage (keyed by LINE user ID)
user_conversations: dict[str, list[dict]] = {}

# User memory (persists to file)
MEMORY_DIR = "memory"
user_memory: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# User memory helpers
# ---------------------------------------------------------------------------

def _memory_path() -> str:
    os.makedirs(MEMORY_DIR, exist_ok=True)
    return os.path.join(MEMORY_DIR, "line_users.json")


def load_memory():
    global user_memory
    path = _memory_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_memory = json.load(f)


def save_memory():
    with open(_memory_path(), "w", encoding="utf-8") as f:
        json.dump(user_memory, f, ensure_ascii=False, indent=2)


def get_or_create_user(user_id: str, display_name: str) -> dict:
    if user_id not in user_memory:
        user_memory[user_id] = {
            "name": display_name,
            "first_seen": datetime.now().isoformat(),
            "visits": 0,
            "memories": [],
        }
    user_memory[user_id]["name"] = display_name
    user_memory[user_id]["visits"] += 1
    user_memory[user_id]["last_seen"] = datetime.now().isoformat()
    save_memory()
    return user_memory[user_id]


def add_memories(user_id: str, new_memories: list[str]):
    if user_id not in user_memory:
        return
    existing = set(user_memory[user_id]["memories"])
    for mem in new_memories:
        if mem not in existing and len(mem) > 2:
            user_memory[user_id]["memories"].append(mem)
            existing.add(mem)
            if len(user_memory[user_id]["memories"]) > 30:
                user_memory[user_id]["memories"] = user_memory[user_id]["memories"][-30:]
    save_memory()


def build_user_context(user_id: str, display_name: str) -> str:
    mem = get_or_create_user(user_id, display_name)
    lines = ["【このユーザーについて】"]
    lines.append(f"名前: {display_name}")

    visits = mem["visits"]
    if visits == 1:
        lines.append("初めての訪問。歓迎して、どんな競馬が好きか自然に聞いてみて。")
    elif visits <= 5:
        lines.append(f"まだ {visits} 回目の訪問。少しずつ打ち解けていこう。")
    elif visits <= 20:
        lines.append(f"{visits} 回目の訪問。もう顔なじみ。気軽に話そう。")
    else:
        lines.append(f"{visits} 回目の常連！親友レベルで話そう。")

    if mem.get("memories"):
        lines.append("")
        lines.append("【覚えていること（自然に会話に活かして）】")
        for m in mem["memories"]:
            lines.append(f"- {m}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LINE Quick Reply buttons
# ---------------------------------------------------------------------------

def get_quick_reply(tools_used: list[str]) -> QuickReply | None:
    """Get context-appropriate quick reply buttons based on tools used."""
    used_set = set(tools_used)
    analysis_tools = {"get_race_flow", "get_jockey_analysis", "get_bloodline_analysis", "get_recent_runs"}

    items = []

    if used_set & analysis_tools:
        # After analysis — show remaining + opinion
        if "get_race_flow" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="展開予想", text="展開は？")))
        if "get_jockey_analysis" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="騎手分析", text="騎手の成績は？")))
        if "get_bloodline_analysis" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="血統分析", text="血統は？")))
        if "get_recent_runs" not in used_set:
            items.append(QuickReplyItem(action=MessageAction(label="過去走", text="過去の成績は？")))
        items.append(QuickReplyItem(action=MessageAction(label="どう思う？", text="お前はどう思う？")))

    elif "get_predictions" in used_set:
        # After predictions — deep dive options
        items = [
            QuickReplyItem(action=MessageAction(label="展開予想", text="展開は？")),
            QuickReplyItem(action=MessageAction(label="騎手分析", text="騎手の成績は？")),
            QuickReplyItem(action=MessageAction(label="血統分析", text="血統は？")),
            QuickReplyItem(action=MessageAction(label="過去走", text="過去の成績は？")),
            QuickReplyItem(action=MessageAction(label="全部見る", text="全部掘り下げて")),
            QuickReplyItem(action=MessageAction(label="どう思う？", text="お前はどう思う？")),
        ]

    elif "get_race_entries" in used_set:
        # After entry list — prediction + odds
        items = [
            QuickReplyItem(action=MessageAction(label="予想して", text="予想して")),
            QuickReplyItem(action=MessageAction(label="オッズは？", text="オッズ見せて")),
        ]

    if items:
        return QuickReply(items=items)
    return None


def get_start_quick_reply() -> QuickReply:
    """Default quick reply buttons."""
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="今日のJRA", text="今日のJRA")),
        QuickReplyItem(action=MessageAction(label="今日の地方競馬", text="今日の地方競馬")),
        QuickReplyItem(action=MessageAction(label="ディーロジって？", text="ディーロジって？")),
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
    """Send a reply message with optional quick reply buttons."""
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        messages = []
        if len(text) > 4500:
            chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
            for i, chunk in enumerate(chunks):
                msg = TextMessage(text=chunk)
                # Attach quick reply to last chunk only
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
    """Send a push message with optional quick reply buttons."""
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        msg = TextMessage(text=text)
        if quick_reply:
            msg.quick_reply = quick_reply
        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[msg],
            )
        )


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    """Handle when user adds/follows the bot — send onboarding."""
    user_id = event.source.user_id
    display_name = _get_display_name(user_id)
    get_or_create_user(user_id, display_name)

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

    # Handle special commands
    if user_text in ("リセット", "会話リセット"):
        user_conversations.pop(user_id, None)
        _reply(event.reply_token, "了解、会話リセットしたよ！記憶は残してるからね。",
               quick_reply=get_start_quick_reply())
        return

    if user_text in ("メモリ", "メモリ確認"):
        if user_id in user_memory and user_memory[user_id].get("memories"):
            memories = user_memory[user_id]["memories"]
            text = f"覚えていること ({len(memories)}件):\n\n"
            for i, m in enumerate(memories, 1):
                text += f"{i}. {m}\n"
        else:
            text = "まだあなたのことはあまり知らないな。もっと話そう！"
        _reply(event.reply_token, text)
        return

    if user_text in ("記憶リセット", "忘れて"):
        if user_id in user_memory:
            user_memory[user_id]["memories"] = []
            save_memory()
        _reply(event.reply_token, "了解、記憶をリセットしたよ。またイチから覚えていくね！",
               quick_reply=get_start_quick_reply())
        return

    if user_text in ("ディーロジって？", "ディーロジとは", "使い方"):
        _reply(event.reply_token, ONBOARDING_TEXT, quick_reply=get_start_quick_reply())
        return

    # Reply immediately with "thinking" (LINE reply tokens expire quickly)
    _reply(event.reply_token, "考え中...")

    # Build user context from memory
    user_context = build_user_context(user_id, display_name)
    system = build_system_prompt(user_context)

    # Get or create conversation history
    history = user_conversations.get(user_id, [])
    history = trim_history(history)
    history.append({"role": "user", "content": user_text})

    try:
        tools_used = []
        notified_tools = set()
        response = None

        # Agentic loop
        for turn in range(MAX_TOOL_TURNS):
            response = call_claude(history, system)

            if response.stop_reason == "end_turn":
                history.append({"role": "assistant", "content": response.content})
                break

            tool_blocks = get_tool_blocks(response)
            if not tool_blocks:
                history.append({"role": "assistant", "content": response.content})
                break

            history.append({"role": "assistant", "content": response.content})

            # Notify user (skip already-notified tools)
            new_tool_names = [tb.name for tb in tool_blocks if tb.name not in notified_tools]
            if new_tool_names:
                notification = format_tool_notification(new_tool_names)
                _push(user_id, notification)
                for name in new_tool_names:
                    notified_tools.add(name)

            # Execute tools
            tool_results = []
            for tool_block in tool_blocks:
                tools_used.append(tool_block.name)
                logger.info(f"Executing tool: {tool_block.name}")
                result = execute_tool(tool_block.name, tool_block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                })

            history.append({"role": "user", "content": tool_results})

        # Extract final response
        if response:
            response_text = extract_text(response)
        else:
            response_text = "ごめん、ちょっと調べすぎちゃった。"

        if not response_text:
            response_text = "ごめん、うまく答えられなかった。もう一回聞いてもらえる？"

        footer = format_tools_used_footer(tools_used)
        if footer:
            response_text = response_text + "\n\n" + footer

        user_conversations[user_id] = history

        # Auto-extract memories
        try:
            new_memories = extract_memories(user_text, response_text)
            if new_memories:
                add_memories(user_id, new_memories)
                logger.info(f"New memories for LINE user {user_id}: {new_memories}")
        except Exception:
            pass

        # Push final response with contextual quick reply buttons
        qr = get_quick_reply(tools_used)
        _push(user_id, response_text, quick_reply=qr)

    except Exception as e:
        logger.exception(f"Error processing LINE message for user {user_id}")
        _push(user_id, "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？")
