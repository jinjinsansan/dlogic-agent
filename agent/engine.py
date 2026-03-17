"""Agent engine with tool use support — supports Claude and OpenAI-compatible models."""

import json
import logging
import uuid

import anthropic

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, SYSTEM_PROMPT, MAX_TOKENS,
    LLM_PROVIDER,
)
from tools.definitions import TOOLS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_openai_client = None
def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        from config import OPENAI_API_KEY
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


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
    "get_race_results": "レース結果取得",
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


# ---------------------------------------------------------------------------
# Anthropic → OpenAI format converters
# ---------------------------------------------------------------------------

def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function format."""
    result = []
    for tool in tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return result


def _anthropic_history_to_openai(history: list[dict], system: str) -> list[dict]:
    """Convert Anthropic-format conversation history to OpenAI format.

    Anthropic format:
      - {"role": "user", "content": "text" | [{"type": "text", ...}]}
      - {"role": "assistant", "content": [ContentBlock, ...]}  (may contain tool_use)
      - {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": ...}]}

    OpenAI format:
      - {"role": "system", "content": "text"}
      - {"role": "user", "content": "text"}
      - {"role": "assistant", "content": "text", "tool_calls": [...]}
      - {"role": "tool", "tool_call_id": ..., "content": "text"}
    """
    messages = [{"role": "system", "content": system}]

    for msg in history:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "user":
            # Could be plain text or list of content blocks
            if isinstance(content, str):
                messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Check if this is a tool_result list
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                if tool_results:
                    for tr in tool_results:
                        tool_content = tr.get("content", "")
                        if isinstance(tool_content, list):
                            # Extract text from content blocks
                            tool_content = "\n".join(
                                b.get("text", str(b)) for b in tool_content if isinstance(b, dict)
                            )
                        if not isinstance(tool_content, str):
                            tool_content = json.dumps(tool_content, ensure_ascii=False)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tr.get("tool_use_id", ""),
                            "content": tool_content,
                        })
                else:
                    # Text content blocks
                    text_parts = []
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            text_parts.append(b.get("text", ""))
                        elif isinstance(b, str):
                            text_parts.append(b)
                    messages.append({"role": "user", "content": "\n".join(text_parts) or str(content)})
            else:
                messages.append({"role": "user", "content": str(content)})

        elif role == "assistant":
            # Content could be a list of ContentBlocks (Anthropic objects or dicts)
            text_parts = []
            tool_calls = []

            if isinstance(content, list):
                for block in content:
                    # Handle both Anthropic SDK objects and plain dicts
                    btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)

                    if btype == "text":
                        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "")
                        if text:
                            text_parts.append(text)
                    elif btype == "tool_use":
                        tool_id = getattr(block, "id", None) or (block.get("id") if isinstance(block, dict) else str(uuid.uuid4()))
                        tool_name = getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else "")
                        tool_input = getattr(block, "input", None) or (block.get("input") if isinstance(block, dict) else {})
                        tool_calls.append({
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_input, ensure_ascii=False),
                            },
                        })
            elif isinstance(content, str):
                text_parts.append(content)

            assistant_msg = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

    return messages


# ---------------------------------------------------------------------------
# Unified response wrapper (makes OpenAI responses look like Anthropic)
# ---------------------------------------------------------------------------

class _ContentBlock:
    """Mimics Anthropic's ContentBlock for compatibility."""
    def __init__(self, block_type, **kwargs):
        self.type = block_type
        for k, v in kwargs.items():
            setattr(self, k, v)


class _UnifiedResponse:
    """Wraps an OpenAI response to look like an Anthropic response."""
    def __init__(self, openai_response):
        self._raw = openai_response
        choice = openai_response.choices[0]
        message = choice.message

        # Build content blocks (Anthropic-style)
        self.content = []
        if message.content:
            self.content.append(_ContentBlock("text", text=message.content))
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                self.content.append(_ContentBlock(
                    "tool_use",
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        # Map stop reason
        if choice.finish_reason == "tool_calls":
            self.stop_reason = "tool_use"
        else:
            self.stop_reason = "end_turn"


# ---------------------------------------------------------------------------
# Cached OpenAI tools
# ---------------------------------------------------------------------------

_openai_tools_cache = None
def _get_openai_tools():
    global _openai_tools_cache
    if _openai_tools_cache is None:
        _openai_tools_cache = _anthropic_tools_to_openai(TOOLS)
    return _openai_tools_cache


# ---------------------------------------------------------------------------
# Public API (same interface regardless of provider)
# ---------------------------------------------------------------------------

def call_claude(conversation_history: list[dict], system: str, tools: list[dict] | None = None) -> object:
    """Single LLM API call with tool use. Dispatches to Claude or OpenAI."""
    if LLM_PROVIDER == "openai":
        return _call_openai(conversation_history, system)
    else:
        return _call_anthropic(conversation_history, system, tools=tools)


def _call_anthropic(conversation_history: list[dict], system: str, tools: list[dict] | None = None) -> object:
    """Claude API call with prompt caching."""
    return _anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=tools or TOOLS,
        messages=conversation_history,
    )


def _call_openai(conversation_history: list[dict], system: str) -> object:
    """OpenAI-compatible API call, returns Anthropic-compatible response."""
    from config import OPENAI_MODEL
    client = _get_openai_client()
    messages = _anthropic_history_to_openai(conversation_history, system)
    openai_response = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=MAX_TOKENS,
        messages=messages,
        tools=_get_openai_tools(),
    )
    return _UnifiedResponse(openai_response)


# ---------------------------------------------------------------------------
# Dynamic tool selection — reduce input tokens by sending only relevant tools
# ---------------------------------------------------------------------------

# Phase 1 tools: needed when user hasn't selected a race yet
_PHASE1_TOOL_NAMES = {
    "get_today_races", "get_race_entries", "search_horse",
    "get_my_stats", "get_prediction_ranking", "get_engine_stats", "send_inquiry",
}

# Phase 2 tools: needed after a race is selected (analysis + data)
_PHASE2_TOOL_NAMES = {
    "get_predictions", "get_race_results", "get_realtime_odds", "get_horse_weights",
    "get_training_comments", "get_race_flow", "get_jockey_analysis",
    "get_bloodline_analysis", "get_recent_runs", "get_odds_probability",
    "get_stable_comments", "record_user_prediction", "check_user_prediction",
}

# Tool index by name for fast lookup
_TOOL_BY_NAME = {t["name"]: t for t in TOOLS}


def select_tools(has_race_context: bool, user_message: str = "") -> list[dict]:
    """Select relevant tools based on conversation state to reduce token usage.

    - No race context: only phase 1 tools (~7 tools instead of 18)
    - Has race context: phase 2 tools + race list tools (for switching races)
    - Always includes utility tools (stats, inquiry)
    """
    if has_race_context:
        # Include all tools — user might want to switch races or analyze
        return TOOLS

    # No race context: skip analysis/data tools that require race_id
    # But check message for keywords that might need phase 2
    _RACE_HINTS = ("予想", "展開", "騎手", "血統", "過去", "オッズ", "馬体重", "勝率", "結果")
    if any(hint in user_message for hint in _RACE_HINTS):
        return TOOLS  # Might need everything

    return [_TOOL_BY_NAME[name] for name in _PHASE1_TOOL_NAMES if name in _TOOL_BY_NAME]


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
    """Extract text parts from a response."""
    text_parts = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_parts)


def get_tool_blocks(response) -> list:
    """Extract tool use blocks from a response."""
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
    Extract memorable facts from a conversation turn.
    Uses the same provider as the main LLM.
    """
    try:
        conversation_text = f"ユーザー: {user_message}\nアシスタント: {assistant_response}"

        if LLM_PROVIDER == "openai":
            from config import OPENAI_MODEL
            client = _get_openai_client()
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": MEMORY_EXTRACT_PROMPT + conversation_text},
                ],
            )
            text = response.choices[0].message.content or ""
        else:
            response = _anthropic_client.messages.create(
                model="claude-haiku-4-5",
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

        memories = [line.strip().lstrip("- ・•") for line in text.split("\n") if line.strip()]
        return [m for m in memories if m and m != "なし"]

    except Exception:
        return []


def _compress_tool_result(content: str, max_len: int = 800) -> str:
    """Compress a tool_result string to save tokens on subsequent API calls.

    Keeps the first max_len characters and appends a truncation notice.
    JSON results are truncated at a sensible boundary.
    """
    if not isinstance(content, str) or len(content) <= max_len:
        return content
    # Try to truncate at last complete JSON object/array boundary
    truncated = content[:max_len]
    # Add notice so Claude knows data was truncated
    return truncated + "\n...[データ省略]"


def _compress_old_tool_results(history: list[dict], keep_recent: int = 4) -> list[dict]:
    """Compress tool_result content in older messages to reduce input tokens.

    Keeps the most recent `keep_recent` messages untouched.
    Older tool_result blocks get their content truncated.
    """
    if len(history) <= keep_recent:
        return history

    compressed = []
    cutoff = len(history) - keep_recent

    for i, msg in enumerate(history):
        if i >= cutoff:
            # Recent messages: keep as-is
            compressed.append(msg)
            continue

        content = msg.get("content")
        if msg.get("role") == "user" and isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    block = dict(block)  # shallow copy
                    block["content"] = _compress_tool_result(block.get("content", ""))
                    new_blocks.append(block)
                else:
                    new_blocks.append(block)
            compressed.append({"role": msg["role"], "content": new_blocks})
        elif msg.get("role") == "assistant" and isinstance(content, list):
            # Compress tool_use input in old assistant messages too
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    block = dict(block)
                    inp = block.get("input", {})
                    if isinstance(inp, dict):
                        # Keep only race_id and race_type from old tool calls
                        minimal = {}
                        for k in ("race_id", "race_type", "horse_number", "horse_name"):
                            if k in inp:
                                minimal[k] = inp[k]
                        block["input"] = minimal or inp
                    new_blocks.append(block)
                else:
                    new_blocks.append(block)
            compressed.append({"role": msg["role"], "content": new_blocks})
        else:
            compressed.append(msg)

    return compressed


def trim_history(conversation_history: list[dict], max_turns: int = 10) -> list[dict]:
    """Trim conversation history to keep only the last N turns to manage context size.

    Ensures we never split tool_use/tool_result pairs, which would cause
    API 400 errors. Also compresses old tool results to save tokens.
    """
    if len(conversation_history) <= max_turns * 2:
        return _compress_old_tool_results(conversation_history)

    trimmed = conversation_history[-(max_turns * 2):]

    while trimmed:
        msg = trimmed[0]
        if msg["role"] != "user":
            trimmed = trimmed[1:]
            continue
        content = msg.get("content", "")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            trimmed = trimmed[1:]
            continue
        break

    return _compress_old_tool_results(trimmed)
