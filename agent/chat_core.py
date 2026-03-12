"""Shared agentic loop — used by both LINE Bot and WebApp chat.

Yields chunks as the conversation progresses:
  {"type": "thinking"}           — tool execution started
  {"type": "tool", "name": ...}  — tool being executed
  {"type": "text", "content": ...} — text chunk from Claude
  {"type": "done", "text": ..., "footer": ..., "tools_used": [...], "active_race_id": ...}
"""

import logging

from agent.engine import (
    call_claude, build_system_prompt, extract_text, get_tool_blocks,
    format_tools_used_footer, trim_history, extract_memories, HEAVY_TOOLS,
)
from agent.response_cache import (
    detect_query_type, find_race_id,
    get as get_cached_response, save as save_cached_response,
    TOOL_QUERY_MAP,
)
from agent.template_router import match_route, route_and_respond
from config import MAX_TOOL_TURNS
from db.user_manager import (
    get_memories as db_get_memories,
    add_memories as db_add_memories,
    build_user_context as db_build_user_context,
)
from db.prediction_manager import check_prediction as db_check_prediction
from tools.executor import execute_tool

logger = logging.getLogger(__name__)


def get_web_quick_replies(tools_used: list[str]) -> list[dict]:
    """Generate context-appropriate quick reply buttons for WebApp (same logic as LINE)."""
    used_set = set(tools_used)
    analysis_tools = {"get_race_flow", "get_jockey_analysis", "get_bloodline_analysis", "get_recent_runs", "get_stable_comments"}
    items = []

    if used_set & analysis_tools:
        if "get_race_flow" not in used_set:
            items.append({"label": "🔄 展開予想", "text": "展開は？"})
        if "get_jockey_analysis" not in used_set:
            items.append({"label": "🏇 騎手分析", "text": "騎手の成績は？"})
        if "get_bloodline_analysis" not in used_set:
            items.append({"label": "🧬 血統分析", "text": "血統は？"})
        if "get_recent_runs" not in used_set:
            items.append({"label": "📈 過去走", "text": "過去の成績は？"})
        if "get_stable_comments" not in used_set:
            items.append({"label": "🗣️ 関係者情報", "text": "関係者情報は？"})
        items.append({"label": "💬 どう思う？", "text": "お前はどう思う？"})

    elif "get_predictions" in used_set:
        items = [
            {"label": "🔄 展開予想", "text": "展開は？"},
            {"label": "🏇 騎手分析", "text": "騎手の成績は？"},
            {"label": "🧬 血統分析", "text": "血統は？"},
            {"label": "📈 過去走", "text": "過去の成績は？"},
            {"label": "🗣️ 関係者情報", "text": "関係者情報は？"},
            {"label": "🔥 全部見る", "text": "全部掘り下げて"},
            {"label": "💬 どう思う？", "text": "お前はどう思う？"},
        ]

    elif "get_race_entries" in used_set:
        items = [
            {"label": "🎯 予想して", "text": "予想して"},
            {"label": "📊 予測勝率", "text": "予測勝率見せて"},
            {"label": "💰 オッズは？", "text": "オッズ見せて"},
            {"label": "⚖️ 馬体重", "text": "馬体重は？"},
            {"label": "🗣️ 関係者情報", "text": "関係者情報は？"},
        ]

    elif "get_today_races" in used_set:
        items = [
            {"label": "🏇 メインレース", "text": "メインレースの出馬表見せて"},
        ]

    return items

# Tools that should skip memory extraction
_MEMORY_SKIP_TOOLS = {
    "get_today_races", "get_race_entries", "get_predictions",
    "get_realtime_odds", "get_race_flow", "get_jockey_analysis",
    "get_bloodline_analysis", "get_recent_runs", "get_horse_weights",
    "get_training_comments", "get_stable_comments", "get_engine_stats",
    "get_odds_probability", "get_prediction_ranking", "search_horse",
}


def run_agent(
    user_message: str,
    history: list[dict],
    profile: dict,
    active_race_id_hint: str | None = None,
):
    """Run the agentic loop as a generator.

    Args:
        user_message: The user's text input.
        history: Mutable conversation history list (will be modified in place).
        profile: User profile dict from Supabase (must have "id").
        active_race_id_hint: Optional race_id from caller context.

    Yields dicts with "type" key. Final yield is always {"type": "done", ...}.
    """
    profile_id = profile["id"]
    is_web_session = profile.get("web_session", False)

    # Build user context
    if is_web_session:
        # Web sessions: no Supabase DB, use minimal context
        memories = []
        user_context = "【Webチャットユーザー】\n名前: ゲスト"
    else:
        memories = db_get_memories(profile_id)
        user_context = db_build_user_context(profile, memories)

    # Inject honmei status if available (LINE only)
    if active_race_id_hint and not is_web_session:
        existing_pick = db_check_prediction(profile_id, active_race_id_hint)
        if existing_pick:
            user_context += (
                f"\n\n【本命登録済み】レース {active_race_id_hint} の本命は "
                f"{existing_pick['horse_number']}番 {existing_pick['horse_name']} で登録済み。"
                f"このレースの本命は再度聞かないこと。"
            )

    system = build_system_prompt(user_context)
    history = trim_history(history)

    # ── Template router: bypass Claude for deterministic queries ──
    route = match_route(user_message)
    if route:
        route_name, route_params = route
        logger.info(f"Template route matched: {route_name}")
        history.append({"role": "user", "content": user_message})

        result = route_and_respond(route_name, route_params, None, history, profile)
        if result:
            logger.info(f"Template route handled: {route_name} (Claude API skipped)")
            for entry in result.get("history_entries", []):
                history.append(entry)

            full_text = result["text"]
            if result.get("footer"):
                full_text += "\n\n" + result["footer"]

            yield {
                "type": "done",
                "text": full_text,
                "raw_text": result["text"],
                "footer": result.get("footer", ""),
                "tools_used": result["tools_used"],
                "active_race_id": result.get("active_race_id"),
                "history": history,
                "cache_used": False,
                "quick_replies": get_web_quick_replies(result["tools_used"]),
            }
            return
        else:
            history.pop()  # Route matched but couldn't handle

    # ── Pre-loop cache check ──
    query_type = detect_query_type(user_message)
    if query_type:
        race_id = find_race_id(history)
        if race_id:
            cached = get_cached_response(race_id, query_type)
            if cached:
                logger.info(f"Pre-loop cache hit: {race_id}:{query_type}")
                history.append({"role": "user", "content": user_message})
                history.append({"role": "assistant", "content": cached["text"]})

                full_text = cached["text"]
                if cached["footer"]:
                    full_text += "\n\n" + cached["footer"]

                yield {
                    "type": "done",
                    "text": full_text,
                    "raw_text": cached["text"],
                    "footer": cached["footer"],
                    "tools_used": cached["tools_used"],
                    "active_race_id": race_id,
                    "history": history,
                    "cache_used": True,
                    "quick_replies": get_web_quick_replies(cached["tools_used"]),
                }
                return

    # ── Agentic loop ──
    history.append({"role": "user", "content": user_message})
    yield {"type": "thinking"}

    tools_used = []
    response = None
    active_race_id = active_race_id_hint
    cache_used = False
    tool_context = {"user_profile_id": profile_id}

    for turn in range(MAX_TOOL_TURNS):
        response = call_claude(history, system)

        if response.stop_reason == "end_turn":
            history.append({"role": "assistant", "content": response.content})
            break

        tool_blocks = get_tool_blocks(response)
        if not tool_blocks:
            history.append({"role": "assistant", "content": response.content})
            break

        # ── Mid-loop cache check ──
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
            logger.info(f"Mid-loop cache hit: {active_race_id}")
            history.append({"role": "assistant", "content": mid_cache["text"]})
            tools_used = mid_cache["tools_used"]
            cache_used = True
            break

        history.append({"role": "assistant", "content": response.content})

        # Execute tools
        tool_results = []
        for tool_block in tool_blocks:
            tools_used.append(tool_block.name)
            yield {"type": "tool", "name": tool_block.name}

            inp = tool_block.input if isinstance(tool_block.input, dict) else {}
            if inp.get("race_id"):
                active_race_id = inp["race_id"]

            logger.info(f"Executing tool: {tool_block.name}")
            result = execute_tool(tool_block.name, tool_block.input, context=tool_context)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result,
            })

        history.append({"role": "user", "content": tool_results})

    # Build final response
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

    # ── Post-loop: save to response cache ──
    if not cache_used and active_race_id:
        save_qt = detect_query_type(user_message)
        if save_qt:
            save_cached_response(active_race_id, save_qt, response_text, footer, tools_used)

    # Auto-extract memories (skip for web sessions — no DB)
    skip_memory = is_web_session or cache_used or bool(set(tools_used) & _MEMORY_SKIP_TOOLS)
    if not skip_memory:
        try:
            new_memories = extract_memories(user_message, response_text)
            if new_memories:
                db_add_memories(profile_id, new_memories)
                logger.info(f"New memories: {new_memories}")
        except Exception:
            pass

    yield {
        "type": "done",
        "text": full_text,
        "raw_text": response_text,
        "footer": footer,
        "tools_used": tools_used,
        "active_race_id": active_race_id,
        "history": history,
        "cache_used": cache_used,
        "quick_replies": get_web_quick_replies(tools_used),
    }
