"""
Data API — レースデータを外部プロジェクト（dlogic-note等）に提供するREST API
既存のスクレイパー/プリフェッチ/アーカイブをHTTPエンドポイントとして公開する
"""
import json
import logging
import os
from collections import Counter
from datetime import datetime
from flask import Blueprint, request, jsonify

SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'golden_history'
)

from tools.executor import (
    _get_today_races, _get_race_entries, _resolve_netkeiba_race_id,
    _get_predictions, _load_prefetch,
)
from scrapers.odds import fetch_realtime_odds
from db.supabase_client import get_client

logger = logging.getLogger(__name__)

bp = Blueprint("data_api", __name__, url_prefix="/api/data")

# Golden pattern config (audit v2 + weekday_strict_search 2026-04-26)
GOLDEN_BEST_VENUES = {"園田", "水沢", "高知", "笠松", "金沢"}
GOLDEN_BEST_WEEKDAYS = {1, 2, 3}  # Tue=1, Wed=2, Thu=3 (Mon=0)
GOLDEN_ENGINE_KEYS = ["Dlogic", "Ilogic", "ViewLogic", "MetaLogic"]

# Per-weekday strict patterns (Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6)
# Each pattern requires: is_nar=True + cons_count in (2,3) + pop_rank in allowed buckets
# Sat(5)/Sun(6) → no strict (all-loss territory in current data)
GOLDEN_PER_WEEKDAY = {
    0: {  # Mon: 1人気 or 6-8人気
        "name": "月",
        "pop_buckets": {1, 6, 7, 8},
        "venues": None,  # 全NAR会場OK
    },
    1: {  # Tue: 火水木 classic strict (5強会場 + 6-12頭 + 5-8人気)
        "name": "火",
        "pop_buckets": {5, 6, 7, 8},
        "venues": GOLDEN_BEST_VENUES,
        "field_min": 6,
        "field_max": 12,
    },
    2: {  # Wed: same
        "name": "水",
        "pop_buckets": {5, 6, 7, 8},
        "venues": GOLDEN_BEST_VENUES,
        "field_min": 6,
        "field_max": 12,
    },
    3: {  # Thu: same (4-8人気拡張も検討余地あり)
        "name": "木",
        "pop_buckets": {5, 6, 7, 8},
        "venues": GOLDEN_BEST_VENUES,
        "field_min": 6,
        "field_max": 12,
    },
    4: {  # Fri: 4-5人気
        "name": "金",
        "pop_buckets": {4, 5},
        "venues": None,
    },
    5: None,  # Sat: 配信なし
    6: None,  # Sun: 配信なし
}


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


@bp.route("/odds/<race_id>", methods=["GET"])
def get_odds(race_id: str):
    """
    リアルタイムオッズを取得（Lightpanda経由）

    Path params:
        race_id: custom or netkeiba race ID

    Query params:
        type: jra or nar (default: jra)

    Returns:
        { race_id, odds: {horse_number: odds_value, ...} }
    """
    race_type = request.args.get("type", "jra")

    try:
        netkeiba_id = _resolve_netkeiba_race_id(race_id, race_type)
        odds = fetch_realtime_odds(netkeiba_id, race_type)
        return jsonify({"race_id": race_id, "odds": odds or {}})
    except Exception as e:
        logger.error(f"Data API /odds error: {e}")
        return jsonify({"error": str(e), "odds": {}}), 500


def _fetch_results_for_date(date_str: str) -> dict:
    """Fetch all finished race results for a given date. Returns {race_id: result_dict}."""
    if len(date_str) != 8:
        return {}
    date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    try:
        sb = get_client()
        res = sb.table("race_results").select(
            "race_id,winner_number,win_payout,result_json,status"
        ).eq("race_date", date_iso).execute()
        out = {}
        for r in (res.data or []):
            if r.get("status") != "finished":
                continue
            rj = r.get("result_json")
            if isinstance(rj, str):
                try:
                    rj = json.loads(rj)
                except Exception:
                    rj = None
            r["result_json"] = rj
            out[r["race_id"]] = r
        return out
    except Exception as e:
        logger.warning(f"_fetch_results_for_date failed: {e}")
        return {}


def _build_race_result(eval_result: dict, race_result: dict | None) -> dict | None:
    """Attach race outcome and golden-pattern P/L info."""
    if not race_result:
        return None
    rj = race_result.get("result_json") or {}
    top3 = rj.get("top3") or []
    cons_horse = eval_result.get("consensus", {}).get("horse_number")
    winner_number = race_result.get("winner_number")
    win_payout = race_result.get("win_payout") or 0

    top3_numbers = [t.get("horse_number") for t in top3 if t.get("horse_number") is not None]
    did_win = bool(cons_horse and cons_horse == winner_number)
    did_place = bool(cons_horse and cons_horse in top3_numbers)

    # Profit only meaningful when the race was a buy candidate (loose or strict)
    is_buy = eval_result.get("is_golden_loose") or eval_result.get("is_golden_strict")
    profit = None
    if is_buy:
        profit = (win_payout - 100) if did_win else -100

    return {
        "status": "finished",
        "winner_number": winner_number,
        "win_payout": win_payout,
        "top3": top3,
        "did_consensus_win": did_win,
        "did_consensus_place": did_place,
        "profit_yen": profit,
    }


def _evaluate_golden_pattern(race: dict, weekday: int) -> dict:
    """Compute consensus, popularity, and golden flags for a single race."""
    horse_numbers = race.get("horse_numbers") or []
    horses = race.get("horses") or []
    odds_arr = race.get("odds") or []
    horse_map = {n: (horses[i] if i < len(horses) else "") for i, n in enumerate(horse_numbers)}

    # Popularity rank from odds (lower odds = more favored)
    pop_rank_map = {}
    if odds_arr and len(odds_arr) == len(horse_numbers):
        valid_pairs = [(n, o) for n, o in zip(horse_numbers, odds_arr) if o is not None and o > 0]
        sorted_pairs = sorted(valid_pairs, key=lambda x: x[1])
        pop_rank_map = {hn: i + 1 for i, (hn, _) in enumerate(sorted_pairs)}

    # Get engine predictions
    pred_params = {
        "race_id": race.get("race_id", ""),
        "horses": horses,
        "horse_numbers": horse_numbers,
        "venue": race.get("venue", ""),
        "race_number": race.get("race_number", 0),
        "jockeys": race.get("jockeys", []),
        "posts": race.get("posts", []),
        "distance": race.get("distance", ""),
        "track_condition": race.get("track_condition", "良"),
    }
    engine_picks = {}
    try:
        preds_json = _get_predictions(pred_params)
        preds_data = json.loads(preds_json)
        preds = preds_data.get("predictions", {})
        for label in GOLDEN_ENGINE_KEYS:
            arr = preds.get(label)
            if isinstance(arr, list) and arr:
                top1 = arr[0]
                engine_picks[label.lower()] = {
                    "horse_number": top1.get("horse_number"),
                    "horse_name": top1.get("horse_name", ""),
                }
    except Exception as e:
        logger.warning(f"predictions failed for {race.get('race_id')}: {e}")

    # Consensus
    pick_nums = [p["horse_number"] for p in engine_picks.values() if p.get("horse_number")]
    cons_horse, cons_count, agreed = None, 0, []
    if pick_nums:
        counter = Counter(pick_nums)
        cons_horse, cons_count = counter.most_common(1)[0]
        agreed = [eng for eng, p in engine_picks.items() if p.get("horse_number") == cons_horse]

    cons_pop = pop_rank_map.get(cons_horse) if cons_horse else None

    # Filters
    is_nar = bool(race.get("is_local"))
    venue = race.get("venue", "")
    total_horses = len(horse_numbers)
    is_loose = (
        cons_count in (2, 3)
        and cons_pop is not None
        and 5 <= cons_pop <= 8
    )
    # Per-weekday strict: each weekday has its own filter
    is_strict = False
    wd_pattern = GOLDEN_PER_WEEKDAY.get(weekday)
    if (wd_pattern is not None
            and is_nar
            and cons_count in (2, 3)
            and cons_pop is not None
            and cons_pop in wd_pattern["pop_buckets"]):
        # Optional venue filter
        venue_ok = (wd_pattern.get("venues") is None
                    or venue in wd_pattern["venues"])
        # Optional field-size filter
        field_min = wd_pattern.get("field_min")
        field_max = wd_pattern.get("field_max")
        field_ok = True
        if field_min is not None and total_horses < field_min:
            field_ok = False
        if field_max is not None and total_horses > field_max:
            field_ok = False
        if venue_ok and field_ok:
            is_strict = True

    return {
        "engine_picks": engine_picks,
        "consensus": {
            "horse_number": cons_horse,
            "horse_name": horse_map.get(cons_horse, "") if cons_horse else "",
            "agreed_engines": agreed,
            "count": cons_count,
        },
        "popularity_rank": cons_pop,
        "is_golden_loose": is_loose,
        "is_golden_strict": is_strict,
    }


@bp.route("/golden-pattern/today", methods=["GET"])
def get_golden_pattern_today():
    """Return today's races with golden-pattern annotations.

    Query params:
        date: YYYYMMDD (default: today)
        race_type: jra | nar | both (default: both)

    Returns:
        { date, weekday, summary: {total, loose, strict}, races: [...] }
    """
    date_str = request.args.get("date", datetime.now().strftime("%Y%m%d"))
    race_type = request.args.get("race_type", "both")

    try:
        weekday = datetime.strptime(date_str, "%Y%m%d").weekday()
    except ValueError:
        return jsonify({"error": "invalid date format, use YYYYMMDD"}), 400

    prefetch = _load_prefetch(date_str)
    if not prefetch:
        # Fallback: load saved snapshot (preserved beyond prefetch retention)
        snapshot_path = os.path.join(SNAPSHOT_DIR, f"{date_str}.json")
        if os.path.exists(snapshot_path):
            try:
                with open(snapshot_path, 'r', encoding='utf-8') as f:
                    snap = json.load(f)
                # Re-filter by race_type if requested
                if race_type in ("jra", "nar") and snap.get("races"):
                    is_local_filter = (race_type == "nar")
                    snap["races"] = [r for r in snap["races"] if bool(r.get("is_local")) == is_local_filter]
                snap["source"] = "snapshot"
                return jsonify(snap)
            except Exception as e:
                logger.warning(f"snapshot load failed for {date_str}: {e}")
        return jsonify({
            "error": "prefetch data not available for this date",
            "date": date_str,
            "races": [],
        }), 404

    races = prefetch.get("races", [])
    if race_type == "jra":
        races = [r for r in races if not r.get("is_local")]
    elif race_type == "nar":
        races = [r for r in races if r.get("is_local")]

    # Fetch results for all races on this date (single query)
    results_by_id = _fetch_results_for_date(date_str)

    enriched = []
    summary = {
        "total": 0,
        "loose_golden": 0, "strict_golden": 0,
        "loose_finished": 0, "strict_finished": 0,
        "loose_hits": 0, "strict_hits": 0,
        "loose_profit": 0, "strict_profit": 0,
    }

    for r in races:
        eval_result = _evaluate_golden_pattern(r, weekday)
        summary["total"] += 1
        is_loose = eval_result["is_golden_loose"]
        is_strict = eval_result["is_golden_strict"]
        if is_loose: summary["loose_golden"] += 1
        if is_strict: summary["strict_golden"] += 1

        race_result = _build_race_result(eval_result, results_by_id.get(r.get("race_id", "")))
        if race_result and is_loose:
            summary["loose_finished"] += 1
            if race_result["did_consensus_win"]:
                summary["loose_hits"] += 1
            if race_result.get("profit_yen") is not None:
                summary["loose_profit"] += race_result["profit_yen"]
        if race_result and is_strict:
            summary["strict_finished"] += 1
            if race_result["did_consensus_win"]:
                summary["strict_hits"] += 1
            if race_result.get("profit_yen") is not None:
                summary["strict_profit"] += race_result["profit_yen"]

        enriched.append({
            "race_id": r.get("race_id", ""),
            "venue": r.get("venue", ""),
            "race_number": r.get("race_number", 0),
            "race_name": r.get("race_name", ""),
            "start_time": r.get("start_time", ""),
            "is_local": bool(r.get("is_local")),
            "distance": r.get("distance", ""),
            "track_condition": r.get("track_condition", "−"),
            "total_horses": len(r.get("horse_numbers") or []),
            **eval_result,
            "result": race_result,
        })

    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][weekday]
    return jsonify({
        "date": date_str,
        "weekday": weekday_ja,
        "summary": summary,
        "races": enriched,
    })
