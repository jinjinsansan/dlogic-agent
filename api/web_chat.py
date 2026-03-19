"""WebApp chat API — SSE streaming endpoint for Next.js frontend.

POST /api/chat
  Body: {"session_id": "...", "message": "..."}
  Response: text/event-stream (SSE)

Events:
  data: {"type": "thinking"}
  data: {"type": "tool", "name": "get_predictions", "label": "予想エンジン..."}
  data: {"type": "text", "content": "..."}
  data: {"type": "done"}
  data: [DONE]
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, request, Response, jsonify

from agent.chat_core import run_agent, get_web_quick_replies
from agent.engine import TOOL_LABELS, trim_history
from agent.response_cache import detect_query_type, save as save_cached_response
from agent.template_router import route_and_respond
from api.auth import verify_auth_header
import re

from db.redis_client import get_redis
from db.user_manager import (
    get_or_create_user, get_or_create_user_by_login,
    build_user_context as db_build_user_context,
    sync_profiles,
    is_maintenance_mode, get_maintenance_message,
    get_user_status,
)
from db.prediction_manager import (
    check_prediction as db_check_prediction,
    record_prediction as db_record_prediction,
)
from tools.executor import resolve_race_id_from_text

logger = logging.getLogger(__name__)

bp = Blueprint("web_chat", __name__)

# In-memory session store (keyed by web_session_id)
# Each session holds: profile, history, active_race_id
_sessions: dict[str, dict] = {}

# Session TTL: clean up sessions older than 6 hours
_SESSION_MAX_AGE = 6 * 3600
_SESSION_PREFIX = "web:session:"
_redis = get_redis()

_QUERY_ROUTE_MAP = {
    "prediction": ("predictions", {}),
    "predictions": ("predictions", {}),
    "odds": ("odds", {}),
    "weights": ("weights", {}),
    "odds_probability": ("odds_probability", {}),
    "stable_comments": ("stable_comments", {}),
    "training": ("training", {}),
    "race_results": ("race_results", {}),
    "my_stats": ("my_stats", {}),
    "honmei_ratio": ("honmei_ratio", {}),
    "today_races_jra": ("today_races", {"race_type": "jra"}),
    "today_races_nar": ("today_races", {"race_type": "nar"}),
}


def _route_from_query_type(query_type: str) -> tuple[str, dict] | None:
    if not query_type:
        return None
    return _QUERY_ROUTE_MAP.get(query_type.strip().lower())

# Honmei (本命) blocking keywords (same as LINE)
_RACE_CHANGE_KEYWORDS = [
    "他のレース", "別のレース", "次のレース",
    "船橋", "大井", "川崎", "浦和", "園田", "姫路", "金沢", "名古屋", "笠松", "高知", "佐賀",
    "中山", "阪神", "東京", "京都", "小倉", "新潟", "福島", "札幌", "函館",
    "今日のJRA", "今日の地方", "地方競馬", "JRA",
    "メインレース",
]

_SAME_RACE_KEYWORDS = [
    "予想して", "オッズ", "馬体重", "関係者", "展開", "騎手", "血統", "過去", "直近",
    "どう思う", "全部", "掘り下げ",
]


def _is_same_race_query(text: str) -> bool:
    return any(kw in text for kw in _SAME_RACE_KEYWORDS)


def _needs_race_prompt(text: str) -> bool:
    if detect_query_type(text):
        return True
    return any(kw in text for kw in (
        "予想", "展開", "騎手", "血統", "オッズ", "馬体重", "調教",
        "関係者", "結果", "勝率", "出馬表", "本命比率",
    ))


def _should_prompt_honmei(race_id: str) -> bool:
    if not race_id:
        return False
    try:
        from tools.executor import is_future_or_today_race
        return is_future_or_today_race(race_id)
    except Exception:
        return False


def _build_honmei_quick_replies(race_id: str) -> list[dict]:
    from tools.executor import _race_cache, execute_tool

    if race_id not in _race_cache or "entries" not in _race_cache[race_id]:
        try:
            execute_tool("get_race_entries", {"race_id": race_id})
        except Exception:
            logger.exception(f"Failed to populate entries for honmei: {race_id}")

    entries = _race_cache.get(race_id, {}).get("entries", {})
    horses = entries.get("horses", [])
    horse_numbers = entries.get("horse_numbers", [])
    if not horses or not horse_numbers:
        return []

    items = []
    for i in range(min(len(horses), len(horse_numbers), 18)):
        num = horse_numbers[i]
        name = horses[i]
        items.append({
            "label": f"{num}.{name}"[:20],
            "text": f"本命 {num}番 {name}",
        })
    return items


def _has_pending_honmei(session: dict, profile_id: str) -> bool:
    race_id = session.get("pending_honmei_race") or session.get("active_race_id")
    if not race_id:
        return False
    if not _should_prompt_honmei(race_id):
        session.pop("pending_honmei_race", None)
        return False
    try:
        existing = db_check_prediction(profile_id, race_id)
    except Exception:
        return False
    if existing:
        session.pop("pending_honmei_race", None)
        return False
    return True


def _sse_text_response(text: str, session_id: str, quick_replies: list[dict] | None = None) -> Response:
    if quick_replies is None:
        quick_replies = []

    def generate():
        yield f"data: {json.dumps({'type': 'text', 'content': text}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': quick_replies}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _get_or_create_session(session_id: str, auth_payload: dict | None = None) -> dict:
    """Get existing session or create one. If auth_payload is provided, use Supabase profile."""
    # Authenticated users: key by line_user_id for cross-session persistence
    if auth_payload:
        auth_key = f"auth_{auth_payload['lid']}"
        session = load_session(auth_key)
        if session:
            session["last_active"] = datetime.now(timezone.utc).timestamp()
            save_session(auth_key, session)
            return session

        # Create authenticated session with Supabase profile (LINE Login ID)
        profile = get_or_create_user_by_login(auth_payload["lid"], auth_payload["name"])
        session = {
            "profile": profile,
            "history": [],
            "active_race_id": None,
            "created_at": datetime.now(timezone.utc).timestamp(),
            "last_active": datetime.now(timezone.utc).timestamp(),
        }
        save_session(auth_key, session)
        logger.info(f"New authenticated web session: {auth_payload['name']}")
        return session

    # Anonymous fallback
    session = load_session(session_id)
    if session:
        session["last_active"] = datetime.now(timezone.utc).timestamp()
        save_session(session_id, session)
        return session

    # Create anonymous web profile (no Supabase — lightweight)
    profile = {
        "id": f"web_{session_id[:16]}",
        "display_name": "Webユーザー",
        "visit_count": 1,
        "web_session": True,
    }

    session = {
        "profile": profile,
        "history": [],
        "active_race_id": None,
        "created_at": datetime.now(timezone.utc).timestamp(),
        "last_active": datetime.now(timezone.utc).timestamp(),
    }
    save_session(session_id, session)
    logger.info(f"New web session: {session_id[:16]}...")
    return session


def _cleanup_old_sessions():
    """Remove sessions older than _SESSION_MAX_AGE."""
    if _redis:
        return
    now = datetime.now(timezone.utc).timestamp()
    expired = [
        sid for sid, s in _sessions.items()
        if now - s["last_active"] > _SESSION_MAX_AGE
    ]
    for sid in expired:
        del _sessions[sid]
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired web sessions")


def _normalize_block(block):
    if isinstance(block, dict):
        return block
    if hasattr(block, "type"):
        if block.type == "text":
            return {"type": "text", "text": block.text}
        if block.type == "tool_use":
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        if block.type == "tool_result":
            return {
                "type": "tool_result",
                "tool_use_id": getattr(block, "tool_use_id", ""),
                "content": getattr(block, "content", ""),
            }
    if isinstance(block, str):
        return {"type": "text", "text": block}
    return {"type": "text", "text": str(block)}


def _normalize_history(history: list[dict]) -> list[dict]:
    normalized = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            content = [_normalize_block(b) for b in content]
        normalized.append({"role": role, "content": content})
    return normalized


def _session_key(session_id: str) -> str:
    return f"{_SESSION_PREFIX}{session_id}"


def load_session(session_id: str) -> dict | None:
    if _redis:
        try:
            raw = _redis.get(_session_key(session_id))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.exception("Failed to load session from Redis")
    return _sessions.get(session_id)


def save_session(session_id: str, session: dict) -> None:
    payload = dict(session)
    payload["history"] = _normalize_history(payload.get("history", []))
    if _redis:
        try:
            _redis.setex(_session_key(session_id), _SESSION_MAX_AGE,
                         json.dumps(payload, ensure_ascii=False))
        except Exception:
            logger.exception("Failed to save session to Redis")
    _sessions[session_id] = payload


@bp.route("/api/chat", methods=["POST"])
def chat():
    """SSE streaming chat endpoint."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    session_id = data.get("session_id", "")
    message = data.get("message", "").strip()
    query_type = (data.get("query_type") or "").strip()

    if not session_id:
        session_id = str(uuid.uuid4())
    if not message:
        return jsonify({"error": "Empty message"}), 400

    # Periodic cleanup
    if len(_sessions) > 100:
        _cleanup_old_sessions()

    # Maintenance mode check
    try:
        if is_maintenance_mode():
            msg = get_maintenance_message() or "ただいまメンテナンス中です。"
            def _maint_response():
                yield f"data: {json.dumps({'type': 'text', 'content': f'🔧 {msg}'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': []}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return Response(_maint_response(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except Exception:
        pass  # fail-open: if DB is down, allow requests through

    auth_payload = verify_auth_header()
    session = _get_or_create_session(session_id, auth_payload)
    session_key = f"auth_{auth_payload['lid']}" if auth_payload else session_id
    profile = session["profile"]
    history = session["history"]

    if auth_payload:
        try:
            status = get_user_status(profile["id"])
        except Exception:
            status = "active"

        if status == "waitlist":
            def _waitlist_response():
                msg = (
                    "今めちゃくちゃ登録が殺到しててよ、順番に案内してるんだ。\n"
                    "お前の番が来たらすぐ連絡するから、もうちょい待っててくれ！💪"
                )
                yield f"data: {json.dumps({'type': 'text', 'content': msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': []}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return Response(_waitlist_response(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        if status == "suspended":
            def _suspended_response():
                msg = (
                    "悪いな、お前のアカウントは今ちょっと止まってるんだ。\n"
                    "何かあったらここから連絡してくれ👇\n"
                    "https://lin.ee/73wrNkv"
                )
                yield f"data: {json.dumps({'type': 'text', 'content': msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': []}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return Response(_suspended_response(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Auto-resolve explicit race hints (venue + R, race_id)
    resolved_race = resolve_race_id_from_text(message)
    if resolved_race:
        session["active_race_id"] = resolved_race
        save_session(session_key, session)

    if not session.get("active_race_id") and _needs_race_prompt(message):
        return _sse_text_response(
            "どのレースの話だ？\n\n例: 中山11R / 阪神10レース / 20260319-中山-11",
            session_id,
        )

    # --- Handle 「引き継ぎコード」request (no code provided) → redirect to LINE app ---
    if message in ("引き継ぎコード", "引継ぎコード", "連携コード", "アカウント連携", "記憶コピー", "記憶コピーコード"):
        redirect_msg = (
            "📱 連携コードはLINEアプリのDロジくんから取得してください！\n\n"
            "① LINEアプリを開く\n"
            "② Dロジくんに「引き継ぎコード」と送信\n"
            "③ 届いたコードをマイページに入力\n\n"
            "Webチャットからは連携コードを取得できません。"
        )
        def _redirect_response():
            yield f"data: {json.dumps({'type': 'text', 'content': redirect_msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': []}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return Response(_redirect_response(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- Handle 「引き継ぎ XXXXXX」or「記憶コピー XXXXXX」 ---
    transfer_match = re.match(r"(?:引き継ぎ|記憶コピー)\s+([A-Za-z0-9]{4,8})", message)
    if transfer_match and auth_payload:
        input_code = transfer_match.group(1).strip().upper()
        own_code = profile.get("transfer_code", "")

        if own_code and own_code == input_code:
            msg = "それはあなた自身のコードです！別のアカウントのコードを入力してください。"
        else:
            from db.supabase_client import get_client
            sb = get_client()
            try:
                res = sb.table("user_profiles") \
                    .select("*") \
                    .eq("transfer_code", input_code) \
                    .limit(1) \
                    .execute()
            except Exception:
                res = type("R", (), {"data": []})()

            if not res.data:
                msg = "そのコードは見つかりませんでした。もう一度確認してください。"
            else:
                source = res.data[0]
                # Bidirectional sync: copy memories/stats between both profiles
                try:
                    synced = sync_profiles(profile["id"], source["id"])
                except Exception:
                    synced = False

                if synced:
                    # Refresh session profile to pick up synced fields
                    try:
                        refreshed = sb.table("user_profiles").select("*").eq("id", profile["id"]).limit(1).execute()
                        if refreshed.data:
                            session["profile"] = refreshed.data[0]
                    except Exception:
                        pass
                    msg = "🎉 アカウント連携完了！データが統合されました。"
                    logger.info(f"Web account sync: {profile['id'][:10]}... <-> {source['id'][:10]}...")
                else:
                    msg = "連携でエラーが発生しました。もう一度試してください。"

        def _link_response():
            yield f"data: {json.dumps({'type': 'text', 'content': msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'quick_replies': []}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return Response(_link_response(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- Honmei (本命) selection handler for Web ---
    if message.startswith("本命 ") or message.startswith("本命:"):
        if not auth_payload or profile.get("web_session"):
            return _sse_text_response("本命登録はLINEログインが必要です。", session_id)

        match = re.match(r"本命[:\s]+(\d+)番?\s*(.*)", message)
        if not match:
            return _sse_text_response("馬番がわからなかった...もう一回タップしてくれ！", session_id)

        horse_number = int(match.group(1))
        horse_name = match.group(2).strip() or f"{horse_number}番"
        race_id = session.get("pending_honmei_race") or session.get("active_race_id")

        if race_id:
            venue = ""
            try:
                from tools.executor import _race_cache
                if race_id in _race_cache and "entries" in _race_cache[race_id]:
                    venue = _race_cache[race_id]["entries"].get("venue", "")
                db_record_prediction(
                    user_profile_id=profile["id"],
                    race_id=race_id,
                    horse_number=horse_number,
                    horse_name=horse_name,
                    race_name="",
                    venue=venue,
                )
                session.pop("pending_honmei_race", None)
                save_session(session_key, session)
                return _sse_text_response(
                    f"👊 {horse_number}番 {horse_name} を本命で登録したぜ！\n\n"
                    "みんなの予想に追加したからな。結果出たら回収率も計算してやるよ。",
                    session_id,
                )
            except Exception:
                logger.exception("Failed to record web honmei")
                return _sse_text_response("ごめん、登録でエラーが出ちゃった。もう一回試してくれ！", session_id)

        return _sse_text_response("レースを先に見てから本命を選んでくれ！", session_id)

    # --- Honmei blocking: pending pick ---
    if auth_payload and not profile.get("web_session"):
        if _has_pending_honmei(session, profile["id"]) and not _is_same_race_query(message):
            pending_race = session.get("pending_honmei_race") or session.get("active_race_id")
            honmei_items = _build_honmei_quick_replies(pending_race) if pending_race else []
            if honmei_items:
                save_session(session_key, session)
                return _sse_text_response(
                    "おっと、ちょっと待ってくれ！\n\n"
                    "今Dlogicじゃ「みんなの予想」を集めてるんだ。\n"
                    "みんなの本命を集計して、回収率ランキングとか出していく予定なんだよ。\n\n"
                    "どうか協力してやってくれ🙏\n\n"
                    "👇 下のボタンから本命をタップ！",
                    session_id,
                    honmei_items,
                )

    # Trim history to prevent unbounded growth
    history = trim_history(history)
    session["history"] = history

    # --- Fast path: query_type provided (skip LLM) ---
    route = _route_from_query_type(query_type)
    if route:
        route_name, route_params = route
        history.append({"role": "user", "content": message})
        result = route_and_respond(
            route_name,
            route_params,
            profile.get("id", ""),
            history,
            profile,
            active_race_id_hint=session.get("active_race_id"),
        )
        if result:
            for entry in result.get("history_entries", []):
                history.append(entry)

            full_text = result["text"]
            if result.get("footer"):
                full_text += "\n\n" + result["footer"]

            if result.get("active_race_id"):
                session["active_race_id"] = result["active_race_id"]
            session["history"] = history
            save_session(session_key, session)

            # Save to response cache for non-query_type callers
            save_qt = detect_query_type(message)
            if save_qt and result.get("active_race_id"):
                save_cached_response(result["active_race_id"], save_qt,
                                     result["text"], result.get("footer", ""), result["tools_used"])

            quick_replies = get_web_quick_replies(result["tools_used"])
            return _sse_text_response(full_text, session_id, quick_replies)
        else:
            history.pop()

    def generate():
        try:
            for chunk in run_agent(
                user_message=message,
                history=history,
                profile=profile,
                active_race_id_hint=session.get("active_race_id"),
            ):
                chunk_type = chunk.get("type")

                if chunk_type == "thinking":
                    yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

                elif chunk_type == "tool":
                    tool_name = chunk.get("name", "")
                    label = TOOL_LABELS.get(tool_name, tool_name)
                    yield f"data: {json.dumps({'type': 'tool', 'name': tool_name, 'label': label}, ensure_ascii=False)}\n\n"

                elif chunk_type == "done":
                    # Update session state
                    session["history"] = chunk.get("history", history)
                    if chunk.get("active_race_id"):
                        session["active_race_id"] = chunk["active_race_id"]

                    full_text = chunk["text"]
                    quick_replies = chunk.get("quick_replies", [])
                    tools_used = chunk.get("tools_used", [])
                    active_race_id = chunk.get("active_race_id")

                    # Honmei (みんなの予想) prompt for authenticated users
                    if auth_payload and not profile.get("web_session") and active_race_id:
                        used_set = set(tools_used)
                        if used_set & {"get_race_entries", "get_predictions"}:
                            try:
                                already_picked = db_check_prediction(profile["id"], active_race_id)
                            except Exception:
                                already_picked = True
                            if not already_picked and _should_prompt_honmei(active_race_id):
                                session["pending_honmei_race"] = active_race_id
                                honmei_items = _build_honmei_quick_replies(active_race_id)
                                if honmei_items:
                                    full_text += (
                                        "\n\n━━━━━━━━\n"
                                        "📢 みんなの予想\n"
                                        "━━━━━━━━\n\n"
                                        "お前の本命を教えてくれ！👇"
                                    )
                                    quick_replies = honmei_items
                            else:
                                session.pop("pending_honmei_race", None)

                    save_session(session_key, session)

                    yield f"data: {json.dumps({'type': 'text', 'content': full_text}, ensure_ascii=False)}\n\n"
                    done_data = {
                        "type": "done",
                        "session_id": session_id,
                        "quick_replies": quick_replies,
                    }
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception(f"WebChat error for session {session_id[:16]}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'エラーが発生しました。もう一度お試しください。'}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx SSE support
        },
    )


@bp.route("/api/chat/sessions", methods=["POST"])
def create_session():
    """Create a new session and return session_id."""
    session_id = str(uuid.uuid4())
    _get_or_create_session(session_id)
    return jsonify({"session_id": session_id})


@bp.route("/api/chat/health", methods=["GET"])
def chat_health():
    """Health check for the chat API."""
    return jsonify({
        "status": "ok",
        "active_sessions": len(_sessions),
    })
