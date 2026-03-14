"""MYBOT agentic loop — customized predictions with user's IMLogic weights.

Similar to chat_core.run_agent but:
- Uses the bot owner's IMLogic weights for get_predictions
- Injects bot personality/tone into system prompt
- Uses IMLogic prediction API instead of standard 4-engine predictions
"""

import logging

from agent.engine import (
    call_claude, build_system_prompt, extract_text, get_tool_blocks,
    trim_history,
)
from agent.chat_core import get_web_quick_replies
from config import MAX_TOOL_TURNS, DLOGIC_API_URL
from tools.executor import execute_tool

logger = logging.getLogger(__name__)

# System prompt template for MYBOT
_MYBOT_PROMPT_TEMPLATE = """あなたは「{bot_name}」。ユーザーが作成したカスタムAI競馬予想BOT。

## 性格
{personality_desc}

## 口調
{tone_desc}

## 予想エンジン
お前が使うのは「IMLogic」エンジン。ユーザーがカスタマイズした12項目のウェイトで予想を出す。
通常のDlogic/Ilogic/ViewLogic/MetaLogicではなく、IMLogicの結果を表示する。

## 予想表示
━━━ {bot_name}の予想 ━━━
S 6.馬名
A 3.馬名
B 11.馬名
C 7.馬名
C 1.馬名
━━━━━━━━━━

## ツール使用（即行動）
確認質問せず即ツール呼び出し:
- 「今日のJRA」→get_today_races(jra) / 「地方」→get_today_races(nar)
- 「予想して」→get_race_entries→get_predictions
- 「オッズ」「馬体重」「展開」「騎手」「血統」「過去走」「予測勝率」→即該当ツール
- 競馬場名→get_today_races / 「11R」→文脈からget_race_entries

## 出馬表（全頭表示。省略禁止）
① {{馬番}}.{{馬名}}（{{騎手名}}）形式。全頭出す

## race_idの扱い
race_idはお前が内部で使うもの。ユーザーには一切見せるな。

## データが取れない場合
技術的な説明は禁止。「まだ情報が出てないみたいだ」等と自然に伝える。

## 絶対禁止
- データソース名（netkeiba.com等）
- race_id等の内部ID
- システムの仕組み・ツール名・API
- 馬券の強制/ハルシネーション
"""

# Personality descriptions
PERSONALITY_MAP = {
    "friendly": "フレンドリーで親しみやすい。ユーザーと友達のように接する。",
    "hot": "熱血漢。レースの予想に情熱を燃やす。勝負所では熱くなる。",
    "cool": "クールで冷静。データに基づいた客観的な分析を重視する。感情的にはならない。",
    "polite": "丁寧で礼儀正しい。敬語で話す。ユーザーを立てる。",
}

# Tone descriptions
TONE_MAP = {
    "casual": "タメ口。「だぜ」「だな」「見てみるか」等。「です」「ます」禁止。",
    "keigo": "敬語。「ですね」「ございます」「いかがでしょうか」等。丁寧に。",
    "kansai": "関西弁。「やで」「やんか」「ちゃうで」「ほんまに」等。",
    "hakata": "博多弁。「ばい」「たい」「よかよ」「〜と？」等。",
}


def _format_mybot_footer(tools_used: list[str], bot_settings: dict) -> str:
    """MYBOT用フッター: get_predictionsをIMLogicラベルに差し替える."""
    _MYBOT_TOOL_LABELS = {
        "get_today_races": "レース一覧取得",
        "get_race_entries": "出馬表取得",
        "get_predictions": "IMLogicエンジン",
        "get_realtime_odds": "リアルタイムオッズ取得",
        "search_horse": "馬データ検索",
        "get_race_flow": "展開予想",
        "get_jockey_analysis": "騎手分析",
        "get_bloodline_analysis": "血統分析",
        "get_recent_runs": "直近走分析",
    }
    _SKIP = {"get_race_entries_by_name"}
    seen = set()
    labels = []
    for t in tools_used:
        if t not in seen and t not in _SKIP:
            seen.add(t)
            label = _MYBOT_TOOL_LABELS.get(t, t)
            labels.append(label)
    if not labels:
        return ""
    bot_name = bot_settings.get("bot_name", "MYBOT")
    return f"─────────────\n⚡ {bot_name} 使用エンジン: " + "、".join(labels)


def _build_mybot_system_prompt(bot_settings: dict, user_context: str = "") -> str:
    """Build system prompt with bot personality and user context."""
    bot_name = bot_settings.get("bot_name", "MYBOT")
    personality = bot_settings.get("personality", "friendly")
    tone = bot_settings.get("tone", "casual")

    personality_desc = PERSONALITY_MAP.get(personality, personality)
    tone_desc = TONE_MAP.get(tone, tone)

    # If personality/tone is custom text (not a key), use as-is
    if personality not in PERSONALITY_MAP:
        personality_desc = personality
    if tone not in TONE_MAP:
        tone_desc = tone

    prompt = _MYBOT_PROMPT_TEMPLATE.format(
        bot_name=bot_name,
        personality_desc=personality_desc,
        tone_desc=tone_desc,
    )

    # Add date
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][now.weekday()]
    prompt += f"\n\n## 現在の日時\n{now.strftime('%Y年%m月%d日')}（{weekday_ja}） {now.strftime('%H:%M')} JST"

    if user_context:
        prompt += "\n\n" + user_context

    return prompt


def _execute_imlogic_prediction(race_id: str, bot_settings: dict, context: dict) -> str:
    """Execute IMLogic prediction with user's custom weights."""
    import json
    import requests
    from tools.executor import _race_cache

    # Get race data from cache
    cache_entry = _race_cache.get(race_id, {})
    entries = cache_entry.get("entries", {})

    if not entries:
        # Fetch entries first
        execute_tool("get_race_entries", {"race_id": race_id}, context=context)
        cache_entry = _race_cache.get(race_id, {})
        entries = cache_entry.get("entries", {})

    if not entries:
        return json.dumps({"error": "レースデータが取得できなかった"}, ensure_ascii=False)

    # Build IMLogic API request
    item_weights = bot_settings.get("item_weights", {})
    horse_weight = bot_settings.get("horse_weight", 70)
    jockey_weight = bot_settings.get("jockey_weight", 30)

    payload = {
        "race_id": race_id,
        "horses": entries.get("horses", []),
        "horse_numbers": entries.get("horse_numbers", []),
        "jockeys": entries.get("jockeys", []),
        "posts": entries.get("posts", []),
        "venue": entries.get("venue", ""),
        "distance": entries.get("distance", ""),
        "track_type": entries.get("track_type", ""),
        "track_condition": entries.get("track_condition", ""),
        "horse_weight": horse_weight,
        "jockey_weight": jockey_weight,
        "item_weights": item_weights,
    }

    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}/api/v2/predictions/imlogic",
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Format as predictions result
            rankings = data.get("rankings", [])
            rank_labels = {1: "S", 2: "A", 3: "B", 4: "C", 5: "C"}
            predictions = []
            for item in rankings[:5]:
                predictions.append({
                    "rank": item.get("rank", 0),
                    "rank_label": rank_labels.get(item.get("rank", 5), "C"),
                    "horse_number": item.get("horse_number"),
                    "horse_name": item.get("horse_name"),
                    "total_score": item.get("total_score"),
                })

            bot_name = bot_settings.get("bot_name", "MYBOT")
            return json.dumps({
                "engine": "IMLogic",
                "bot_name": bot_name,
                "predictions": {bot_name: predictions},
                "race_name": entries.get("race_name", ""),
                "venue": entries.get("venue", ""),
                "horse_weight_ratio": horse_weight,
                "jockey_weight_ratio": jockey_weight,
            }, ensure_ascii=False)
        else:
            logger.error(f"IMLogic API error: {resp.status_code} {resp.text[:200]}")
            return json.dumps({"error": "予想エンジンでエラーが発生した"}, ensure_ascii=False)

    except Exception as e:
        logger.exception("IMLogic API call failed")
        return json.dumps({"error": "予想エンジンに接続できなかった"}, ensure_ascii=False)


def run_mybot_agent(
    user_message: str,
    history: list[dict],
    profile: dict,
    bot_settings: dict,
    active_race_id_hint: str | None = None,
):
    """Run MYBOT agentic loop as a generator.

    Similar to chat_core.run_agent but uses IMLogic for predictions
    and injects bot personality.
    """
    profile_id = profile["id"]

    # Build user context (minimal for MYBOT)
    user_context = ""
    if active_race_id_hint:
        from tools.executor import _race_cache
        race_info = _race_cache.get(active_race_id_hint, {}).get("entries", {})
        race_name = race_info.get("race_name", "")
        venue = race_info.get("venue", "")
        if race_name or venue:
            user_context = (
                f"【現在のレース】{venue} {race_name} (race_id: {active_race_id_hint})\n"
                f"ユーザーが「予想は？」「展開は？」等と聞いた場合、このレースについて答えろ。"
            )

    system = _build_mybot_system_prompt(bot_settings, user_context)
    history = trim_history(history)

    # Agentic loop
    history.append({"role": "user", "content": user_message})
    yield {"type": "thinking"}

    tools_used = []
    response = None
    active_race_id = active_race_id_hint
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

        history.append({"role": "assistant", "content": response.content})

        # Execute tools
        tool_results = []
        for tool_block in tool_blocks:
            tools_used.append(tool_block.name)
            yield {"type": "tool", "name": tool_block.name}

            inp = tool_block.input if isinstance(tool_block.input, dict) else {}
            if inp.get("race_id"):
                active_race_id = inp["race_id"]

            logger.info(f"MYBOT executing tool: {tool_block.name}")

            # Intercept get_predictions → use IMLogic instead
            if tool_block.name == "get_predictions" and active_race_id:
                result = _execute_imlogic_prediction(
                    active_race_id, bot_settings, context=tool_context
                )
            else:
                result = execute_tool(tool_block.name, tool_block.input, context=tool_context)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result,
            })

        history.append({"role": "user", "content": tool_results})

    # Build final response
    if response:
        response_text = extract_text(response)
    else:
        response_text = "ごめん、ちょっと調べすぎちゃった。"
    if not response_text:
        response_text = "ごめん、うまく答えられなかった。もう一回聞いてもらえる？"

    footer = _format_mybot_footer(tools_used, bot_settings)
    full_text = response_text + ("\n\n" + footer if footer else "")

    yield {
        "type": "done",
        "text": full_text,
        "raw_text": response_text,
        "footer": footer,
        "tools_used": tools_used,
        "active_race_id": active_race_id,
        "history": history,
        "quick_replies": get_web_quick_replies(tools_used),
    }
