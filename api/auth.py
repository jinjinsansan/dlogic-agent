"""LINE Login OAuth endpoints for web chat authentication.

POST /api/auth/line   — Exchange LINE auth code for JWT session token
GET  /api/auth/me     — Validate token and return user profile
"""

import hashlib
import hmac
import json
import logging
import os
import time

import requests
from flask import Blueprint, request, jsonify

from db.user_manager import get_or_create_user

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID", "")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET", "")
WEB_AUTH_SECRET = os.getenv("WEB_AUTH_SECRET", "dlogic-web-auth-secret-key-2026")

TOKEN_EXPIRY = 7 * 24 * 3600  # 7 days


# ---------------------------------------------------------------------------
# Simple JWT-like token (HMAC-SHA256, no external dependency)
# ---------------------------------------------------------------------------

def _create_token(profile_id: str, line_user_id: str, display_name: str) -> str:
    """Create a signed token containing user info."""
    payload = {
        "pid": profile_id,
        "lid": line_user_id,
        "name": display_name,
        "exp": int(time.time()) + TOKEN_EXPIRY,
    }
    data = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(WEB_AUTH_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    # base64-like encoding without dependency: just hex
    return f"{data.encode().hex()}.{sig}"


def _verify_token(token: str) -> dict | None:
    """Verify token and return payload, or None if invalid."""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        data_hex, sig = parts
        data = bytes.fromhex(data_hex).decode()
        expected_sig = hmac.new(WEB_AUTH_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(data)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def verify_auth_header() -> dict | None:
    """Extract and verify token from Authorization header. Returns payload or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return _verify_token(auth[7:])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@bp.route("/api/auth/line", methods=["POST"])
def line_login():
    """Exchange LINE Login authorization code for a session token."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    code = data.get("code", "")
    redirect_uri = data.get("redirect_uri", "")

    if not code or not redirect_uri:
        return jsonify({"error": "Missing code or redirect_uri"}), 400

    if not LINE_LOGIN_CHANNEL_ID or not LINE_LOGIN_CHANNEL_SECRET:
        logger.error("LINE Login credentials not configured")
        return jsonify({"error": "Server configuration error"}), 500

    # Exchange code for access token
    try:
        token_resp = requests.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": LINE_LOGIN_CHANNEL_ID,
                "client_secret": LINE_LOGIN_CHANNEL_SECRET,
            },
            timeout=10,
        )
        if token_resp.status_code != 200:
            logger.error(f"LINE token exchange failed: {token_resp.status_code} {token_resp.text[:200]}")
            return jsonify({"error": "LINE認証に失敗しました"}), 401

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return jsonify({"error": "No access token"}), 401

    except Exception as e:
        logger.error(f"LINE token exchange error: {e}")
        return jsonify({"error": "LINE認証エラー"}), 500

    # Get LINE profile
    try:
        profile_resp = requests.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if profile_resp.status_code != 200:
            return jsonify({"error": "LINEプロフィール取得に失敗しました"}), 401

        line_profile = profile_resp.json()
        line_user_id = line_profile.get("userId", "")
        display_name = line_profile.get("displayName", "Webユーザー")

        if not line_user_id:
            return jsonify({"error": "LINE user ID not found"}), 401

    except Exception as e:
        logger.error(f"LINE profile fetch error: {e}")
        return jsonify({"error": "LINEプロフィール取得エラー"}), 500

    # Upsert user in Supabase (same function as LINE Bot)
    try:
        profile = get_or_create_user(line_user_id, display_name)
        profile_id = profile["id"]
    except Exception as e:
        logger.error(f"Supabase user creation error: {e}")
        return jsonify({"error": "ユーザー登録エラー"}), 500

    # Create session token
    token = _create_token(profile_id, line_user_id, display_name)

    logger.info(f"LINE Login success: {display_name} ({line_user_id[:10]}...)")

    return jsonify({
        "token": token,
        "user": {
            "id": profile_id,
            "display_name": display_name,
            "status": profile.get("status", "active"),
        },
    })


@bp.route("/api/auth/me", methods=["GET"])
def me():
    """Return current user profile from token."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify({
        "user": {
            "id": payload["pid"],
            "display_name": payload["name"],
        },
    })
