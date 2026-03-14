"""Template router — bypass Claude API for deterministic queries.

For common patterns (race list, entries, predictions, odds, etc.),
call tools directly and format responses with templates.
This saves ~$0.01-0.05 per message by avoiding Claude API calls.

The tool results are still added to conversation history so that
Claude has full context when called for free-form questions like "お前どう思う？".
"""

import json
import logging
import re
import uuid

from tools.executor import execute_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pattern matching: user message → route
# ---------------------------------------------------------------------------

_ROUTES: list[tuple[re.Pattern, str, dict]] = [
    # Race lists
    (re.compile(r"(今日の|きょうの)?(JRA|jra|中央)"), "today_races", {"race_type": "jra"}),
    (re.compile(r"(今日の|きょうの)?(地方|NAR|nar|地方競馬)"), "today_races", {"race_type": "nar"}),
    # Predictions
    (re.compile(r"予想(して|を|出|見)"), "predictions", {}),
    # Analysis tools
    (re.compile(r"展開(は|予想|を)?[？?]?$"), "race_flow", {}),
    (re.compile(r"(どんな|どういう)(レース|展開)"), "race_flow", {}),
    (re.compile(r"騎手(の|分析|は)"), "jockey", {}),
    (re.compile(r"血統(は|分析|的)"), "bloodline", {}),
    (re.compile(r"(過去|直近|前走)(の|走|成績)"), "recent_runs", {}),
    # Data tools
    (re.compile(r"オッズ(は|を|見)?"), "odds", {}),
    (re.compile(r"馬体重(は|を|見)?"), "weights", {}),
    (re.compile(r"調教(は|を|どう)?"), "training", {}),
    (re.compile(r"(予測)?勝率(は|を|見)?"), "odds_probability", {}),
    # Stats (no API needed at all)
    (re.compile(r"(俺の|おれの|自分の)?(成績|的中|回収)"), "my_stats", {}),
]


def match_route(text: str) -> tuple[str, dict] | None:
    """Match user message to a template route.

    Returns (route_name, extra_params) or None if no match.
    """
    text = text.strip()
    for pattern, route, params in _ROUTES:
        if pattern.search(text):
            return route, params
    return None


# ---------------------------------------------------------------------------
# Template formatters
# ---------------------------------------------------------------------------

def _fmt_race_list(data: dict) -> str:
    """Format race list for LINE display."""
    races = data.get("races", [])
    if not races:
        return "今日はレースがないみたいだな。"

    # Group by venue
    venues: dict[str, list] = {}
    for r in races:
        v = r.get("venue", "不明")
        venues.setdefault(v, []).append(r)

    lines = []
    for venue, venue_races in venues.items():
        lines.append(f"🏇 {venue}")
        lines.append("─────────")
        for r in sorted(venue_races, key=lambda x: x.get("race_number", 0)):
            num = r.get("race_number", "?")
            name = r.get("race_name", "")
            st = r.get("start_time", "")
            if st:
                lines.append(f"  {num}R {st} {name}")
            else:
                lines.append(f"  {num}R {name}")
        lines.append("")

    return "\n".join(lines).strip()


def _fmt_entries(data: dict) -> str:
    """Format race entries for LINE display."""
    race_name = data.get("race_name", "")
    venue = data.get("venue", "")
    distance = data.get("distance", "")
    condition = data.get("track_condition", "")
    entries = data.get("entries", [])

    lines = [f"【{race_name}】"]
    if venue or distance:
        info_parts = [p for p in [venue, distance, condition] if p]
        lines.append(" / ".join(info_parts))
    lines.append("━━━━━━━━━━")

    circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱"
    for i, e in enumerate(entries):
        num = e.get("horse_number", i + 1)
        name = e.get("horse_name", "?")
        jockey = e.get("jockey", "?")
        circle = circled[i] if i < len(circled) else f"{i+1}"
        odds_str = ""
        if e.get("odds"):
            odds_str = f" {e['odds']}倍"
        lines.append(f"{circle} {num}.{name}（{jockey}）{odds_str}")

    lines.append("━━━━━━━━━━")
    return "\n".join(lines)


def _fmt_predictions(data: dict) -> str:
    """Format prediction results for LINE display."""
    preds = data.get("predictions", {})
    if not preds:
        return "予想データがまだないみたいだ。"

    rank_labels = {1: "S", 2: "A", 3: "B", 4: "C", 5: "C"}
    lines = ["━━━ 予想結果 ━━━"]

    track_adjusted = data.get("track_adjusted", False)
    track_condition = data.get("track_condition", "")
    if track_adjusted and track_condition:
        lines.append(f"※ {track_condition}馬場補正済み")
        lines.append("")

    for engine in ["Dlogic", "Ilogic", "ViewLogic", "MetaLogic"]:
        engine_data = preds.get(engine, [])
        if not engine_data:
            continue
        label = f"【{engine}】" if engine != "MetaLogic" else "【MetaLogic】総合判断"
        lines.append(label)
        for item in engine_data[:5]:
            rank = item.get("rank", 0)
            rl = rank_labels.get(rank, "C")
            num = item.get("horse_number", "?")
            name = item.get("horse_name", "?")
            lines.append(f"{rl} {num}.{name}")
        lines.append("")

    return "\n".join(lines).strip()


def _fmt_odds(data: dict) -> str:
    """Format odds data for LINE display."""
    odds = data.get("odds", {})
    if not odds:
        return "オッズがまだ出てないみたいだ。"

    # Need entries from cache to show horse names
    entries = data.get("_entries", [])
    name_map = {}
    for e in entries:
        name_map[str(e.get("horse_number", ""))] = e.get("horse_name", "")
    if not name_map:
        horses = data.get("_horses", [])
        nums = data.get("_horse_numbers", [])
        for i, num in enumerate(nums):
            if i < len(horses):
                name_map[str(num)] = horses[i]

    is_prefetch = data.get("_prefetch", False)
    lines = ["━━━ オッズ ━━━"]
    if is_prefetch:
        lines.append("※前日オッズ（リアルタイムは発売開始後に更新）")
        lines.append("")
    sorted_odds = sorted(odds.items(), key=lambda x: float(x[1]) if x[1] else 999)
    circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱"
    for i, (num, val) in enumerate(sorted_odds):
        name = name_map.get(num, "")
        circle = circled[i] if i < len(circled) else f"{i+1}"
        lines.append(f"{circle} {num}.{name} {val}倍")
    lines.append("━━━━━━━━━━")
    return "\n".join(lines)


def _fmt_weights(data: dict) -> str:
    """Format horse weights for LINE display."""
    weights = data.get("horse_weights", {})
    if not weights:
        return data.get("note", "馬体重がまだ発表されてないみたいだ。")

    entries = data.get("_entries", [])
    name_map = {}
    for e in entries:
        name_map[str(e.get("horse_number", ""))] = e.get("horse_name", "")
    if not name_map:
        horses = data.get("_horses", [])
        nums = data.get("_horse_numbers", [])
        for i, num in enumerate(nums):
            if i < len(horses):
                name_map[str(num)] = horses[i]

    lines = ["━━━ 馬体重 ━━━"]
    for num in sorted(weights.keys(), key=lambda x: int(x)):
        name = name_map.get(num, "")
        w = weights[num]
        lines.append(f"{num}.{name} {w}kg")
    lines.append("━━━━━━━━━━")
    return "\n".join(lines)


def _fmt_odds_probability(data: dict) -> str:
    """Format odds probability for LINE display."""
    probs = data.get("probabilities", [])
    if not probs:
        return data.get("note", "オッズデータがないから予測勝率が出せないな。")

    sorted_probs = sorted(probs, key=lambda x: -x.get("win_prob", 0))

    lines = ["━━━ 予測勝率 ━━━"]
    lines.append("")
    lines.append("馬番  馬名")
    lines.append("  勝率     複勝率")
    lines.append("─────────")

    for i, p in enumerate(sorted_probs):
        num = p.get("horse_number", "?")
        name = p.get("horse_name", "?")
        wp = p.get("win_prob", 0)
        pp = p.get("place_prob", 0)

        # Rank indicator
        if i == 0:
            rank = "🥇"
        elif i == 1:
            rank = "🥈"
        elif i == 2:
            rank = "🥉"
        else:
            rank = "　"

        lines.append(f"{rank} {num}.{name}")
        lines.append(f"    勝 {wp:5.1f}%  複 {pp:5.1f}%")

    lines.append("")
    lines.append("━━━━━━━━━━")
    lines.append("※オッズから算出した統計的確率")
    return "\n".join(lines)


def _fmt_generic_analysis(data: dict, tool_name: str) -> str:
    """Generic fallback: return raw JSON summary for analysis tools.
    Claude will format these when user asks 'お前どう思う？'"""
    # For analysis tools, we still want Claude to interpret the data
    # Return None to fall through to Claude
    return None


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

def route_and_respond(
    route_name: str,
    route_params: dict,
    user_id: str,
    history: list[dict],
    profile: dict,
    active_race_id_hint: str | None = None,
) -> dict | None:
    """Execute template route. Returns dict with keys:
        text: str           — formatted response text
        footer: str         — tool footer
        tools_used: list    — tool names used
        history_entries: list — entries to append to conversation history
    Or None if route cannot be handled (fall through to Claude).
    """
    from tools.executor import _race_cache
    from agent.response_cache import find_race_id
    from agent.engine import format_tools_used_footer

    tool_context = {"user_profile_id": profile["id"]}

    def _ensure_entries_cached(race_id: str):
        """Ensure race entries are in _race_cache (may be missing on different worker)."""
        if race_id and (race_id not in _race_cache or "entries" not in _race_cache.get(race_id, {})):
            try:
                execute_tool("get_race_entries", {"race_id": race_id}, context=tool_context)
            except Exception:
                pass

    # ── Route: today_races ──
    if route_name == "today_races":
        race_type = route_params.get("race_type", "jra")
        result_str = execute_tool("get_today_races", {"race_type": race_type}, context=tool_context)
        data = json.loads(result_str)
        text = _fmt_race_list(data)

        tools_used = ["get_today_races"]
        footer = format_tools_used_footer(tools_used)

        # Build synthetic history entries
        history_entries = _build_history_entries(
            tool_name="get_today_races",
            tool_input={"race_type": race_type},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used, "history_entries": history_entries}

    # ── Route: predictions (needs race_id from history) ──
    if route_name == "predictions":
        race_id = find_race_id(history) or active_race_id_hint
        if not race_id:
            return None  # Fall through to Claude

        # Get entries first if not cached
        if race_id not in _race_cache or "entries" not in _race_cache.get(race_id, {}):
            entries_result = execute_tool("get_race_entries", {"race_id": race_id}, context=tool_context)

        pred_result = execute_tool("get_predictions", {"race_id": race_id}, context=tool_context)
        data = json.loads(pred_result)
        text = _fmt_predictions(data)

        tools_used = ["get_predictions"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_predictions",
            tool_input={"race_id": race_id},
            tool_result=pred_result,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: odds ──
    if route_name == "odds":
        race_id = find_race_id(history) or active_race_id_hint
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        cache_entry = _race_cache.get(race_id, {})
        race_type = cache_entry.get("entries", {}).get("race_type", "jra")
        result_str = execute_tool("get_realtime_odds", {"race_id": race_id, "race_type": race_type}, context=tool_context)
        data = json.loads(result_str)

        # Enrich with horse names from cache
        entries_data = cache_entry.get("entries", {})
        if isinstance(entries_data, dict):
            data["_horse_numbers"] = entries_data.get("horse_numbers", [])
            data["_horses"] = entries_data.get("horses", [])

        # JRA fallback: if realtime odds empty, use prefetch odds
        if not data.get("odds") and entries_data:
            pf_odds = entries_data.get("odds", [])
            pf_nums = entries_data.get("horse_numbers", [])
            if pf_odds and any(o > 0 for o in pf_odds):
                odds_map = {}
                for i, num in enumerate(pf_nums):
                    if i < len(pf_odds) and pf_odds[i] > 0:
                        odds_map[str(num)] = pf_odds[i]
                data["odds"] = odds_map
                data["_prefetch"] = True

        text = _fmt_odds(data)
        tools_used = ["get_realtime_odds"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_realtime_odds",
            tool_input={"race_id": race_id, "race_type": race_type},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: weights ──
    if route_name == "weights":
        race_id = find_race_id(history) or active_race_id_hint
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        cache_entry = _race_cache.get(race_id, {})
        race_type = cache_entry.get("entries", {}).get("race_type", "jra")
        result_str = execute_tool("get_horse_weights", {"race_id": race_id, "race_type": race_type}, context=tool_context)
        data = json.loads(result_str)

        entries_data = cache_entry.get("entries", {})
        if isinstance(entries_data, dict):
            data["_horse_numbers"] = entries_data.get("horse_numbers", [])
            data["_horses"] = entries_data.get("horses", [])

        text = _fmt_weights(data)
        tools_used = ["get_horse_weights"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_horse_weights",
            tool_input={"race_id": race_id, "race_type": race_type},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: odds_probability ──
    if route_name == "odds_probability":
        race_id = find_race_id(history) or active_race_id_hint
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        result_str = execute_tool("get_odds_probability", {"race_id": race_id}, context=tool_context)
        data = json.loads(result_str)
        text = _fmt_odds_probability(data)
        tools_used = ["get_odds_probability"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_odds_probability",
            tool_input={"race_id": race_id},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: my_stats ──
    if route_name == "my_stats":
        result_str = execute_tool("get_my_stats", {}, context=tool_context)
        data = json.loads(result_str)
        text = _fmt_stats(data)
        tools_used = ["get_my_stats"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_my_stats",
            tool_input={},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used, "history_entries": history_entries}

    # ── Analysis routes: fall through to Claude ──
    # race_flow, jockey, bloodline, recent_runs, training
    # These need Claude to interpret and summarize the data
    if route_name in ("race_flow", "jockey", "bloodline", "recent_runs", "training"):
        return None  # Claude handles these (interpretation needed)

    return None


def _fmt_stats(data: dict) -> str:
    """Format user stats for LINE display."""
    stats = data.get("stats")
    predictions = data.get("pending_predictions", [])

    lines = ["━━━ お前の成績 ━━━"]

    if stats:
        total = stats.get("total_picks", 0)
        wins = stats.get("total_wins", 0)
        hit_rate = stats.get("win_rate") if stats.get("win_rate") is not None else ((wins / total * 100) if total > 0 else 0)
        recovery = stats.get("recovery_rate", 0)
        streak = stats.get("current_streak", 0)
        best = stats.get("best_payout", 0)

        lines.append(f"🎯 的中率: {hit_rate:.1f}%（{wins}勝/{total}戦）")
        lines.append(f"💰 回収率: {recovery:.1f}%")
        if streak > 0:
            lines.append(f"🔥 連勝中: {streak}連勝")
        if best > 0:
            lines.append(f"🏆 最高配当: {best:,}円")
    else:
        lines.append("まだ成績データがないな。")

    if predictions:
        lines.append("─────────")
        lines.append("【予想済みレース】")
        for p in predictions[:5]:
            race = p.get("race_name", "") or p.get("race_id", "")
            venue = p.get("venue", "")
            horse = p.get("horse_name", "")
            num = p.get("horse_number", "")
            lines.append(f"⏳ {venue} {race} → {num}番{horse}")

    if not stats and not predictions:
        lines.append("レースの本命を登録すれば、結果が出た後に成績が記録されるぜ！")

    lines.append("━━━━━━━━━━")
    return "\n".join(lines)


def _build_history_entries(
    tool_name: str,
    tool_input: dict,
    tool_result: str,
    final_text: str,
) -> list[dict]:
    """Build conversation history entries that mimic Claude's tool use flow.

    This ensures Claude has full context when called later for opinions.
    """
    # Simulate: assistant called tool → user provided result → assistant responded
    # Use proper toolu_ prefix with UUID to satisfy Claude API validation
    tool_use_id = f"toolu_{uuid.uuid4().hex[:24]}"
    return [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": tool_result,
                }
            ],
        },
        {
            "role": "assistant",
            "content": final_text,
        },
    ]
