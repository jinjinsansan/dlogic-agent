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
from agent.response_cache import (
    detect_query_type, find_race_id,
    get as get_cached_response, save as save_cached_response,
    TOOL_QUERY_MAP,
)
from config import TELEGRAM_BOT_TOKEN, MAX_TOOL_TURNS, ONBOARDING_TEXT, ADMIN_TELEGRAM_IDS
from tools.executor import execute_tool
from db.user_manager import (
    is_maintenance_mode, set_maintenance, get_maintenance_message,
    activate_users, get_waitlist_count, get_active_count, get_total_user_count,
)
from db.supabase_client import get_client as get_supabase

# Admin chat IDs (jin + authorized admins)
ADMIN_CHAT_ID = 197618639  # kept for backward compat (notification target)

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

    if "get_today_races" in used_set:
        # After race list — offer to pick a race
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("メインレースを見る", callback_data="メインレースの出馬表見せて")],
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

async def _send_response(chat_id, text, buttons, context):
    """Send response, splitting if too long."""
    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for i, chunk in enumerate(chunks):
            markup = buttons if i == len(chunks) - 1 else None
            await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=buttons)


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

    # ── Pre-loop cache check (button case: race_id already in history) ──
    query_type = detect_query_type(user_text)
    if query_type:
        race_id = find_race_id(history)
        if race_id:
            cached = get_cached_response(race_id, query_type)
            if cached:
                logger.info(f"Pre-loop cache hit: {race_id}:{query_type} user={user_id}")
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": cached["text"]})
                user_conversations[user_id] = history

                full_text = cached["text"]
                if cached["footer"]:
                    full_text += "\n\n" + cached["footer"]
                buttons = get_context_buttons(cached["tools_used"])
                await _send_response(chat_id, full_text, buttons, context)
                return

    history.append({"role": "user", "content": user_text})

    try:
        tools_used = []
        notified_tools = set()
        response = None
        active_race_id = None
        cache_used = False
        ev_loop = asyncio.get_event_loop()

        for turn in range(MAX_TOOL_TURNS):
            response = await ev_loop.run_in_executor(
                None, partial(call_claude, history, system)
            )

            if response.stop_reason == "end_turn":
                history.append({"role": "assistant", "content": response.content})
                break

            tool_blocks = get_tool_blocks(response)
            if not tool_blocks:
                history.append({"role": "assistant", "content": response.content})
                break

            # ── Mid-loop cache check: cacheable tool about to run? ──
            mid_cache = None
            for tb in tool_blocks:
                inp = tb.input if isinstance(tb.input, dict) else {}
                rid = inp.get("race_id")
                if rid:
                    active_race_id = rid
                qt = TOOL_QUERY_MAP.get(tb.name)
                if rid and qt:
                    mid_cache = get_cached_response(rid, qt)
                    if mid_cache:
                        break

            if mid_cache:
                # Cache hit — skip tool execution and remaining API calls
                logger.info(f"Mid-loop cache hit: {active_race_id} user={user_id}")
                history.append({"role": "assistant", "content": mid_cache["text"]})
                tools_used = mid_cache["tools_used"]
                cache_used = True
                break

            # Normal flow — append assistant message, execute tools
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
                inp = tool_block.input if isinstance(tool_block.input, dict) else {}
                if inp.get("race_id"):
                    active_race_id = inp["race_id"]
                logger.info(f"Executing tool: {tool_block.name}")
                result = await ev_loop.run_in_executor(
                    None, partial(execute_tool, tool_block.name, tool_block.input)
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                })

            history.append({"role": "user", "content": tool_results})
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Build final response text
        if cache_used:
            response_text = mid_cache["text"]
            footer = mid_cache["footer"]
        else:
            if response:
                response_text = extract_text(response)
            else:
                response_text = "ごめん、ちょっと調べすぎちゃった。"
            if not response_text:
                response_text = "ごめん、うまく答えられなかった。もう一回聞いてもらえる？"
            footer = format_tools_used_footer(tools_used)

        full_text = response_text + ("\n\n" + footer if footer else "")
        user_conversations[user_id] = history

        # ── Post-loop: save to response cache ──
        if not cache_used and active_race_id:
            save_qt = detect_query_type(user_text)
            if save_qt:
                save_cached_response(active_race_id, save_qt, response_text, footer, tools_used)

        # Auto-extract memories (skip if cache was used — no new content)
        if not cache_used:
            try:
                new_memories = await ev_loop.run_in_executor(
                    None, partial(extract_memories, user_text, response_text)
                )
                if new_memories:
                    add_memories(user_id, new_memories)
                    logger.info(f"New memories for user {user_id}: {new_memories}")
            except Exception:
                pass

        # Contextual buttons + send
        buttons = get_context_buttons(tools_used)
        await _send_response(chat_id, full_text, buttons, context)

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
async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's Telegram ID."""
    uid = update.effective_user.id
    await update.message.reply_text(f"あなたのTelegram ID: `{uid}`", parse_mode="Markdown")
    logger.info(f"/myid from user {uid} ({update.effective_user.first_name})")


# Admin commands (Telegram only — for managing LINE Bot)
# ---------------------------------------------------------------------------

def _is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_TELEGRAM_IDS


async def maintenance_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle maintenance ON. Usage: /maintenance_on [message]"""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return
    custom_msg = " ".join(context.args) if context.args else None
    set_maintenance(True, custom_msg)
    msg = get_maintenance_message()
    await update.message.reply_text(
        f"🔧 メンテナンスモード ON\n\n"
        f"LINE Botへの全メッセージがブロックされます。\n"
        f"表示メッセージ: {msg}\n\n"
        f"/maintenance_off で解除"
    )


async def maintenance_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle maintenance OFF."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return
    set_maintenance(False)
    await update.message.reply_text("✅ メンテナンスモード OFF\nLINE Bot通常稼働に復帰しました。")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot status: maintenance, user counts."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return
    maint = is_maintenance_mode()
    total = get_total_user_count()
    active = get_active_count()
    waitlist = get_waitlist_count()
    await update.message.reply_text(
        f"📊 LINE Bot ステータス\n"
        f"━━━━━━━━━━━━━━━\n"
        f"メンテナンス: {'🔧 ON' if maint else '✅ OFF'}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"総ユーザー数: {total}\n"
        f"アクティブ: {active}\n"
        f"ウェイトリスト: {waitlist}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"コマンド一覧:\n"
        f"/maintenance_on [msg] - メンテON\n"
        f"/maintenance_off - メンテOFF\n"
        f"/activate [数] - ウェイトリスト解除\n"
        f"/activate_all - 全員アクティベート"
    )


async def activate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate N users from waitlist. Usage: /activate 10"""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return

    count = 10  # default
    if context.args:
        try:
            count = int(context.args[0])
        except ValueError:
            await update.message.reply_text("数値を指定してください: /activate 10")
            return

    activated = activate_users(count)
    if not activated:
        await update.message.reply_text("ウェイトリストに待機ユーザーがいません。")
        return

    names = "\n".join([f"  • {u['display_name']}" for u in activated])
    remaining = get_waitlist_count()
    await update.message.reply_text(
        f"✅ {len(activated)}人をアクティベートしました！\n\n"
        f"{names}\n\n"
        f"残りウェイトリスト: {remaining}人"
    )

    # Send activation notification to each user via LINE
    import time as _time
    from bot.line_handlers import _push, get_start_quick_reply
    from config import ONBOARDING_TEXT
    notified = 0
    for user in activated:
        line_uid = user.get("line_user_id", "")
        if not line_uid or line_uid.startswith("login_"):
            logger.info(f"Skip notification (no LINE ID): {user['display_name']}")
            continue
        try:
            _push(
                line_uid,
                "よう、待たせたな！🔥\n\n"
                "お前の順番が来たぜ。今日から俺と一緒に勝ちにいこう！\n\n"
                + ONBOARDING_TEXT,
                quick_reply=get_start_quick_reply(),
            )
            notified += 1
            logger.info(f"Activation push sent: {user['display_name']}")
            _time.sleep(0.3)
        except Exception:
            logger.exception(f"Failed to notify activated user: {user['display_name']}")
    await update.message.reply_text(f"📨 LINE通知: {notified}/{len(activated)}人に送信")


async def inquiries_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List open inquiries."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return

    sb = get_supabase()
    res = sb.table("inquiries") \
        .select("id, display_name, content, created_at") \
        .eq("status", "open") \
        .order("created_at", desc=False) \
        .limit(20) \
        .execute()

    if not res.data:
        await update.message.reply_text("✅ 未対応の問い合わせはありません。")
        return

    text = f"📩 未対応の問い合わせ ({len(res.data)}件)\n━━━━━━━━━━━━━━━\n\n"
    for item in res.data:
        created = item["created_at"][:16].replace("T", " ")
        content = item["content"][:50]
        text += f"#{item['id']} {item['display_name']}\n"
        text += f"  {content}\n"
        text += f"  {created}\n\n"
    text += "対応完了: /resolve <ID>"
    await update.message.reply_text(text)


async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve an inquiry and notify user. Usage: /resolve <id> [message]"""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return

    if not context.args:
        await update.message.reply_text("使い方: /resolve <ID> [メッセージ]")
        return

    try:
        inquiry_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("IDは数値で指定してください。")
        return

    admin_note = " ".join(context.args[1:]) if len(context.args) > 1 else ""

    # Get inquiry from Supabase
    sb = get_supabase()
    res = sb.table("inquiries") \
        .select("*") \
        .eq("id", inquiry_id) \
        .limit(1) \
        .execute()

    if not res.data:
        await update.message.reply_text(f"ID #{inquiry_id} の問い合わせが見つかりません。")
        return

    inquiry = res.data[0]
    if inquiry["status"] == "resolved":
        await update.message.reply_text(f"#{inquiry_id} は既に対応済みです。")
        return

    # Update status
    from datetime import datetime, timezone
    sb.table("inquiries") \
        .update({
            "status": "resolved",
            "admin_note": admin_note,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }) \
        .eq("id", inquiry_id) \
        .execute()

    # Notify user via LINE push (ディーロジのキャラで回答を包む)
    line_user_id = inquiry.get("line_user_id")
    user_name = inquiry.get("display_name", "")
    notified = False
    if line_user_id:
        try:
            from bot.line_handlers import _push, get_start_quick_reply
            if admin_note:
                msg = (
                    f"おう{user_name}！運営から回答が来たぜ 💬\n\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{admin_note}\n"
                    f"━━━━━━━━━━━━━━━\n\n"
                    f"わかったか？他にも聞きたいことがあったら気軽に言ってくれ！👊"
                )
            else:
                msg = (
                    f"おう{user_name}！お前の問い合わせ、運営が確認してくれたぜ！👊\n\n"
                    "また何かあったらいつでも言ってくれ！"
                )
            _push(line_user_id, msg, quick_reply=get_start_quick_reply())
            notified = True
        except Exception:
            logger.warning(f"Failed to notify user for inquiry #{inquiry_id}")

    await update.message.reply_text(
        f"✅ #{inquiry_id} を対応済みにしました。\n"
        f"ユーザー: {user_name}\n"
        f"LINE通知: {'送信済み' if notified else '失敗'}"
    )


async def mybot_inquiries_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List open MYBOT inquiries."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return

    sb = get_supabase()
    res = sb.table("mybot_inquiries") \
        .select("id, bot_name, sender_name, content, created_at") \
        .eq("status", "open") \
        .order("created_at", desc=False) \
        .limit(20) \
        .execute()

    if not res.data:
        await update.message.reply_text("✅ MYBOT未対応の問い合わせはありません。")
        return

    text = f"📩 MYBOT問い合わせ ({len(res.data)}件)\n━━━━━━━━━━━━━━━\n\n"
    for item in res.data:
        created = item["created_at"][:16].replace("T", " ")
        content = item["content"][:50]
        text += f"#{item['id']} [{item['bot_name']}] {item['sender_name']}\n"
        text += f"  {content}\n"
        text += f"  {created}\n\n"
    text += "対応完了: /resolve_mybot <ID> [メッセージ]"
    await update.message.reply_text(text)


async def resolve_mybot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve a MYBOT inquiry and notify user via their BOT's LINE channel.

    Usage: /resolve_mybot <id> [message]
    """
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return

    if not context.args:
        await update.message.reply_text("使い方: /resolve_mybot <ID> [メッセージ]")
        return

    try:
        inquiry_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("IDは数値で指定してください。")
        return

    admin_note = " ".join(context.args[1:]) if len(context.args) > 1 else ""

    sb = get_supabase()
    res = sb.table("mybot_inquiries") \
        .select("*") \
        .eq("id", inquiry_id) \
        .limit(1) \
        .execute()

    if not res.data:
        await update.message.reply_text(f"ID #{inquiry_id} のMYBOT問い合わせが見つかりません。")
        return

    inquiry = res.data[0]
    if inquiry["status"] == "resolved":
        await update.message.reply_text(f"#{inquiry_id} は既に対応済みです。")
        return

    # Update status
    from datetime import datetime, timezone
    sb.table("mybot_inquiries") \
        .update({
            "status": "resolved",
            "admin_note": admin_note,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }) \
        .eq("id", inquiry_id) \
        .execute()

    # Notify user via the BOT owner's LINE channel
    sender_line_id = inquiry.get("sender_line_id")
    bot_owner_id = inquiry.get("bot_owner_id")
    sender_name = inquiry.get("sender_name", "")
    bot_name = inquiry.get("bot_name", "MYBOT")
    notified = False

    if sender_line_id and bot_owner_id:
        try:
            from db.encryption import decrypt_value
            ch_res = sb.table("mybot_line_channels") \
                .select("access_token_enc") \
                .eq("user_id", bot_owner_id) \
                .limit(1) \
                .execute()

            if ch_res.data:
                access_token = decrypt_value(ch_res.data[0]["access_token_enc"])

                if admin_note:
                    msg = (
                        f"Dlogic運営本部から回答が届きました！\n\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{admin_note}\n"
                        f"━━━━━━━━━━━━━━━\n\n"
                        f"他にもご質問があればお気軽にどうぞ！"
                    )
                else:
                    msg = (
                        f"Dlogic運営本部がお問い合わせを確認しました！\n\n"
                        f"また何かありましたらお気軽にどうぞ！"
                    )

                from bot.mybot_line_handler import _push as mybot_push
                mybot_push(access_token, sender_line_id, msg)
                notified = True
        except Exception:
            logger.warning(f"Failed to notify MYBOT user for inquiry #{inquiry_id}")

    await update.message.reply_text(
        f"✅ MYBOT #{inquiry_id} を対応済みにしました。\n"
        f"BOT: {bot_name}\n"
        f"ユーザー: {sender_name}\n"
        f"LINE通知: {'送信済み' if notified else '失敗'}"
    )


async def activate_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate ALL waitlisted users."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ 管理者のみ使用可能です。")
        return

    waitlist = get_waitlist_count()
    if waitlist == 0:
        await update.message.reply_text("ウェイトリストに待機ユーザーがいません。")
        return

    activated = activate_users(waitlist)
    await update.message.reply_text(
        f"✅ 全 {len(activated)}人をアクティベートしました！\n\n"
        f"LINE通知を送信中..."
    )

    # Send activation notifications
    import time as _time
    from bot.line_handlers import _push, get_start_quick_reply
    from config import ONBOARDING_TEXT
    success = 0
    for user in activated:
        line_uid = user.get("line_user_id", "")
        if not line_uid or line_uid.startswith("login_"):
            logger.info(f"Skip notification (no LINE ID): {user['display_name']}")
            continue
        try:
            _push(
                line_uid,
                "よう、待たせたな！🔥\n\n"
                "お前の順番が来たぜ。今日から俺と一緒に勝ちにいこう！\n\n"
                + ONBOARDING_TEXT,
                quick_reply=get_start_quick_reply(),
            )
            success += 1
            logger.info(f"Activation push sent: {user['display_name']}")
            _time.sleep(0.3)
        except Exception:
            logger.exception(f"Failed to notify activated user: {user['display_name']}")

    await update.message.reply_text(f"📨 LINE通知完了: {success}/{len(activated)}人に送信")


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
        BotCommand("status", "LINE Botステータス確認"),
        BotCommand("maintenance_on", "メンテナンスON"),
        BotCommand("maintenance_off", "メンテナンスOFF"),
        BotCommand("activate", "ウェイトリスト解除"),
        BotCommand("activate_all", "全員アクティベート"),
        BotCommand("inquiries", "未対応の問い合わせ一覧"),
        BotCommand("resolve", "問い合わせ対応完了"),
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

    app.add_handler(CommandHandler("myid", myid_command))

    # Admin commands (LINE Bot management from Telegram)
    app.add_handler(CommandHandler("maintenance_on", maintenance_on_command))
    app.add_handler(CommandHandler("maintenance_off", maintenance_off_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("activate", activate_command))
    app.add_handler(CommandHandler("activate_all", activate_all_command))
    app.add_handler(CommandHandler("inquiries", inquiries_command))
    app.add_handler(CommandHandler("resolve", resolve_command))
    app.add_handler(CommandHandler("mybot_inquiries", mybot_inquiries_command))
    app.add_handler(CommandHandler("resolve_mybot", resolve_mybot_command))

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
