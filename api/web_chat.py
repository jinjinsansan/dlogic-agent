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

from agent.chat_core import run_agent
from agent.engine import TOOL_LABELS, trim_history
from api.auth import verify_auth_header
import re

from db.user_manager import (
    get_or_create_user, get_or_create_user_by_login,
    build_user_context as db_build_user_context,
    sync_profiles,
    is_maintenance_mode, get_maintenance_message,
)

logger = logging.getLogger(__name__)

bp = Blueprint("web_chat", __name__)

# In-memory session store (keyed by web_session_id)
# Each session holds: profile, history, active_race_id
_sessions: dict[str, dict] = {}

# Session TTL: clean up sessions older than 6 hours
_SESSION_MAX_AGE = 6 * 3600


def _get_or_create_session(session_id: str, auth_payload: dict | None = None) -> dict:
    """Get existing session or create one. If auth_payload is provided, use Supabase profile."""
    # Authenticated users: key by line_user_id for cross-session persistence
    if auth_payload:
        auth_key = f"auth_{auth_payload['lid']}"
        if auth_key in _sessions:
            session = _sessions[auth_key]
            session["last_active"] = datetime.now(timezone.utc).timestamp()
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
        _sessions[auth_key] = session
        logger.info(f"New authenticated web session: {auth_payload['name']}")
        return session

    # Anonymous fallback
    if session_id in _sessions:
        session = _sessions[session_id]
        session["last_active"] = datetime.now(timezone.utc).timestamp()
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
    _sessions[session_id] = session
    logger.info(f"New web session: {session_id[:16]}...")
    return session


def _cleanup_old_sessions():
    """Remove sessions older than _SESSION_MAX_AGE."""
    now = datetime.now(timezone.utc).timestamp()
    expired = [
        sid for sid, s in _sessions.items()
        if now - s["last_active"] > _SESSION_MAX_AGE
    ]
    for sid in expired:
        del _sessions[sid]
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired web sessions")


@bp.route("/api/chat", methods=["POST"])
def chat():
    """SSE streaming chat endpoint."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    session_id = data.get("session_id", "")
    message = data.get("message", "").strip()

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
    profile = session["profile"]
    history = session["history"]

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

    # Trim history to prevent unbounded growth
    history = trim_history(history)
    session["history"] = history

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

                    yield f"data: {json.dumps({'type': 'text', 'content': chunk['text']}, ensure_ascii=False)}\n\n"
                    done_data = {
                        'type': 'done',
                        'session_id': session_id,
                        'quick_replies': chunk.get('quick_replies', []),
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
