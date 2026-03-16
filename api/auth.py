"""LINE Login OAuth endpoints for web chat authentication.

POST /api/chatauth/line   — Exchange LINE auth code for JWT session token
POST /api/chatauth/liff   — Exchange LIFF access token for JWT session token
GET  /api/chatauth/me     — Validate token and return user profile
"""

import hashlib
import hmac
import json
import logging
import os
import time

import requests
from flask import Blueprint, request, jsonify

from db.supabase_client import get_client
from db.user_manager import (
    get_or_create_user,
    get_or_create_user_by_login,
    link_login_to_profile,
    merge_profiles,
)
from config import ADMIN_PROFILE_IDS

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
# Login history
# ---------------------------------------------------------------------------

def _record_login_history(profile_id: str):
    """Record a login event to login_history table."""
    try:
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        # Take the first IP if X-Forwarded-For has multiple
        if "," in ip_address:
            ip_address = ip_address.split(",")[0].strip()
        user_agent = request.headers.get("User-Agent", "")[:500]

        sb = get_client()
        sb.table("login_history").insert({
            "user_id": profile_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }).execute()
    except Exception:
        logger.exception(f"Failed to record login history for {profile_id}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@bp.route("/api/chatauth/line", methods=["POST"])
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

    # Upsert user in Supabase using LINE Login ID
    try:
        profile = get_or_create_user_by_login(line_user_id, display_name)
        profile_id = profile["id"]
    except Exception as e:
        logger.error(f"Supabase user creation error: {e}")
        return jsonify({"error": "ユーザー登録エラー"}), 500

    # Use the DB profile's display_name (respects custom_name flag)
    db_display_name = profile.get("display_name", display_name)

    # Create session token
    token = _create_token(profile_id, line_user_id, db_display_name)

    # Record login history
    _record_login_history(profile_id)

    logger.info(f"LINE Login success: {db_display_name} ({line_user_id[:10]}...)")

    return jsonify({
        "token": token,
        "user": {
            "id": profile_id,
            "display_name": db_display_name,
            "status": profile.get("status", "active"),
            "is_admin": profile_id in ADMIN_PROFILE_IDS,
        },
    })


@bp.route("/api/chatauth/liff", methods=["POST"])
def liff_login():
    """Authenticate using LIFF access token (from LINE app)."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    access_token = data.get("access_token", "")
    if not access_token:
        return jsonify({"error": "Missing access_token"}), 400

    # Get LINE profile using the LIFF access token
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
        logger.error(f"LIFF profile fetch error: {e}")
        return jsonify({"error": "LINEプロフィール取得エラー"}), 500

    # Upsert user in Supabase using LINE Login ID
    try:
        profile = get_or_create_user_by_login(line_user_id, display_name)
        profile_id = profile["id"]
    except Exception as e:
        logger.error(f"Supabase user creation error: {e}")
        return jsonify({"error": "ユーザー登録エラー"}), 500

    # Use the DB profile's display_name (respects custom_name flag)
    db_display_name = profile.get("display_name", display_name)

    token = _create_token(profile_id, line_user_id, db_display_name)

    # Record login history
    _record_login_history(profile_id)

    logger.info(f"LIFF Login success: {db_display_name} ({line_user_id[:10]}...)")

    return jsonify({
        "token": token,
        "user": {
            "id": profile_id,
            "display_name": db_display_name,
            "status": profile.get("status", "active"),
            "is_admin": profile_id in ADMIN_PROFILE_IDS,
        },
    })


@bp.route("/api/chatauth/me", methods=["GET"])
def me():
    """Return current user profile from token."""
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    # Fetch current display_name from DB (token may have stale name)
    profile_id = payload["pid"]
    display_name = payload["name"]
    try:
        sb = get_client()
        res = sb.table("user_profiles").select("display_name").eq("id", profile_id).limit(1).execute()
        if res.data:
            display_name = res.data[0].get("display_name", display_name)
    except Exception:
        pass  # Fall back to token name

    return jsonify({
        "user": {
            "id": profile_id,
            "display_name": display_name,
            "is_admin": profile_id in ADMIN_PROFILE_IDS,
        },
    })


@bp.route("/api/chatauth/link", methods=["POST"])
def link_account():
    """Link web account to existing Dlogic LINE Bot account using transfer code.

    POST body: {"transfer_code": "ABC123"}
    """
    payload = verify_auth_header()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data or not data.get("transfer_code"):
        return jsonify({"error": "引き継ぎコードを入力してください"}), 400

    transfer_code = data["transfer_code"].strip().upper()
    line_login_id = payload["lid"]
    current_profile_id = payload["pid"]

    sb = get_client()

    # Find the Dlogic profile by transfer code
    res = sb.table("user_profiles") \
        .select("*") \
        .eq("transfer_code", transfer_code) \
        .limit(1) \
        .execute()

    if not res.data:
        return jsonify({"error": "引き継ぎコードが見つかりません"}), 404

    target_profile = res.data[0]
    target_id = target_profile["id"]

    # Already the same profile
    if target_id == current_profile_id:
        return jsonify({"message": "既に連携済みです", "user": {
            "id": target_id,
            "display_name": target_profile["display_name"],
        }})

    # Check if target already has a different line_login_id
    if target_profile.get("line_login_id") and target_profile["line_login_id"] != line_login_id:
        return jsonify({"error": "このアカウントは既に別のWebアカウントと連携されています"}), 409

    # Link: set line_login_id on the target (Dlogic) profile
    if not link_login_to_profile(target_id, line_login_id):
        return jsonify({"error": "連携に失敗しました"}), 500

    # Merge: move data from current web profile to target, delete web profile
    if current_profile_id != target_id:
        merge_profiles(target_id, current_profile_id)

    # Issue new token pointing to the merged profile
    new_token = _create_token(target_id, line_login_id, target_profile["display_name"])

    logger.info(f"Account linked: web={current_profile_id[:10]}... -> dlogic={target_id[:10]}...")

    return jsonify({
        "message": "連携完了！Dロジくんのデータが引き継がれました",
        "token": new_token,
        "user": {
            "id": target_id,
            "display_name": target_profile["display_name"],
            "visit_count": target_profile["visit_count"],
        },
    })
