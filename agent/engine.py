"""Claude API agent engine with tool use support."""

import logging

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, SYSTEM_PROMPT, MAX_TOKENS
from tools.definitions import TOOLS

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MEMORY_EXTRACT_PROMPT = """以下のユーザーとアシスタントの会話から、ユーザーについて覚えておくべき情報を抽出してください。

抽出すべき情報:
- 名前、ニックネーム
- 競馬の好み（中央/地方、好きな競馬場、好きな馬、好きな騎手）
- 馬券の買い方の好み（単勝派、三連複派、穴狙い、堅実派など）
- 性格や会話スタイルの特徴
- その他、次回の会話で活かせる個人的な情報

出力形式: 覚えるべきことが「ある場合のみ」、1行1項目で簡潔に出力。
なければ「なし」とだけ出力。
余計な説明や前置きは不要。

会話:
"""

# Tool display names for user-facing notifications
TOOL_LABELS = {
    "get_today_races": "レース一覧取得",
    "get_race_entries": "出馬表取得",
    "get_predictions": "予想エンジン (Dlogic/Ilogic/ViewLogic/MetaLogic)",
    "get_realtime_odds": "リアルタイムオッズ取得",
    "search_horse": "馬データ検索",
    "get_race_flow": "展開予想エンジン",
    "get_jockey_analysis": "騎手分析エンジン",
    "get_bloodline_analysis": "血統分析エンジン",
    "get_recent_runs": "直近5走エンジン",
    "record_user_prediction": "本命登録",
    "check_user_prediction": "本命確認",
    "get_my_stats": "成績確認",
    "get_prediction_ranking": "ランキング取得",
    "get_odds_probability": "予測勝率算出",
    "get_stable_comments": "関係者情報取得",
    "get_horse_weights": "馬体重取得",
    "get_training_comments": "調教情報取得",
    "get_engine_stats": "エンジン的中率確認",
    "send_inquiry": "問い合わせ送信",
}

# Tools that involve heavy engine computation (notify user about wait time)
HEAVY_TOOLS = {
    "get_predictions", "get_race_flow", "get_jockey_analysis",
    "get_bloodline_analysis", "get_recent_runs",
}


def call_claude(conversation_history: list[dict], system: str) -> object:
    """Single Claude API call with prompt caching."""
    return client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=TOOLS,
        messages=conversation_history,
    )


def build_system_prompt(user_context: str = "") -> str:
    """Build full system prompt with optional user context."""
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][now.weekday()]
    date_line = f"\n\n## 現在の日時\n{now.strftime('%Y年%m月%d日')}（{weekday_ja}） {now.strftime('%H:%M')} JST"
    system = SYSTEM_PROMPT + date_line
    if user_context:
        system = system + "\n\n" + user_context
    return system


def extract_text(response) -> str:
    """Extract text parts from a Claude response."""
    text_parts = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_parts)


def get_tool_blocks(response) -> list:
    """Extract tool use blocks from a Claude response."""
    return [b for b in response.content if b.type == "tool_use"]


def format_tool_notification(tool_names: list[str]) -> str:
    """Generate a user-friendly notification about which tools are being used."""
    labels = []
    for name in tool_names:
        label = TOOL_LABELS.get(name, name)
        labels.append(label)

    has_heavy = any(name in HEAVY_TOOLS for name in tool_names)

    if has_heavy:
        msg = "⚡ エンジン起動中...\n"
        msg += "\n".join(f"  → {l}" for l in labels)
        msg += "\n少し待ってな（10〜30秒くらい）"
    else:
        msg = "🔍 データ取得中...\n"
        msg += "\n".join(f"  → {l}" for l in labels)

    return msg


_UTILITY_TOOLS = {
    "get_my_stats", "get_prediction_ranking", "record_user_prediction",
    "check_user_prediction", "get_engine_stats", "send_inquiry",
}


def format_tools_used_footer(tools_used: list[str]) -> str:
    """Generate a footer showing which tools/engines were used."""
    if not tools_used:
        return ""

    # Deduplicate while preserving order, skip utility tools
    seen = set()
    unique = []
    for t in tools_used:
        if t not in seen and t not in _UTILITY_TOOLS:
            seen.add(t)
            unique.append(t)

    if not unique:
        return ""

    labels = [TOOL_LABELS.get(t, t) for t in unique]
    has_engine = any(t in HEAVY_TOOLS for t in unique)

    if has_engine:
        return "─────────────\n⚡ 使用エンジン: " + "、".join(labels)
    else:
        return "─────────────\n🔍 使用データ: " + "、".join(labels)


def extract_memories(user_message: str, assistant_response: str) -> list[str]:
    """
    Use Claude to extract memorable facts from a conversation turn.
    Returns a list of memory strings, or empty list.
    """
    try:
        conversation_text = f"ユーザー: {user_message}\nアシスタント: {assistant_response}"

        response = client.messages.create(
            model="claude-haiku-4-5",  # Always use Haiku for memory extraction (cheap)
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": MEMORY_EXTRACT_PROMPT + conversation_text,
            }],
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        text = text.strip()
        if text == "なし" or not text:
            return []

        # Split into individual memories
        memories = [line.strip().lstrip("- ・•") for line in text.split("\n") if line.strip()]
        return [m for m in memories if m and m != "なし"]

    except Exception:
        return []


def trim_history(conversation_history: list[dict], max_turns: int = 10) -> list[dict]:
    """Trim conversation history to keep only the last N turns to manage context size."""
    if len(conversation_history) <= max_turns * 2:
        return conversation_history

    trimmed = conversation_history[-(max_turns * 2):]
    if trimmed and trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed
