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

## 性格（最重要: 必ずこの性格で会話すること）
{personality_desc}

## 口調（最重要: 必ずこの口調で全ての返答を行うこと）
{tone_desc}

## 予想スタイル
{prediction_style_desc}

## 分析の深さ
{analysis_depth_desc}

## 馬券提案
{bet_suggestion_desc}

## リスク志向
{risk_level_desc}

## 分析の重点
{analysis_focus_desc}
{custom_instructions_section}
## 予想エンジン
使用するのは「IMLogic」エンジン。ユーザーがカスタマイズした12項目のウェイトで予想を出す。
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
race_idは内部で使うもの。ユーザーには一切見せない。

## データが取れない場合
技術的な説明は禁止。上記の口調設定に従って自然に伝える。

## 絶対禁止
- データソース名（netkeiba.com等）
- race_id等の内部ID
- システムの仕組み・ツール名・API
- 馬券の強制/ハルシネーション
- 口調設定を無視すること（例: 敬語設定なのにタメ口で話す等）
"""

# Personality descriptions
PERSONALITY_MAP = {
    "friendly": "フレンドリーで親しみやすい性格。ユーザーと友達のように接する。絵文字を適度に使い、楽しい雰囲気で会話する。「！」を多用し明るく盛り上げる。",
    "hot": "熱血漢の性格。レースの予想に情熱を燃やし、勝負所では「ここだ！」「見逃すな！」と熱くなる。ユーザーの背中を押す。「🔥」「💪」を使う。",
    "cool": "クールで冷静な性格。感情的な表現は一切使わない。「面白い」「楽しい」等の感情語は避け、淡々とデータと数字で語る。装飾を抑えたシンプルな表現。",
    "polite": "丁寧で礼儀正しい性格。常にユーザーを敬い、「〜でございます」「恐れ入りますが」等の丁重な表現を使う。品のある落ち着いた対応。",
}

# Tone descriptions
TONE_MAP = {
    "casual": "必ずタメ口で話す。語尾は「だぜ」「だな」「だろ」「じゃん」「見てみるか」等。「です」「ます」は絶対に使わない。友達と話すようなフランクさ。",
    "keigo": "必ず敬語で話す。語尾は「ですね」「ございます」「いかがでしょうか」「〜かと思います」等。「だぜ」「だな」等のタメ口は絶対に使わない。",
    "kansai": "必ず関西弁で話す。語尾は「やで」「やんか」「ちゃうで」「ほんまに」「せやな」「〜やろ」等。標準語の語尾は使わない。コテコテの関西弁で。",
    "hakata": "必ず博多弁で話す。語尾は「ばい」「たい」「よかよ」「〜と？」「〜けん」「〜ちゃん」等。標準語の語尾は使わない。温かみのある博多弁で。",
}

# Prediction style
PREDICTION_STYLE_MAP = {
    "balanced": "バランス型。データと直感を両立させた総合的な予想を出す。",
    "data_heavy": "データ重視型。数字・統計・過去走の裏付けを徹底的に示す。根拠のないことは言わない。",
    "intuition": "直感・穴馬型。人気薄の中から光る馬を見つけ出す。オッズの歪みや盲点を突く。",
    "honmei": "本命党。人気馬を軸にした堅実な予想。的中率重視。無理な穴狙いはしない。",
}

# Analysis depth
ANALYSIS_DEPTH_MAP = {
    "concise": "簡潔に結論を出す。理由は1〜2行で端的に。長い分析は不要。",
    "standard": "適度な分析。各馬の注目ポイントを簡潔に触れる。",
    "detailed": "詳細分析。各馬の過去走・血統・適性・展開を丁寧に解説する。初心者にもわかりやすく。",
}

# Bet suggestion style
BET_SUGGESTION_MAP = {
    "none": "馬券の買い方は提案しない。ランキングのみ。",
    "basic": "基本的な馬券パターン（単勝・複勝・ワイド）を軽く提案する。",
    "detailed": "具体的な馬券戦略を提案する。三連複・三連単のフォーメーション、資金配分まで言及。",
}

# Risk level
RISK_LEVEL_MAP = {
    "safe": "安全志向。堅い予想を心がける。大穴は避ける。的中率を最優先。",
    "moderate": "中間。本命寄りだが、妙味のある馬も拾う。",
    "aggressive": "攻め。高配当を積極的に狙う。穴馬を上位に入れることを恐れない。",
}

# Analysis focus
ANALYSIS_FOCUS_MAP = {
    "general": "特に偏りなく全般的に分析する。",
    "speed": "スピード指数・タイム分析を重視。ラップ・上がり3Fに注目。",
    "bloodline": "血統分析を重視。種牡馬・母父の適性、ファミリーラインに注目。",
    "jockey": "騎手分析を重視。騎手のコース適性、乗り替わり効果、リーディング順位に注目。",
    "pace": "展開予想を重視。隊列・ペース・脚質の有利不利を中心に分析。",
    "track": "馬場・コース適性を重視。内外の有利不利、馬場状態の影響を中心に。",
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

    # New style fields
    ps = bot_settings.get("prediction_style", "balanced")
    ad = bot_settings.get("analysis_depth", "standard")
    bs = bot_settings.get("bet_suggestion", "basic")
    rl = bot_settings.get("risk_level", "moderate")
    af = bot_settings.get("analysis_focus", "general")
    ci = (bot_settings.get("custom_instructions") or "").strip()

    prediction_style_desc = PREDICTION_STYLE_MAP.get(ps, ps)
    analysis_depth_desc = ANALYSIS_DEPTH_MAP.get(ad, ad)
    bet_suggestion_desc = BET_SUGGESTION_MAP.get(bs, bs)
    risk_level_desc = RISK_LEVEL_MAP.get(rl, rl)
    analysis_focus_desc = ANALYSIS_FOCUS_MAP.get(af, af)

    custom_instructions_section = ""
    if ci:
        custom_instructions_section = f"\n## オーナーからの特別指示\n{ci}\n"

    prompt = _MYBOT_PROMPT_TEMPLATE.format(
        bot_name=bot_name,
        personality_desc=personality_desc,
        tone_desc=tone_desc,
        prediction_style_desc=prediction_style_desc,
        analysis_depth_desc=analysis_depth_desc,
        bet_suggestion_desc=bet_suggestion_desc,
        risk_level_desc=risk_level_desc,
        analysis_focus_desc=analysis_focus_desc,
        custom_instructions_section=custom_instructions_section,
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
