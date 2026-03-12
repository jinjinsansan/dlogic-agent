"""
Data API — レースデータを外部プロジェクト（dlogic-note等）に提供するREST API
既存のスクレイパー/プリフェッチ/アーカイブをHTTPエンドポイントとして公開する
"""
import json
import logging
from flask import Blueprint, request, jsonify

from tools.executor import _get_today_races, _get_race_entries

logger = logging.getLogger(__name__)

bp = Blueprint("data_api", __name__, url_prefix="/api/data")


@bp.route("/races", methods=["GET"])
def get_races():
    """
    レース一覧を取得

    Query params:
        date: YYYYMMDD (default: today)
        type: jra or nar (default: jra)
        venue: 競馬場名フィルタ (optional)

    Returns:
        { races: [...], count: int }
    """
    params = {
        "date": request.args.get("date", ""),
        "race_type": request.args.get("type", "jra"),
        "venue": request.args.get("venue", ""),
    }
    # Remove empty strings so executor uses defaults
    params = {k: v for k, v in params.items() if v}
    if "race_type" not in params:
        params["race_type"] = "jra"

    try:
        result_json = _get_today_races(params)
        return jsonify(json.loads(result_json))
    except Exception as e:
        logger.error(f"Data API /races error: {e}")
        return jsonify({"error": str(e), "races": [], "count": 0}), 500


@bp.route("/entries/<race_id>", methods=["GET"])
def get_entries(race_id: str):
    """
    出馬表を取得

    Path params:
        race_id: netkeiba race ID

    Query params:
        type: jra or nar (default: jra)

    Returns:
        { race_id, race_name, venue, distance, entries: [...], ... }
    """
    params = {
        "race_id": race_id,
        "race_type": request.args.get("type", "jra"),
    }

    try:
        result_json = _get_race_entries(params)
        return jsonify(json.loads(result_json))
    except Exception as e:
        logger.error(f"Data API /entries error: {e}")
        return jsonify({"error": str(e)}), 500
