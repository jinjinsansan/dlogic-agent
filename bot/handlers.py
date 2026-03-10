"""Telegram bot handlers with async agentic loop and contextual inline buttons."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from functools import partial
from telegram import (
    BotCommand, Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from agent.engine import (
    call_claude, build_system_prompt, extract_text, get_tool_blocks,
    format_tool_notification, format_tools_used_footer,
    trim_history, extract_memories, HEAVY_TOOLS,
)
from config import TELEGRAM_BOT_TOKEN, MAX_TOOL_TURNS, ONBOARDING_TEXT
from tools.executor import execute_tool

logger = logging.getLogger(__name__)

# In-memory conversation storage
user_conversations: dict[int, list[dict]] = {}

# Cooldown for /start to prevent duplicate messages
_last_start: dict[int, float] = {}

# User memory (persists to file)
MEMORY_DIR = "memory"
user_memory: dict[str, dict] = {}

# Persistent keyboard at bottom of chat
PERSISTENT_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("今日のJRA"), KeyboardButton("今日の地方競馬")],
        [KeyboardButton("ディーロジって？"), KeyboardButton("会話リセット")],
    ],
    resize_keyboard=True,
    input_field_placeholder="レース名や馬名を入力...",
)


# ---------------------------------------------------------------------------
# User memory helpers
# ---------------------------------------------------------------------------

def _memory_path() -> str:
    os.makedirs(MEMORY_DIR, exist_ok=True)
    return os.path.join(MEMORY_DIR, "users.json")


def load_memory():
    """Load user memory from file."""
    global user_memory
    path = _memory_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_memory = json.load(f)


def save_memory():
    """Save user memory to file."""
    with open(_memory_path(), "w", encoding="utf-8") as f:
        json.dump(user_memory, f, ensure_ascii=False, indent=2)


def get_or_create_user(user_id: int, first_name: str) -> dict:
    """Get or create user memory entry."""
    uid = str(user_id)
    if uid not in user_memory:
        user_memory[uid] = {
            "name": first_name,
            "first_seen": datetime.now().isoformat(),
            "visits": 0,
            "memories": [],
        }
    user_memory[uid]["name"] = first_name
    user_memory[uid]["visits"] += 1
    user_memory[uid]["last_seen"] = datetime.now().isoformat()
    save_memory()
    return user_memory[uid]


def add_memories(user_id: int, new_memories: list[str]):
    """Add new memories for a user, avoiding duplicates."""
    uid = str(user_id)
    if uid not in user_memory:
        return

    existing = set(user_memory[uid]["memories"])
    for mem in new_memories:
        if mem not in existing and len(mem) > 2:
            user_memory[uid]["memories"].append(mem)
            existing.add(mem)
            if len(user_memory[uid]["memories"]) > 30:
                user_memory[uid]["memories"] = user_memory[uid]["memories"][-30:]

    save_memory()


def build_user_context(user_id: int, first_name: str) -> str:
    """Build user context string for the system prompt."""
    mem = get_or_create_user(user_id, first_name)

    lines = ["【このユーザーについて】"]
    lines.append(f"名前: {first_name}")

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
# Contextual inline buttons
# ---------------------------------------------------------------------------

def get_context_buttons(tools_used: list[str]) -> InlineKeyboardMarkup | None:
    """Get context-appropriate inline buttons based on tools used in this turn."""
    used_set = set(tools_used)
    analysis_tools = {"get_race_flow", "get_jockey_analysis", "get_bloodline_analysis", "get_recent_runs"}

    if used_set & analysis_tools:
        # After deep analysis — show remaining analysis options + opinion
        rows = []
        remaining = []
        if "get_race_flow" not in used_set:
            remaining.append(InlineKeyboardButton("展開予想", callback_data="展開は？"))
        if "get_jockey_analysis" not in used_set:
            remaining.append(InlineKeyboardButton("騎手分析", callback_data="騎手の成績は？"))
        if "get_bloodline_analysis" not in used_set:
            remaining.append(InlineKeyboardButton("血統分析", callback_data="血統は？"))
        if "get_recent_runs" not in used_set:
            remaining.append(InlineKeyboardButton("過去走", callback_data="過去の成績は？"))
        for i in range(0, len(remaining), 2):
            rows.append(remaining[i:i + 2])
        rows.append([InlineKeyboardButton("お前はどう思う？", callback_data="お前はどう思う？")])
        return InlineKeyboardMarkup(rows)

    if "get_predictions" in used_set:
        # After predictions — offer deep dive options
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("展開予想", callback_data="展開は？"),
             InlineKeyboardButton("騎手分析", callback_data="騎手の成績は？")],
            [InlineKeyboardButton("血統分析", callback_data="血統は？"),
             InlineKeyboardButton("過去走", callback_data="過去の成績は？")],
            [InlineKeyboardButton("全部掘り下げて", callback_data="全部掘り下げて")],
            [InlineKeyboardButton("お前はどう思う？", callback_data="お前はどう思う？")],
        ])

    if "get_race_entries" in used_set:
        # After entry list — offer prediction + odds
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("予想して", callback_data="予想して"),
             InlineKeyboardButton("オッズは？", callback_data="オッズ見せて")],
        ])

    return None


def get_start_buttons() -> InlineKeyboardMarkup:
    """Buttons shown after /start and onboarding."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("今日のJRA", callback_data="今日のJRA"),
         InlineKeyboardButton("今日の地方競馬", callback_data="今日の地方競馬")],
        [InlineKeyboardButton("ディーロジって？", callback_data="about")],
    ])


# ---------------------------------------------------------------------------
# Core message processing (shared by handle_message and handle_callback)
# ---------------------------------------------------------------------------

async def _process_and_reply(
    user_id: int,
    first_name: str,
    user_text: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Run the agentic loop and send the final response with contextual buttons."""
    user_context = build_user_context(user_id, first_name)
    system = build_system_prompt(user_context)

    history = user_conversations.get(user_id, [])
    history = trim_history(history)
    history.append({"role": "user", "content": user_text})

    try:
        tools_used = []
        notified_tools = set()
        response = None
        loop = asyncio.get_event_loop()

        for turn in range(MAX_TOOL_TURNS):
            response = await loop.run_in_executor(
                None, partial(call_claude, history, system)
            )

            if response.stop_reason == "end_turn":
                history.append({"role": "assistant", "content": response.content})
                break

            tool_blocks = get_tool_blocks(response)
            if not tool_blocks:
                history.append({"role": "assistant", "content": response.content})
                break

            history.append({"role": "assistant", "content": response.content})

            # Notify user about tools (skip already-notified)
            new_tool_names = [tb.name for tb in tool_blocks if tb.name not in notified_tools]
            if new_tool_names:
                notification = format_tool_notification(new_tool_names)
                await context.bot.send_message(chat_id=chat_id, text=notification)
                for name in new_tool_names:
                    notified_tools.add(name)

            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

            tool_results = []
            for tool_block in tool_blocks:
                tools_used.append(tool_block.name)
                logger.info(f"Executing tool: {tool_block.name}")
                result = await loop.run_in_executor(
                    None, partial(execute_tool, tool_block.name, tool_block.input)
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                })

            history.append({"role": "user", "content": tool_results})
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Extract final text
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

        # Auto-extract memories (best-effort)
        try:
            new_memories = await loop.run_in_executor(
                None, partial(extract_memories, user_text, response_text)
            )
            if new_memories:
                add_memories(user_id, new_memories)
                logger.info(f"New memories for user {user_id}: {new_memories}")
        except Exception:
            pass

        # Contextual buttons
        buttons = get_context_buttons(tools_used)

        # Send response (split if too long, attach buttons to last chunk)
        if len(response_text) > 4000:
            chunks = [response_text[i:i + 4000] for i in range(0, len(response_text), 4000)]
            for i, chunk in enumerate(chunks):
                markup = buttons if i == len(chunks) - 1 else None
                await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=markup)
        else:
            await context.bot.send_message(
                chat_id=chat_id, text=response_text, reply_markup=buttons
            )

    except Exception as e:
        logger.exception(f"Error processing message for user {user_id}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？",
        )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user

    # Prevent duplicate /start within 5 seconds
    now = time.time()
    if user.id in _last_start and now - _last_start[user.id] < 5:
        logger.info(f"Ignoring duplicate /start from user {user.id}")
        return
    _last_start[user.id] = now

    # Reset conversation but keep memory
    user_conversations.pop(user.id, None)

    mem = get_or_create_user(user.id, user.first_name)

    if mem["visits"] > 1 and mem.get("memories"):
        await update.message.reply_text(
            f"おっ、{user.first_name}！おかえり！\n\n"
            "今日はどのレースが気になる？",
            reply_markup=PERSISTENT_KEYBOARD,
        )
    elif mem["visits"] > 1:
        await update.message.reply_text(
            f"よう、{user.first_name}！また来てくれたね！\n\n"
            "今日はどのレースいく？気軽に聞いてね！",
            reply_markup=PERSISTENT_KEYBOARD,
        )
    else:
        # First visit — show onboarding + persistent keyboard
        await update.message.reply_text(
            f"よう、{user.first_name}！はじめまして！\n\n"
            "俺はディーロジ。お前の競馬の相棒だ。",
            reply_markup=PERSISTENT_KEYBOARD,
        )
        await update.message.reply_text(
            ONBOARDING_TEXT,
            reply_markup=get_start_buttons(),
        )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command - clear conversation history."""
    user_id = update.effective_user.id
    user_conversations.pop(user_id, None)
    await update.message.reply_text("了解、会話リセットしたよ！記憶は残してるからね。")


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /memory command - show what the bot remembers about the user."""
    uid = str(update.effective_user.id)
    if uid in user_memory and user_memory[uid].get("memories"):
        memories = user_memory[uid]["memories"]
        text = f"あなたについて覚えていること ({len(memories)}件):\n\n"
        for i, m in enumerate(memories, 1):
            text += f"{i}. {m}\n"
        text += "\n/forget で全部忘れるよ。"
    else:
        text = "まだあなたのことはあまり知らないな。もっと話そう！"
    await update.message.reply_text(text)


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /forget command - clear user memories."""
    uid = str(update.effective_user.id)
    if uid in user_memory:
        user_memory[uid]["memories"] = []
        save_memory()
    await update.message.reply_text("了解、記憶をリセットしたよ。またイチから覚えていくね！")


# ---------------------------------------------------------------------------
# Message & callback handlers
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages with async agentic loop."""
    user_text = update.message.text
    if not user_text:
        return

    await update.message.chat.send_action("typing")
    await _process_and_reply(
        update.effective_user.id,
        update.effective_user.first_name or "ゲスト",
        user_text,
        update.message.chat_id,
        context,
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()

    text = query.data
    user = query.from_user
    chat_id = query.message.chat_id

    # "About" button — show onboarding
    if text == "about":
        await context.bot.send_message(
            chat_id=chat_id,
            text=ONBOARDING_TEXT,
            reply_markup=get_start_buttons(),
        )
        return

    # Everything else — process as a user message
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    await _process_and_reply(user.id, user.first_name or "ゲスト", text, chat_id, context)


async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route persistent keyboard button presses."""
    text = update.message.text
    if text == "メモリ確認":
        return await memory_command(update, context)
    elif text == "会話リセット":
        return await reset_command(update, context)
    elif text == "ディーロジって？":
        await update.message.reply_text(
            ONBOARDING_TEXT,
            reply_markup=get_start_buttons(),
        )
        return
    return await handle_message(update, context)


# ---------------------------------------------------------------------------
# Bot commands menu & app factory
# ---------------------------------------------------------------------------

async def post_init(app: Application) -> None:
    """Set bot commands menu after initialization."""
    await app.bot.set_my_commands([
        BotCommand("start", "最初から始める"),
        BotCommand("reset", "会話をリセット"),
        BotCommand("memory", "覚えていることを確認"),
        BotCommand("forget", "記憶をリセット"),
    ])


def create_app() -> Application:
    """Create and configure the Telegram bot application."""
    load_memory()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("forget", forget_command))

    # Inline button callback handler
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Persistent keyboard button handler
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^(メモリ確認|会話リセット|ディーロジって？)$"),
        handle_keyboard_button,
    ))

    # General text message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
