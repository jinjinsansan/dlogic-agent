"""Telegram bot handlers with async agentic loop for tool use notifications."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from functools import partial
from telegram import BotCommand, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from agent.engine import (
    call_claude, build_system_prompt, extract_text, get_tool_blocks,
    format_tool_notification, format_tools_used_footer,
    trim_history, extract_memories, HEAVY_TOOLS,
)
from config import TELEGRAM_BOT_TOKEN, MAX_TOOL_TURNS
from tools.executor import execute_tool

logger = logging.getLogger(__name__)

# In-memory conversation storage
user_conversations: dict[int, list[dict]] = {}

# Cooldown for /start to prevent duplicate messages
_last_start: dict[int, float] = {}

# User memory (persists to file)
MEMORY_DIR = "memory"
user_memory: dict[str, dict] = {}


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
            # Keep max 30 memories (oldest removed)
            if len(user_memory[uid]["memories"]) > 30:
                user_memory[uid]["memories"] = user_memory[uid]["memories"][-30:]

    save_memory()


def build_user_context(user_id: int, first_name: str) -> str:
    """Build user context string for the system prompt."""
    mem = get_or_create_user(user_id, first_name)

    lines = [f"【このユーザーについて】"]
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

    # Show persistent keyboard
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("今日のJRA"), KeyboardButton("今日の地方競馬")],
            [KeyboardButton("メモリ確認"), KeyboardButton("会話リセット")],
        ],
        resize_keyboard=True,
        input_field_placeholder="レース名や馬名を入力...",
    )

    if mem["visits"] > 1 and mem.get("memories"):
        await update.message.reply_text(
            f"おっ、{user.first_name}！おかえり！\n\n"
            "今日はどのレースが気になる？",
            reply_markup=keyboard,
        )
    elif mem["visits"] > 1:
        await update.message.reply_text(
            f"よう、{user.first_name}！また来てくれたね！\n\n"
            "今日はどのレースいく？気軽に聞いてね！",
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(
            f"よう、{user.first_name}！はじめまして！\n\n"
            "俺はディーロジ。お前の競馬の相棒だ。\n"
            "JRAも地方もどっちもいける。\n\n"
            "「今日のレース」とか「船橋11Rの予想」みたいに\n"
            "気軽に話しかけてくれればOK！\n\n"
            "エンジン使ってデータ調べたり、展開読んだり、\n"
            "全力でサポートするぜ。最後に決めるのはお前だけどな！",
            reply_markup=keyboard,
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages with async agentic loop."""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "ゲスト"
    user_text = update.message.text

    if not user_text:
        return

    # Build user context from memory
    user_context = build_user_context(user_id, first_name)
    system = build_system_prompt(user_context)

    # Get or create conversation history
    history = user_conversations.get(user_id, [])
    history = trim_history(history)

    # Append user message
    history.append({"role": "user", "content": user_text})

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        tools_used = []
        notified_tools = set()  # Track which tools we already notified about
        response = None
        loop = asyncio.get_event_loop()

        # Agentic loop: call Claude, execute tools, repeat
        for turn in range(MAX_TOOL_TURNS):
            # Call Claude API (sync → run in executor to not block event loop)
            response = await loop.run_in_executor(
                None, partial(call_claude, history, system)
            )

            # If Claude is done (no tool calls), break
            if response.stop_reason == "end_turn":
                history.append({"role": "assistant", "content": response.content})
                break

            # Extract tool use blocks
            tool_blocks = get_tool_blocks(response)

            if not tool_blocks:
                history.append({"role": "assistant", "content": response.content})
                break

            # Append assistant's response (including tool_use blocks)
            history.append({"role": "assistant", "content": response.content})

            # Notify user about tool usage BEFORE executing (skip already-notified tools)
            new_tool_names = [tb.name for tb in tool_blocks if tb.name not in notified_tools]
            if new_tool_names:
                notification = format_tool_notification(new_tool_names)
                await update.message.reply_text(notification)
                for name in new_tool_names:
                    notified_tools.add(name)

            # Show typing while tools execute
            await update.message.chat.send_action("typing")

            # Execute each tool (sync → run in executor)
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

            # Keep typing indicator for next Claude call
            await update.message.chat.send_action("typing")

        # Extract final response text
        if response:
            response_text = extract_text(response)
        else:
            response_text = "ごめん、ちょっと調べすぎちゃった。"

        if not response_text:
            response_text = "ごめん、うまく答えられなかった。もう一回聞いてもらえる？"

        # Add tool usage footer
        footer = format_tools_used_footer(tools_used)
        if footer:
            response_text = response_text + "\n\n" + footer

        # Save conversation
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

        # Split long messages (Telegram limit: 4096 chars)
        if len(response_text) > 4000:
            chunks = [response_text[i:i+4000] for i in range(0, len(response_text), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response_text)

    except Exception as e:
        logger.exception(f"Error processing message for user {user_id}")
        await update.message.reply_text(
            "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？"
        )


async def post_init(app: Application) -> None:
    """Set bot commands menu after initialization."""
    await app.bot.set_my_commands([
        BotCommand("start", "最初から始める"),
        BotCommand("reset", "会話をリセット"),
        BotCommand("memory", "覚えていることを確認"),
        BotCommand("forget", "記憶をリセット"),
    ])


async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route keyboard button presses to appropriate handlers."""
    text = update.message.text
    if text == "メモリ確認":
        return await memory_command(update, context)
    elif text == "会話リセット":
        return await reset_command(update, context)
    # Otherwise fall through to normal message handling
    return await handle_message(update, context)


def create_app() -> Application:
    """Create and configure the Telegram bot application."""
    load_memory()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("forget", forget_command))
    # Keyboard button handler (check specific texts first)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^(メモリ確認|会話リセット)$"),
        handle_keyboard_button,
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
