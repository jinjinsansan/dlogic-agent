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
from db.user_manager import get_or_create_user, build_user_context as db_build_user_context

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

        # Create authenticated session with Supabase profile
        profile = get_or_create_user(auth_payload["lid"], auth_payload["name"])
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

    auth_payload = verify_auth_header()
    session = _get_or_create_session(session_id, auth_payload)
    profile = session["profile"]
    history = session["history"]

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
