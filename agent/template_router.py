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
    # Self-introduction (static, no API call)
    (re.compile(r"(ディーロジ|Dロジ|dロジ)(くん)?(って|とは|は何|ってなに|について)"), "self_intro", {}),
    # Inquiry (static guidance, no API call)
    (re.compile(r"問い合わせ(したい|する|を|は)?"), "inquiry", {}),
    # Race lists
    (re.compile(r"(今日の|きょうの)?(JRA|jra|中央)"), "today_races", {"race_type": "jra"}),
    (re.compile(r"(今日の|きょうの)?(地方|NAR|nar|地方競馬)"), "today_races", {"race_type": "nar"}),
    # Entries (出馬表)
    (re.compile(r"メインレース.*(出馬表|エントリ|エントリー)"), "entries", {"main_race": True}),
    (re.compile(r"出馬表(を|見せて|は|出して)?"), "entries", {}),
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
    (re.compile(r"調教(は|を|どう|評価)?"), "training", {}),
    (re.compile(r"(予測)?勝率(は|を|見)?"), "odds_probability", {}),
    (re.compile(r"関係者(情報|の|は)?"), "stable_comments", {}),
    (re.compile(r"(陣営|厩舎)(の|コメント|情報|は)"), "stable_comments", {}),
    (re.compile(r"結果(は|を|見)?[？?]?$"), "race_results", {}),
    (re.compile(r"(何着|着順|勝った馬)"), "race_results", {}),
    # Odds signals (歪み)
    (re.compile(r"歪み(は|を|見|ある)?[？?]?"), "odds_signal", {}),
    # Stats (no API needed at all)
    (re.compile(r"(俺の|おれの|自分の)?(成績|的中|回収)"), "my_stats", {}),
    # Honmei ratio (みんなの本命比率)
    (re.compile(r"(みんなの|皆の)?(本命比率|本命分布|投票比率)"), "honmei_ratio", {}),
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

    deduped = []
    seen = set()
    for r in races:
        key = r.get("race_id") or f"{r.get('venue', '')}-{r.get('race_number', 0)}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    races = deduped

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
    lines.append("━━━━━━━━")

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

    lines.append("━━━━━━━━")
    return "\n".join(lines)


def _fmt_predictions(data: dict) -> str:
    """Format prediction results for LINE display."""
    preds = data.get("predictions", {})
    if not preds:
        return "予想データがまだないみたいだ。"

    rank_labels = {1: "S", 2: "A", 3: "B", 4: "C", 5: "C"}
    lines = ["━━ 予想結果 ━━"]

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


def _fmt_opinion(entries: dict, predictions: dict, race_flow: dict, odds: dict) -> str:
    """Format a deterministic 'opinion' response.

    NOTE: Must always provide an opinion (no '分からない').
    """

    def _safe_float(v):
        try:
            return float(v)
        except Exception:
            return None

    race_name = entries.get("race_name", "") if isinstance(entries, dict) else ""
    venue = entries.get("venue", "") if isinstance(entries, dict) else ""
    distance = entries.get("distance", "") if isinstance(entries, dict) else ""
    cond = entries.get("track_condition", "") if isinstance(entries, dict) else ""

    lines = ["━━ 俺の見解 ━━"]
    header_parts = [p for p in [venue, race_name] if p]
    meta_parts = [p for p in [distance, cond] if p]
    if header_parts:
        lines.append(" ".join(header_parts))
    if meta_parts:
        lines.append(" / ".join(meta_parts))
    lines.append("─────────")

    # Map horse_number -> horse_name
    name_map: dict[int, str] = {}
    for e in (entries.get("entries", []) if isinstance(entries, dict) else []):
        try:
            num = int(e.get("horse_number"))
            name_map[num] = e.get("horse_name", "")
        except Exception:
            continue

    pred_map = (predictions.get("predictions") if isinstance(predictions, dict) else {}) or {}
    score: dict[int, float] = {}
    top2_count: dict[int, int] = {}

    for engine, items in pred_map.items():
        if not isinstance(items, list):
            continue
        for it in items[:5]:
            try:
                num = int(it.get("horse_number"))
            except Exception:
                continue
            rank = it.get("rank") or 5
            try:
                rank = int(rank)
            except Exception:
                rank = 5
            # Rank weight: 1->5, 2->4, ... 5->1
            score[num] = score.get(num, 0.0) + max(1, 6 - rank)
            if rank <= 2:
                top2_count[num] = top2_count.get(num, 0) + 1

    odds_map = (odds.get("odds") if isinstance(odds, dict) else {}) or {}
    odds_f: dict[int, float] = {}
    for k, v in odds_map.items():
        try:
            num = int(k)
        except Exception:
            continue
        fv = _safe_float(v)
        if fv is not None:
            odds_f[num] = fv

    # Pick main candidates
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], odds_f.get(kv[0], 9999.0)))
    top_nums = [n for n, _ in ranked[:3]]
    if not top_nums and odds_f:
        # Fallback: by odds
        top_nums = [n for n, _ in sorted(odds_f.items(), key=lambda kv: kv[1])[:3]]

    def _fmt_horse(n: int) -> str:
        name = name_map.get(n) or "?"
        o = odds_f.get(n)
        o_str = f"（現時点{o:.1f}倍）" if o is not None else ""
        return f"{n}.{name}{o_str}"

    if top_nums:
        honmei = top_nums[0]
        others = top_nums[1:]
        lines.append(f"結論: 俺は { _fmt_horse(honmei) } 寄り")
        if others:
            lines.append("相手: " + " / ".join(_fmt_horse(x) for x in others))
    else:
        lines.append("結論: ここはまだ割れ気味だな。俺は人気どころ中心で様子見。")

    # Reasons
    lines.append("")
    lines.append("根拠:")

    if top_nums:
        c = top2_count.get(top_nums[0], 0)
        if c >= 2:
            lines.append(f"- エンジン上位一致: {top_nums[0]}番は複数エンジンで上位")
        else:
            lines.append(f"- エンジン総合: 上位に出てる回数が多いのは {top_nums[0]}番")

    # Pace (best-effort)
    pace = None
    if isinstance(race_flow, dict):
        for key in ("pace", "pace_prediction", "predicted_pace", "pace_scenario", "pace_label"):
            if key in race_flow and race_flow.get(key):
                pace = race_flow.get(key)
                break
        # Try nested
        if pace is None:
            for k, v in race_flow.items():
                if isinstance(k, str) and "pace" in k.lower() and v:
                    pace = v
                    break
    if pace is not None:
        lines.append(f"- 展開: ペースは『{pace}』寄りって扱い")
    else:
        lines.append("- 展開: ペースは極端じゃない前提で見る")

    if odds_f and top_nums:
        favs = sorted(odds_f.items(), key=lambda kv: kv[1])[:3]
        fav_str = " / ".join(_fmt_horse(n) for n, _ in favs)
        lines.append(f"- オッズ: 人気上位は {fav_str}")
    elif odds_f:
        favs = sorted(odds_f.items(), key=lambda kv: kv[1])[:3]
        fav_str = " / ".join(_fmt_horse(n) for n, _ in favs)
        lines.append(f"- オッズ: 現時点の上位は {fav_str}")
    else:
        lines.append("- オッズ: 直近オッズが取れてないから、エンジン寄りで見る")

    lines.append("")
    lines.append("押し付けはしねー。最終判断はお前が決めろ。")
    return "\n".join(lines)


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
    lines = ["━━ オッズ ━━"]
    if is_prefetch:
        lines.append("※前日オッズ（リアルタイムは発売開始後に更新）")
        lines.append("")
    sorted_odds = sorted(odds.items(), key=lambda x: float(x[1]) if x[1] else 999)
    circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱"
    for i, (num, val) in enumerate(sorted_odds):
        name = name_map.get(num, "")
        circle = circled[i] if i < len(circled) else f"{i+1}"
        lines.append(f"{circle} {num}.{name} {val}倍")
    lines.append("━━━━━━━━")
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

    lines = ["━━ 馬体重 ━━"]
    for num in sorted(weights.keys(), key=lambda x: int(x)):
        name = name_map.get(num, "")
        w = weights[num]
        if isinstance(w, dict):
            kg = w.get("weight", "?")
            diff = w.get("diff", "")
            diff_str = f"（{diff}）" if diff else ""
            lines.append(f"{num}.{name}  {kg}kg{diff_str}")
        else:
            lines.append(f"{num}.{name}  {w}kg")
    lines.append("━━━━━━━━")
    return "\n".join(lines)


def _fmt_odds_probability(data: dict) -> str:
    """Format odds probability for LINE display."""
    probs = data.get("probabilities", [])
    if not probs:
        return data.get("note", "オッズデータがないから予測勝率が出せないな。")

    sorted_probs = sorted(probs, key=lambda x: -x.get("win_prob", 0))

    lines = ["━━ 予測勝率 ━━"]
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
    lines.append("━━━━━━━━")
    lines.append("※オッズから算出した統計的確率")
    return "\n".join(lines)


def _fmt_stable_comments(data: dict) -> str:
    """Format stable/trainer comments for LINE display."""
    comments = data.get("comments", [])
    if not comments:
        return data.get("note", "関係者情報がまだ出てないみたいだ。")

    lines = ["━━ 関係者情報 ━━"]
    lines.append("")

    for c in comments:
        num = c.get("horse_number", "?")
        name = c.get("horse_name", "?")
        rank = c.get("rank", "")
        comment = c.get("comment", "")
        condition = c.get("condition", "")

        rank_str = f"【{rank}】" if rank else ""
        lines.append(f"{num}.{name} {rank_str}")
        if condition:
            lines.append(f"  状態: {condition}")
        if comment:
            # Truncate long comments
            short = comment[:60] + "…" if len(comment) > 60 else comment
            lines.append(f"  → {short}")
        lines.append("")

    lines.append("━━━━━━━━")
    lines.append("※関係者情報を要約して表示")
    return "\n".join(lines)


def _fmt_training_comments(data: dict) -> str:
    """Format training evaluation for LINE display."""
    comments = data.get("comments", [])
    if not comments:
        return data.get("note", "調教評価がまだ出てないみたいだ。")

    lines = ["━━ 調教評価 ━━"]
    lines.append("")

    for c in comments:
        num = c.get("horse_number", "?")
        name = c.get("horse_name", "?")
        rank = c.get("rank", "")
        summary = c.get("summary", "")
        comment = c.get("comment", "")

        rank_str = f"【{rank}】" if rank else ""
        lines.append(f"{num}.{name} {rank_str}")
        if summary:
            lines.append(f"  {summary}")
        if comment:
            short = comment[:60] + "…" if len(comment) > 60 else comment
            lines.append(f"  → {short}")
        lines.append("")

    lines.append("━━━━━━━━")
    lines.append("※調教評価を要約して表示")
    return "\n".join(lines)


def _fmt_race_results(data: dict) -> str:
    """Format race results for LINE display."""
    results = data.get("results", [])
    if not results:
        return data.get("note", "まだ結果が出てないみたいだ。")

    race_name = data.get("race_name", "")
    venue = data.get("venue", "")

    lines = []
    if race_name or venue:
        lines.append(f"【{venue} {race_name}】")
    lines.append("━━ レース結果 ━━")
    lines.append("")

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for r in results:
        pos = r.get("position", "?")
        num = r.get("horse_number", "?")
        name = r.get("horse_name", "?")
        jockey = r.get("jockey", "")
        time_str = r.get("time", "")
        odds = r.get("odds", "")

        medal = medals.get(pos, f"{pos}着")
        if isinstance(pos, int) and pos <= 3:
            medal_str = f"{medal} "
        else:
            medal_str = f"{pos}着 "

        line = f"{medal_str}{num}.{name}"
        if jockey:
            line += f"（{jockey}）"
        if time_str:
            line += f" {time_str}"
        lines.append(line)

    # Payouts
    payouts = data.get("payouts", {})
    if payouts:
        lines.append("")
        lines.append("─────────")
        for bet_type, amount in payouts.items():
            if amount:
                lines.append(f"💰 {bet_type}: {amount}円")

    lines.append("━━━━━━━━")
    return "\n".join(lines)


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
    from tools.executor import JRA_VENUES, NAR_VENUES
    from agent.response_cache import find_race_id
    from agent.engine import format_tools_used_footer

    tool_context = {"user_profile_id": profile["id"]}

    def _build_multi_tool_history(tool_calls: list[tuple[str, dict, str]], final_text: str) -> list[dict]:
        """Build synthetic history for multiple tools in one turn."""
        tool_use_blocks = []
        tool_result_blocks = []
        for tool_name, tool_input, tool_result in tool_calls:
            tool_use_id = f"toolu_{uuid.uuid4().hex[:24]}"
            tool_use_blocks.append({
                "type": "tool_use",
                "id": tool_use_id,
                "name": tool_name,
                "input": tool_input,
            })
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": tool_result,
            })
        return [
            {"role": "assistant", "content": tool_use_blocks},
            {"role": "user", "content": tool_result_blocks},
            {"role": "assistant", "content": final_text},
        ]

    def _ensure_entries_cached(race_id: str):
        """Ensure race entries are in _race_cache (may be missing on different worker)."""
        if race_id and (race_id not in _race_cache or "entries" not in _race_cache.get(race_id, {})):
            try:
                execute_tool("get_race_entries", {"race_id": race_id}, context=tool_context)
            except Exception:
                pass

    def _entries_dict_from_cache(race_id: str) -> dict:
        """Normalize executor's _race_cache[...]['entries'] into get_race_entries-like dict."""
        cached = _race_cache.get(race_id, {}).get("entries", {})
        if not isinstance(cached, dict):
            return {}

        horses = cached.get("horses", []) or []
        nums = cached.get("horse_numbers", []) or []
        jockeys = cached.get("jockeys", []) or []
        posts = cached.get("posts", []) or []
        odds = cached.get("odds", []) or []

        entries = []
        for i in range(max(len(horses), len(nums), len(jockeys), 0)):
            num = nums[i] if i < len(nums) else i + 1
            name = horses[i] if i < len(horses) else ""
            jockey = jockeys[i] if i < len(jockeys) else ""
            ent = {"horse_number": num, "horse_name": name, "jockey": jockey}
            if i < len(posts):
                ent["post"] = posts[i]
            if i < len(odds) and odds[i]:
                ent["odds"] = odds[i]
            entries.append(ent)

        return {
            "race_id": race_id,
            "race_name": cached.get("race_name", ""),
            "venue": cached.get("venue", ""),
            "distance": cached.get("distance", ""),
            "race_number": cached.get("race_number", 0),
            "track_condition": cached.get("track_condition", ""),
            "entries": entries,
        }

    def _guess_race_type_from_race_id(race_id: str) -> str:
        """Best-effort guess of race_type from race_id (YYYYMMDD-venue-num)."""
        try:
            m = re.match(r"^\d{8}-(.+?)-\d+$", race_id)
            venue = m.group(1) if m else ""
        except Exception:
            venue = ""
        if venue and venue in NAR_VENUES:
            return "nar"
        if venue and venue in JRA_VENUES:
            return "jra"
        return "jra"

    def _pick_main_race_id(race_type: str) -> str | None:
        """Pick a reasonable 'main race' from today's races.

        Heuristic:
          - JRA: prefer 11R; NAR: prefer highest race_number
          - If start_time is available, choose the nearest upcoming
        """
        from datetime import datetime, timezone, timedelta

        try:
            result_str = execute_tool("get_today_races", {"race_type": race_type}, context=tool_context)
            data = json.loads(result_str)
        except Exception:
            return None

        races = data.get("races", []) or []
        if not races:
            return None

        nums = [r.get("race_number", 0) for r in races if isinstance(r, dict)]
        max_num = max(nums) if nums else 0
        target_num = 11 if race_type == "jra" else (max_num or 12)

        candidates = [r for r in races if r.get("race_number") == target_num] or list(races)

        # Try to choose nearest upcoming by start_time
        jst = timezone(timedelta(hours=9))
        now = datetime.now(jst)

        parsed = []
        for r in candidates:
            st = (r.get("start_time") or "").strip()
            if not st:
                parsed.append((None, r))
                continue
            try:
                hh, mm = st.split(":", 1)
                dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                parsed.append((dt, r))
            except Exception:
                parsed.append((None, r))

        upcoming = [(dt, r) for dt, r in parsed if dt and dt >= now]
        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            return upcoming[0][1].get("race_id")

        # Fallback: earliest time, else highest race_number
        timed = [(dt, r) for dt, r in parsed if dt]
        if timed:
            timed.sort(key=lambda x: x[0])
            return timed[0][1].get("race_id")

        candidates.sort(key=lambda x: x.get("race_number", 0), reverse=True)
        return candidates[0].get("race_id")

    # ── Route: self_intro (static, $0) ──
    if route_name == "self_intro":
        text = (
            "俺は「ディーロジ」。お前の競馬予想の相棒だ。\n"
            "JRA・地方競馬の予想を24時間サポートするぜ。\n\n"
            "━━ 予想エンジン ━━\n"
            "【Dlogic】統計分析。堅実な予想が強み。\n"
            "【Ilogic】過去走パターン分析。穴馬発見に強い。\n"
            "【ViewLogic】展開・位置取りシミュレーション。\n"
            "【MetaLogic】上の3つを総合判断するAI。\n\n"
            "━━ 掘り下げエンジン ━━\n"
            "展開予想／騎手分析／血統分析／過去走／予測勝率\n\n"
            "まずは「今日のJRA」「今日の地方競馬」で今日のレースを見てみろ！"
        )
        return {"text": text, "footer": "", "tools_used": [], "history_entries": []}

    # ── Route: inquiry (static, $0) ──
    if route_name == "inquiry":
        text = (
            "問い合わせは以下の手順で送れるぜ。\n\n"
            "そのまま問い合わせ内容を書いて送ってくれ。\n"
            "例：「予想の表示がおかしい」「こんな機能がほしい」\n\n"
            "運営に直接届くから、気軽に送ってくれ！"
        )
        return {"text": text, "footer": "", "tools_used": [], "history_entries": []}

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

    # ── Route: entries (出馬表) ──
    if route_name == "entries":
        main_race = bool(route_params.get("main_race"))

        race_id = active_race_id_hint or find_race_id(history)
        race_type = _guess_race_type_from_race_id(race_id) if race_id else "jra"

        if main_race:
            # Prefer the last listed race_type if user just requested race list
            # (fallback: jra)
            inferred_type = None
            for msg in reversed(history):
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "get_today_races":
                        inp = block.get("input") or {}
                        if isinstance(inp, dict) and inp.get("race_type") in ("jra", "nar"):
                            inferred_type = inp.get("race_type")
                            break
                if inferred_type:
                    break

            race_type = inferred_type or race_type or "jra"
            race_id = _pick_main_race_id(race_type)
            if not race_id:
                return None

        if not race_id:
            return None

        result_str = execute_tool(
            "get_race_entries",
            {"race_id": race_id, "race_type": race_type},
            context=tool_context,
        )
        data = json.loads(result_str)
        text = _fmt_entries(data)

        tools_used = ["get_race_entries"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_race_entries",
            tool_input={"race_id": race_id, "race_type": race_type},
            tool_result=result_str,
            final_text=text,
        )
        return {
            "text": text,
            "footer": footer,
            "tools_used": tools_used,
            "history_entries": history_entries,
            "active_race_id": race_id,
        }

    # ── Route: predictions (needs race_id from history) ──
    if route_name == "predictions":
        race_id = active_race_id_hint or find_race_id(history)
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

    # ── Route: opinion (お前はどう思う？) ──
    if route_name == "opinion":
        race_id = active_race_id_hint or find_race_id(history)
        if not race_id:
            return None

        cache_entry = _race_cache.get(race_id, {})
        cached_entries = cache_entry.get("entries", {}) if isinstance(cache_entry, dict) else {}
        race_type = "jra"
        if isinstance(cached_entries, dict) and cached_entries.get("race_type") in ("jra", "nar"):
            race_type = cached_entries.get("race_type")
        else:
            race_type = _guess_race_type_from_race_id(race_id)

        tool_calls: list[tuple[str, dict, str]] = []

        # Ensure entries (prefer cache)
        entries_dict = _entries_dict_from_cache(race_id) if (race_id in _race_cache and cached_entries) else {}
        if not entries_dict.get("entries"):
            # Try tool call (and retry with other race_type if needed)
            for rt in (race_type, "nar" if race_type == "jra" else "jra"):
                result_str = execute_tool("get_race_entries", {"race_id": race_id, "race_type": rt}, context=tool_context)
                try:
                    data = json.loads(result_str)
                except Exception:
                    data = {}
                if isinstance(data, dict) and not data.get("error"):
                    race_type = rt
                    entries_dict = data
                    tool_calls.append(("get_race_entries", {"race_id": race_id, "race_type": rt}, result_str))
                    break

        # Predictions
        pred_str = execute_tool("get_predictions", {"race_id": race_id}, context=tool_context)
        try:
            pred_data = json.loads(pred_str)
        except Exception:
            pred_data = {}
        tool_calls.append(("get_predictions", {"race_id": race_id}, pred_str))

        # Race flow
        flow_str = execute_tool("get_race_flow", {"race_id": race_id}, context=tool_context)
        try:
            flow_data = json.loads(flow_str)
        except Exception:
            flow_data = {}
        tool_calls.append(("get_race_flow", {"race_id": race_id}, flow_str))

        # Odds
        odds_data = {}
        for rt in (race_type, "nar" if race_type == "jra" else "jra"):
            odds_str = execute_tool("get_realtime_odds", {"race_id": race_id, "race_type": rt}, context=tool_context)
            try:
                data = json.loads(odds_str)
            except Exception:
                data = {}
            if isinstance(data, dict) and not data.get("error"):
                race_type = rt
                odds_data = data
                tool_calls.append(("get_realtime_odds", {"race_id": race_id, "race_type": rt}, odds_str))
                break

        text = _fmt_opinion(entries_dict, pred_data, flow_data, odds_data)
        tools_used = [t[0] for t in tool_calls]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_multi_tool_history(tool_calls, text)
        return {
            "text": text,
            "footer": footer,
            "tools_used": tools_used,
            "history_entries": history_entries,
            "active_race_id": race_id,
        }

    # ── Route: odds ──
    if route_name == "odds":
        race_id = active_race_id_hint or find_race_id(history)
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
        race_id = active_race_id_hint or find_race_id(history)
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
        race_id = active_race_id_hint or find_race_id(history)
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

    # ── Route: honmei_ratio (みんなの本命比率) ──
    if route_name == "honmei_ratio":
        race_id = active_race_id_hint or find_race_id(history)
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        text = _fmt_honmei_ratio(race_id)
        tools_used = ["get_honmei_ratio"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_honmei_ratio",
            tool_input={"race_id": race_id},
            tool_result=text,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: stable_comments (関係者情報) ──
    if route_name == "stable_comments":
        race_id = active_race_id_hint or find_race_id(history)
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        result_str = execute_tool("get_stable_comments", {"race_id": race_id}, context=tool_context)
        data = json.loads(result_str)
        text = _fmt_stable_comments(data)
        tools_used = ["get_stable_comments"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_stable_comments",
            tool_input={"race_id": race_id},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: training (調教評価) ──
    if route_name == "training":
        race_id = active_race_id_hint or find_race_id(history)
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        result_str = execute_tool("get_training_comments", {"race_id": race_id}, context=tool_context)
        data = json.loads(result_str)
        text = _fmt_training_comments(data)
        tools_used = ["get_training_comments"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_training_comments",
            tool_input={"race_id": race_id},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: race_results (レース結果) ──
    if route_name == "race_results":
        race_id = active_race_id_hint or find_race_id(history)
        if not race_id:
            return None

        _ensure_entries_cached(race_id)
        cache_entry = _race_cache.get(race_id, {})
        race_type = cache_entry.get("entries", {}).get("race_type", "jra")
        result_str = execute_tool("get_race_results", {"race_id": race_id, "race_type": race_type}, context=tool_context)
        data = json.loads(result_str)
        text = _fmt_race_results(data)
        tools_used = ["get_race_results"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_race_results",
            tool_input={"race_id": race_id, "race_type": race_type},
            tool_result=result_str,
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Route: odds_signal (歪みは？) ──
    if route_name == "odds_signal":
        race_id = active_race_id_hint or find_race_id(history)
        if not race_id:
            return None

        _ensure_entries_cached(race_id)

        # Resolve to netkeiba ID for Supabase query
        from tools.executor import _resolve_netkeiba_race_id
        netkeiba_id = _resolve_netkeiba_race_id(race_id)

        # Query odds_signals from Supabase (last 3 hours)
        try:
            from db.supabase_client import get_client
            from datetime import datetime, timedelta, timezone
            sb = get_client()
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            res = sb.table("odds_signals") \
                .select("*") \
                .eq("race_id", netkeiba_id) \
                .gte("notified_at", cutoff) \
                .order("notified_at", desc=True) \
                .execute()
            signals = res.data or []
        except Exception:
            logger.exception("Failed to fetch odds signals")
            signals = []

        text = _fmt_odds_signals(signals, race_id)
        tools_used = ["get_odds_signals"]
        footer = format_tools_used_footer(tools_used)
        history_entries = _build_history_entries(
            tool_name="get_odds_signals",
            tool_input={"race_id": race_id},
            tool_result=json.dumps({"count": len(signals)}, ensure_ascii=False),
            final_text=text,
        )
        return {"text": text, "footer": footer, "tools_used": tools_used,
                "history_entries": history_entries, "active_race_id": race_id}

    # ── Analysis routes: fall through to Claude ──
    # race_flow, jockey, bloodline, recent_runs
    # These need Claude to interpret and summarize the data
    if route_name in ("race_flow", "jockey", "bloodline", "recent_runs"):
        return None  # Claude handles these (interpretation needed)

    return None


def _fmt_stats(data: dict) -> str:
    """Format user stats for LINE display."""
    stats = data.get("stats")
    predictions = data.get("pending_predictions", [])

    lines = ["━━ お前の成績 ━━"]

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

    lines.append("━━━━━━━━")
    return "\n".join(lines)


def _fmt_honmei_ratio(race_id: str) -> str:
    """Format honmei prediction ratio for a race."""
    from db.supabase_client import get_client
    from tools.executor import _race_cache

    sb = get_client()

    # Get all predictions for this race
    res = sb.table("user_predictions") \
        .select("horse_number, horse_name") \
        .eq("race_id", race_id) \
        .execute()

    predictions = res.data or []

    if not predictions:
        return "まだこのレースにはみんな本命登録してないみたいだな。\n\n出馬表や予想を見た後に「本命」を選んでくれ！"

    # Count per horse
    counts: dict[int, dict] = {}
    for p in predictions:
        num = p["horse_number"]
        if num not in counts:
            counts[num] = {"name": p["horse_name"], "count": 0}
        counts[num]["count"] += 1

    total = len(predictions)

    # Sort by count descending
    ranked = sorted(counts.items(), key=lambda x: x[1]["count"], reverse=True)

    # Get race info from cache
    race_name = ""
    venue = ""
    cache = _race_cache.get(race_id, {}).get("entries", {})
    if cache:
        race_name = cache.get("race_name", "")
        venue = cache.get("venue", "")

    # Format
    lines = []
    header = f"【{venue} {race_name}】" if race_name else f"【{race_id}】"
    lines.append(f"📊 みんなの本命比率 {header}")
    lines.append("━━━━━━━━")
    lines.append("")

    bar_chars = "█▉▊▋▌▍▎▏"
    for i, (num, info) in enumerate(ranked):
        pct = info["count"] / total * 100
        # Visual bar (max 10 blocks)
        bar_len = int(pct / 10)
        bar = "█" * bar_len
        if bar_len < 10:
            remainder = (pct / 10) - bar_len
            idx = int(remainder * 8)
            if idx > 0 and idx < len(bar_chars):
                bar += bar_chars[idx]

        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
        lines.append(f"{medal} {num}番 {info['name']}")
        lines.append(f"   {bar} {pct:.0f}%")

    lines.append("")
    lines.append("━━━━━━━━")

    return "\n".join(lines)


def _fmt_odds_signals(signals: list[dict], race_id: str) -> str:
    """Format odds signals for LINE display."""
    from tools.executor import _race_cache

    # Build horse number → name map from cache
    horse_map: dict[int, str] = {}
    cached = _race_cache.get(race_id, {}).get("entries", {})
    if isinstance(cached, dict):
        nums = cached.get("horse_numbers", [])
        names = cached.get("horses", [])
        for n, name in zip(nums, names):
            try:
                horse_map[int(n)] = name
            except (ValueError, TypeError):
                pass

    venue = cached.get("venue", "")
    race_number = cached.get("race_number", "")
    race_name = cached.get("race_name", "")

    lines = ["━━ オッズ歪みシグナル ━━"]
    if venue or race_number:
        lines.append(f"📍 {venue}{race_number}R {race_name}".strip())
    lines.append("")

    if not signals:
        lines.append("このレースはまだ歪みシグナルが出てないな。")
        lines.append("レース前になったらまたチェックしてくれ！")
        lines.append("")
        lines.append("━━━━━━━━")
        return "\n".join(lines)

    # Group by type
    drops = [s for s in signals if s.get("signal_type") == "drop"]
    surges = [s for s in signals if s.get("signal_type") == "surge"]
    reversals = [s for s in signals if s.get("signal_type") == "reversal"]

    if drops:
        lines.append("📉 急落（大口買い検知）")
        for s in drops:
            num = s.get("horse_number", 0)
            name = horse_map.get(num, s.get("horse_name", f"{num}番"))
            detail = s.get("detail", {})
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except Exception:
                    detail = {}
            prev = detail.get("prev_odds", "?")
            curr = detail.get("curr_odds", "?")
            pct = detail.get("change_pct", 0)
            lines.append(f"  {num}. {name}")
            lines.append(f"     {prev}倍 → {curr}倍（{pct:+.1f}%）")
        lines.append("")

    if surges:
        lines.append("📈 急騰（嫌気）")
        for s in surges:
            num = s.get("horse_number", 0)
            name = horse_map.get(num, s.get("horse_name", f"{num}番"))
            detail = s.get("detail", {})
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except Exception:
                    detail = {}
            prev = detail.get("prev_odds", "?")
            curr = detail.get("curr_odds", "?")
            pct = detail.get("change_pct", 0)
            lines.append(f"  {num}. {name}")
            lines.append(f"     {prev}倍 → {curr}倍（{pct:+.1f}%）")
        lines.append("")

    if reversals:
        lines.append("🔀 人気逆転")
        for s in reversals:
            detail = s.get("detail", {})
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except Exception:
                    detail = {}
            old_num = detail.get("old_favorite", "?")
            new_num = detail.get("new_favorite", "?")
            old_name = horse_map.get(old_num, f"{old_num}番")
            new_name = horse_map.get(new_num, f"{new_num}番")
            lines.append(f"  {old_num}.{old_name} → {new_num}.{new_name} が1番人気に")
        lines.append("")

    lines.append(f"検知数: 📉{len(drops)} 📈{len(surges)} 🔀{len(reversals)}")
    lines.append("━━━━━━━━")

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
