"""Tool execution logic - bridges Claude tool calls to actual data fetching."""

import json
import logging
import math
import os
import re
import time
from datetime import datetime

import requests

from config import DLOGIC_API_URL, TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_CHAT_ID
from scrapers import jra, nar, archive
from scrapers.odds import fetch_realtime_odds
from scrapers.horse_weight import fetch_horse_weights
from scrapers.training_comment import fetch_training_comments
from scrapers.horse import search_horse
from scrapers.stable_comment import fetch_comments_for_race
from db.engine_stats import get_engine_stats as _query_engine_stats
from scrapers.nar import NAR_VENUES
from db.prediction_manager import record_prediction, check_prediction
from scrapers.validators import validate_race_entries, validate_parallel_arrays

logger = logging.getLogger(__name__)

# Prefetch JSON directory
PREFETCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'prefetch')

# Race data cache: stores entry data, predictions, analysis results, and realtime data per race_id
# Structure: _race_cache[race_id] = {
#   "entries": { horses, horse_numbers, jockeys, posts, venue, ... },
#   "predictions": { "Dlogic": [...], ... },           # permanent
#   "analysis": { "/api/v2/analysis/race-flow": {...}, ... },  # permanent
#   "realtime": { "odds": {...}, "track_condition": "...", "fetched_at": float },  # TTL
# }
_race_cache: dict[str, dict] = {}

# TTL for realtime data (odds, track_condition)
_REALTIME_TTL = 300  # 5 minutes


# Display engine brand names
ENGINE_LABEL_MAP = {
    "dlogic": "Dlogic",
    "ilogic": "Ilogic",
    "viewlogic": "ViewLogic",
    "metalogic": "MetaLogic",
}


# Cache for custom → netkeiba race_id resolution
_netkeiba_id_cache: dict[str, str] = {}


def _resolve_netkeiba_race_id(race_id: str, race_type: str = "jra") -> str:
    """Resolve custom race_id (YYYYMMDD-venue-num) to netkeiba race_id.

    If already a netkeiba ID (all digits, 10-12 chars), return as-is.
    If custom format, scrape race list to find the matching netkeiba ID.
    """
    # Already a netkeiba ID
    if race_id.isdigit() and len(race_id) >= 10:
        return race_id

    # Not custom format
    m = re.match(r'^(\d{8})-(.+?)-(\d+)$', race_id)
    if not m:
        return race_id  # Unknown format, return as-is

    # Check cache
    if race_id in _netkeiba_id_cache:
        return _netkeiba_id_cache[race_id]

    date_str = m.group(1)  # YYYYMMDD
    venue = m.group(2)
    race_number = int(m.group(3))

    is_nar = any(v in venue for v in NAR_VENUES)

    try:
        if is_nar:
            races = nar.fetch_race_list(date_str, venue_filter=venue)
        else:
            races = jra.fetch_race_list(date_str)

        for r in races:
            if r.venue == venue and r.race_number == race_number:
                _netkeiba_id_cache[race_id] = r.race_id
                logger.info(f"Resolved race_id: {race_id} → {r.race_id}")
                return r.race_id

        # Try looser match (venue contains)
        for r in races:
            if venue in r.venue and r.race_number == race_number:
                _netkeiba_id_cache[race_id] = r.race_id
                logger.info(f"Resolved race_id (loose): {race_id} → {r.race_id}")
                return r.race_id
    except Exception:
        logger.exception(f"Failed to resolve race_id: {race_id}")

    logger.warning(f"Could not resolve race_id: {race_id}")
    return race_id  # Return original if resolution fails


def _rename_prediction_keys(predictions: dict) -> dict:
    """Rename engine keys to generic labels."""
    renamed = {}
    for key, value in predictions.items():
        label = ENGINE_LABEL_MAP.get(key, key)
        renamed[label] = value
    return renamed


def execute_tool(tool_name: str, tool_input: dict, context: dict | None = None) -> str:
    """Execute a tool and return the result as a JSON string.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Tool parameters from Claude.
        context: Optional context dict with user info (e.g. {"user_profile_id": "..."}).
    """
    logger.info(f"Tool call: {tool_name} with keys={list(tool_input.keys())}")
    try:
        if tool_name == "get_today_races":
            return _get_today_races(tool_input)
        elif tool_name == "get_race_entries":
            return _get_race_entries(tool_input)
        elif tool_name == "get_predictions":
            return _get_predictions(tool_input)
        elif tool_name == "get_realtime_odds":
            return _get_realtime_odds(tool_input)
        elif tool_name == "get_horse_weights":
            return _get_horse_weights(tool_input)
        elif tool_name == "get_training_comments":
            return _get_training_comments(tool_input)
        elif tool_name == "search_horse":
            return _search_horse(tool_input)
        elif tool_name == "get_race_flow":
            return _call_analysis_api("/api/v2/analysis/race-flow", tool_input)
        elif tool_name == "get_jockey_analysis":
            return _call_analysis_api("/api/v2/analysis/jockey-analysis", tool_input)
        elif tool_name == "get_bloodline_analysis":
            return _call_analysis_api("/api/v2/analysis/bloodline-analysis", tool_input)
        elif tool_name == "get_recent_runs":
            return _call_analysis_api("/api/v2/analysis/recent-runs", tool_input)
        elif tool_name == "record_user_prediction":
            return _record_user_prediction(tool_input, context)
        elif tool_name == "check_user_prediction":
            return _check_user_prediction(tool_input, context)
        elif tool_name == "get_my_stats":
            return _get_my_stats(tool_input, context)
        elif tool_name == "get_prediction_ranking":
            return _get_prediction_ranking(tool_input)
        elif tool_name == "get_odds_probability":
            return _get_odds_probability(tool_input)
        elif tool_name == "get_stable_comments":
            return _get_stable_comments(tool_input)
        elif tool_name == "get_engine_stats":
            return _get_engine_stats(tool_input)
        elif tool_name == "send_inquiry":
            return _send_inquiry(tool_input, context)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception(f"Tool execution error: {tool_name}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _load_prefetch(date_str: str) -> dict | None:
    """Load prefetched race data JSON for a given date."""
    path = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _find_prefetch_race(date_str: str, race_id: str) -> dict | None:
    """Find a specific race from prefetch data by race_id."""
    data = _load_prefetch(date_str)
    if not data:
        return None
    for race in data.get('races', []):
        if race.get('race_id') == race_id:
            return race
    return None


def _get_today_races(params: dict) -> str:
    date_str = params.get("date", datetime.now().strftime("%Y%m%d"))
    race_type = params.get("race_type", "jra")
    venue_filter = params.get("venue", "")
    is_local = race_type == "nar"

    # Step 0: Try prefetched JSON (fastest path)
    prefetch = _load_prefetch(date_str)
    if prefetch:
        races = prefetch.get('races', [])
        # Filter by type
        if race_type == "nar":
            races = [r for r in races if r.get('is_local', True)]
        elif race_type == "jra":
            races = [r for r in races if not r.get('is_local', False)]
        # Filter by venue
        if venue_filter:
            races = [r for r in races if venue_filter in r.get('venue', '')]

        if races:
            result = []
            for r in races:
                race_entry = {
                    "race_id": r.get('race_id', ''),
                    "race_number": r.get('race_number', 0),
                    "race_name": r.get('race_name', ''),
                    "venue": r.get('venue', ''),
                    "distance": r.get('distance', ''),
                    "headcount": len(r.get('horses', [])),
                    "track_condition": r.get('track_condition', '−'),
                    "has_predictions": bool(r.get('predictions')),
                }
                if r.get('start_time'):
                    race_entry["start_time"] = r['start_time']
                result.append(race_entry)
            return json.dumps({
                "races": result,
                "count": len(result),
                "source": "prefetch",
            }, ensure_ascii=False)

    # Step 1: Try TS archive files
    archive_races = archive.find_archive_races(date_str, venue_filter, is_local=is_local)

    if archive_races:
        result = []
        for r in archive_races:
            result.append({
                "race_id": r.race_id,
                "race_number": r.race_number,
                "race_name": r.race_name,
                "venue": r.venue,
                "distance": r.distance,
                "headcount": len(r.horses),
                "track_condition": r.track_condition,
                "has_predictions": bool(r.predictions),
            })
        return json.dumps({
            "races": result,
            "count": len(result),
            "source": "archive",
        }, ensure_ascii=False)

    # Step 2: Fallback to scraping
    if race_type == "jra":
        scrape_races = jra.fetch_race_list(date_str)
    else:
        scrape_races = nar.fetch_race_list(date_str, venue_filter=venue_filter)

    if venue_filter and race_type == "jra":
        scrape_races = [r for r in scrape_races if venue_filter in r.venue]

    if not scrape_races:
        return json.dumps({
            "races": [],
            "count": 0,
        }, ensure_ascii=False)

    result = []
    for r in scrape_races:
        result.append({
            "race_id": r.race_id,
            "race_number": r.race_number,
            "race_name": r.race_name,
            "venue": r.venue,
            "distance": r.distance,
            "headcount": r.headcount,
            "start_time": r.start_time,
            "has_predictions": False,
        })

    return json.dumps({
        "races": result,
        "count": len(result),
    }, ensure_ascii=False)


def _get_race_entries(params: dict) -> str:
    race_id = params["race_id"]
    race_type = params.get("race_type", "jra")

    # Step 0: Try prefetched JSON
    date_part = race_id.split("-")[0] if "-" in race_id else ""
    if date_part:
        pf = _find_prefetch_race(date_part, race_id)
        if pf and pf.get('horses'):
            # Validate parallel arrays integrity
            pf_valid, pf_warnings = validate_parallel_arrays(pf, race_id)
            for w in pf_warnings:
                logger.warning(f"Prefetch validation: {w}")
            if not pf_valid:
                logger.error(f"Prefetch data invalid for {race_id}, falling through to scraping")
            else:
                entries = []
                for i in range(len(pf['horses'])):
                    entry = {
                        "horse_number": pf['horse_numbers'][i] if i < len(pf.get('horse_numbers', [])) else i + 1,
                        "horse_name": pf['horses'][i],
                        "jockey": pf['jockeys'][i] if i < len(pf.get('jockeys', [])) else "",
                        "trainer": pf['trainers'][i] if i < len(pf.get('trainers', [])) else "",
                        "post": pf['posts'][i] if i < len(pf.get('posts', [])) else 0,
                        "sex_age": pf['sex_ages'][i] if i < len(pf.get('sex_ages', [])) else "",
                        "weight": pf['weights'][i] if i < len(pf.get('weights', [])) else 0,
                    }
                    if pf.get('odds') and i < len(pf['odds']):
                        entry["odds"] = pf['odds'][i]
                    if pf.get('popularities') and i < len(pf['popularities']):
                        entry["popularity"] = pf['popularities'][i]
                    entries.append(entry)

                # Validate constructed entries
                entries_valid, entries_warnings = validate_race_entries(entries, race_id)
                for w in entries_warnings:
                    logger.warning(f"Prefetch entries: {w}")
                if not entries_valid:
                    logger.error(f"Prefetch entries invalid for {race_id}, falling through to scraping")
                else:
                    result = {
                        "race_id": race_id,
                        "race_name": pf.get('race_name', ''),
                        "venue": pf.get('venue', ''),
                        "distance": pf.get('distance', ''),
                        "race_number": pf.get('race_number', 0),
                        "track_condition": pf.get('track_condition', '−'),
                        "headcount": len(pf['horses']),
                        "entries": entries,
                        "source": "prefetch",
                    }
                    if pf.get('predictions'):
                        result["predictions"] = _rename_prediction_keys(pf['predictions'])
                    # Cache race data for analysis tools
                    _cache_race_data(race_id, entries, result)
                    return json.dumps(result, ensure_ascii=False)

    # Step 1: Try TS archive
    arch = archive.find_archive_race_by_id(race_id)
    if arch and arch.horses:
        # Validate archive data arrays
        arch_data = {
            "horses": arch.horses,
            "horse_numbers": arch.horse_numbers,
            "jockeys": arch.jockeys,
            "posts": arch.posts,
            "trainers": arch.trainers,
        }
        arch_valid, arch_warnings = validate_parallel_arrays(arch_data, race_id)
        for w in arch_warnings:
            logger.warning(f"Archive validation: {w}")

        if arch_valid:
            entries = []
            for i in range(len(arch.horses)):
                entry = {
                    "horse_number": arch.horse_numbers[i] if i < len(arch.horse_numbers) else i + 1,
                    "horse_name": arch.horses[i],
                    "jockey": arch.jockeys[i] if i < len(arch.jockeys) else "",
                    "trainer": arch.trainers[i] if i < len(arch.trainers) else "",
                    "post": arch.posts[i] if i < len(arch.posts) else 0,
                    "sex_age": arch.sex_ages[i] if i < len(arch.sex_ages) else "",
                    "weight": arch.weights[i] if i < len(arch.weights) else 0,
                }
                if arch.odds and i < len(arch.odds):
                    entry["odds"] = arch.odds[i]
                if arch.popularities and i < len(arch.popularities):
                    entry["popularity"] = arch.popularities[i]
                entries.append(entry)

            # Validate constructed entries
            entries_valid, entries_warnings = validate_race_entries(entries, race_id)
            for w in entries_warnings:
                logger.warning(f"Archive entries: {w}")

            if entries_valid:
                result = {
                    "race_id": arch.race_id,
                    "race_name": arch.race_name,
                    "venue": arch.venue,
                    "distance": arch.distance,
                    "race_number": arch.race_number,
                    "track_condition": arch.track_condition,
                    "headcount": len(arch.horses),
                    "entries": entries,
                }

                if arch.predictions:
                    horse_map = {}
                    for i, num in enumerate(arch.horse_numbers):
                        if i < len(arch.horses):
                            horse_map[num] = arch.horses[i]

                    predictions = {}
                    for engine, nums in arch.predictions.items():
                        predictions[engine] = [
                            {"rank": ri + 1, "horse_number": n, "horse_name": horse_map.get(n, f"#{n}")}
                            for ri, n in enumerate(nums[:5])
                        ]
                    result["predictions"] = _rename_prediction_keys(predictions)

                _cache_race_data(arch.race_id, entries, result)
                return json.dumps(result, ensure_ascii=False)
            else:
                logger.error(f"Archive entries invalid for {race_id}, falling through to scraping")

    # Step 2: Fallback to scraping
    if race_type == "jra":
        detail = jra.fetch_race_entries(race_id)
    else:
        detail = nar.fetch_race_entries(race_id)

    if not detail:
        return json.dumps({"error": f"レース情報の取得に失敗しました: {race_id}"}, ensure_ascii=False)

    # Scraper already validates internally (returns None on invalid data)
    entries = []
    for e in detail.entries:
        entries.append({
            "horse_number": e.horse_number,
            "horse_name": e.horse_name,
            "jockey": e.jockey,
            "trainer": e.trainer,
            "post": e.post,
            "sex_age": e.sex_age,
            "weight": e.weight,
        })

    # Final validation before serving to user
    entries_valid, entries_warnings = validate_race_entries(entries, race_id)
    for w in entries_warnings:
        logger.warning(f"Scrape entries: {w}")
    if not entries_valid:
        logger.error(f"Scraped data invalid for {race_id}")
        return json.dumps({"error": f"レースデータの整合性チェックに失敗しました: {race_id}"}, ensure_ascii=False)

    result = {
        "race_id": race_id,
        "race_name": detail.summary.race_name,
        "venue": detail.summary.venue,
        "distance": detail.summary.distance,
        "race_number": detail.summary.race_number,
        "track_condition": detail.track_condition,
        "headcount": detail.summary.headcount,
        "entries": entries,
    }
    _cache_race_data(race_id, entries, result)
    return json.dumps(result, ensure_ascii=False)


def _get_predictions(params: dict) -> str:
    race_id = params.get("race_id", "")

    # Check prediction cache first
    if race_id and race_id in _race_cache and "predictions" in _race_cache[race_id]:
        logger.info(f"Prediction cache hit for {race_id}")
        return json.dumps({
            "race_id": race_id,
            "predictions": _race_cache[race_id]["predictions"],
        }, ensure_ascii=False)

    # Step 1: Check if archive already has predictions
    arch = archive.find_archive_race_by_id(race_id)
    if arch and arch.predictions:
        horse_map = {}
        for i, num in enumerate(arch.horse_numbers):
            if i < len(arch.horses):
                horse_map[num] = arch.horses[i]

        predictions = {}
        for engine, nums in arch.predictions.items():
            predictions[engine] = [
                {"rank": ri + 1, "horse_number": n, "horse_name": horse_map.get(n, f"#{n}")}
                for ri, n in enumerate(nums[:5])
            ]

        renamed = _rename_prediction_keys(predictions)

        # Cache predictions
        if race_id in _race_cache:
            _race_cache[race_id]["predictions"] = renamed

        return json.dumps({
            "race_id": race_id,
            "predictions": renamed,
        }, ensure_ascii=False)

    # Step 2: Auto-fill missing parameters from race cache (like analysis tools)
    if race_id and race_id in _race_cache and "entries" in _race_cache[race_id]:
        cached = _race_cache[race_id]["entries"]
        for key in ["horses", "horse_numbers", "jockeys", "posts", "venue",
                     "race_number", "distance", "track_condition"]:
            if key not in params or not params[key]:
                params[key] = cached.get(key)
        logger.info(f"Auto-filled prediction params from cache for {race_id}")
    elif race_id and not params.get("horses"):
        # No cache — try archive lookup
        logger.info(f"No cache for predictions {race_id}, trying archive lookup")
        arch2 = archive.find_archive_race_by_id(race_id)
        if arch2:
            params.setdefault("horses", arch2.horses)
            params.setdefault("horse_numbers", arch2.horse_numbers)
            params.setdefault("jockeys", arch2.jockeys)
            params.setdefault("posts", arch2.posts)
            params.setdefault("venue", arch2.venue)
            params.setdefault("race_number", arch2.race_number)
            params.setdefault("distance", arch2.distance)
            params.setdefault("track_condition", arch2.track_condition)

    if not params.get("horses"):
        return json.dumps({"error": "出馬表データがありません。先にレースの出馬表を取得してください。"}, ensure_ascii=False)

    # Step 3: Call backend API
    payload = {
        "race_id": params.get("race_id", ""),
        "horses": params.get("horses", []),
        "horse_numbers": params.get("horse_numbers", []),
        "venue": params.get("venue", ""),
        "race_number": params.get("race_number", 0),
        "jockeys": params.get("jockeys", []),
        "posts": params.get("posts", []),
        "distance": params.get("distance", ""),
        "track_condition": params.get("track_condition", "良"),
    }

    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}/api/v2/predictions/newspaper",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        horse_map = {num: name for num, name in zip(params.get("horse_numbers", []), params.get("horses", []))}

        result = {}
        for engine in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
            if engine in data:
                top5_numbers = data[engine][:5]
                result[engine] = [
                    {"rank": i + 1, "horse_number": n, "horse_name": horse_map.get(n, f"#{n}")}
                    for i, n in enumerate(top5_numbers)
                ]

        renamed = _rename_prediction_keys(result)
        track_adjusted = data.get("track_adjusted", False)
        track_cond = params.get("track_condition", "良")

        # Cache predictions
        if race_id and race_id in _race_cache:
            _race_cache[race_id]["predictions"] = renamed

        resp_data = {
            "race_id": race_id,
            "predictions": renamed,
        }
        if track_adjusted:
            resp_data["track_adjusted"] = True
            resp_data["track_condition"] = track_cond

        return json.dumps(resp_data, ensure_ascii=False)

    except requests.RequestException as e:
        return json.dumps({"error": f"予想APIへの接続に失敗しました: {str(e)}"}, ensure_ascii=False)


def _get_realtime_odds(params: dict) -> str:
    race_id = params["race_id"]
    race_type = params.get("race_type", "jra")
    # Resolve custom race_id to netkeiba format for scraping
    scrape_id = _resolve_netkeiba_race_id(race_id, race_type)

    # Check realtime cache (with TTL)
    if race_id in _race_cache and "realtime" in _race_cache[race_id]:
        rt = _race_cache[race_id]["realtime"]
        if time.time() - rt["fetched_at"] < _REALTIME_TTL:
            logger.info(f"Realtime cache hit for {race_id} (age: {time.time() - rt['fetched_at']:.0f}s)")
            sorted_odds = dict(sorted(rt["odds"].items()))
            result = {
                "race_id": race_id,
                "odds": {str(k): v for k, v in sorted_odds.items()},
            }
            if rt.get("track_condition"):
                result["track_condition"] = rt["track_condition"]
            return json.dumps(result, ensure_ascii=False)

    odds_map = fetch_realtime_odds(scrape_id, race_type)

    # Also scrape track_condition from the same page
    track_condition = _scrape_track_condition(scrape_id, race_type)

    # Cache realtime data
    if race_id in _race_cache:
        _race_cache[race_id]["realtime"] = {
            "odds": odds_map or {},
            "track_condition": track_condition,
            "fetched_at": time.time(),
        }
        # Also update entries cache track_condition for analysis tools
        if track_condition and "entries" in _race_cache[race_id]:
            _race_cache[race_id]["entries"]["track_condition"] = track_condition

    if not odds_map:
        result = {"race_id": race_id, "odds": {}}
        if track_condition:
            result["track_condition"] = track_condition
        return json.dumps(result, ensure_ascii=False)

    sorted_odds = dict(sorted(odds_map.items()))
    result = {
        "race_id": race_id,
        "odds": {str(k): v for k, v in sorted_odds.items()},
    }
    if track_condition:
        result["track_condition"] = track_condition
    return json.dumps(result, ensure_ascii=False)


def _get_horse_weights(params: dict) -> str:
    race_id = params["race_id"]
    race_type = params.get("race_type", "jra")
    # Resolve custom race_id to netkeiba format for scraping
    scrape_id = _resolve_netkeiba_race_id(race_id, race_type)

    # Check realtime cache (horse_weights share the same TTL as odds)
    if race_id in _race_cache and "realtime" in _race_cache[race_id]:
        rt = _race_cache[race_id]["realtime"]
        if time.time() - rt["fetched_at"] < _REALTIME_TTL and rt.get("horse_weights"):
            logger.info(f"Horse weights cache hit for {race_id}")
            return json.dumps({
                "race_id": race_id,
                "horse_weights": {str(k): v for k, v in sorted(rt["horse_weights"].items())},
            }, ensure_ascii=False)

    weight_map = fetch_horse_weights(scrape_id, race_type)

    # Cache realtime data
    if race_id in _race_cache:
        _race_cache[race_id].setdefault("realtime", {"fetched_at": time.time()})
        _race_cache[race_id]["realtime"]["horse_weights"] = weight_map or {}
        _race_cache[race_id]["realtime"]["fetched_at"] = time.time()

    if not weight_map:
        return json.dumps({
            "race_id": race_id,
            "horse_weights": {},
            "note": "馬体重はまだ発表されてないぜ。だいたい発走30分前くらいに公開されるから、その頃また聞いてくれ！",
        }, ensure_ascii=False)

    return json.dumps({
        "race_id": race_id,
        "horse_weights": {str(k): v for k, v in sorted(weight_map.items())},
    }, ensure_ascii=False)


def _get_training_comments(params: dict) -> str:
    race_id = params["race_id"]
    # Resolve custom race_id to netkeiba format for scraping
    scrape_id = _resolve_netkeiba_race_id(race_id)

    # Check analysis cache (training comments are semi-static, cache permanently per race)
    if race_id in _race_cache:
        analysis = _race_cache[race_id].get("analysis", {})
        if "training_comments" in analysis:
            logger.info(f"Training comments cache hit for {race_id}")
            return json.dumps(analysis["training_comments"], ensure_ascii=False)

    comments = fetch_training_comments(scrape_id)

    if not comments:
        return json.dumps({
            "race_id": race_id,
            "training_comments": {},
            "note": "調教データが取得できませんでした（地方競馬は非対応、またはレースが見つかりません）",
        }, ensure_ascii=False)

    result = {
        "race_id": race_id,
        "training_comments": {str(k): v for k, v in sorted(comments.items())},
    }

    # Cache permanently (training comments don't change)
    if race_id in _race_cache:
        _race_cache[race_id].setdefault("analysis", {})["training_comments"] = result

    return json.dumps(result, ensure_ascii=False)


def _get_engine_stats(params: dict) -> str:
    """Get engine prediction accuracy stats."""
    days = params.get("days", 30)
    stats = _query_engine_stats(days)

    if not stats or not stats.get("engines"):
        return json.dumps({
            "engines": {},
            "note": "まだ的中率データがありません。レースが終わるごとに自動集計されます。",
        }, ensure_ascii=False)

    return json.dumps(stats, ensure_ascii=False)


def _get_stable_comments(params: dict) -> str:
    """Fetch stable/trainer comments from keibabook."""
    race_id = params["race_id"]

    # Check analysis cache
    if race_id in _race_cache:
        analysis = _race_cache[race_id].get("analysis", {})
        if "stable_comments" in analysis:
            logger.info(f"Stable comments cache hit for {race_id}")
            return json.dumps(analysis["stable_comments"], ensure_ascii=False)

    # Need venue, date, race_number to resolve keibabook race ID
    venue = ""
    race_number = 0
    date_str = ""
    is_chihou = True

    # Try race cache
    if race_id in _race_cache and "entries" in _race_cache[race_id]:
        cached = _race_cache[race_id]["entries"]
        venue = cached.get("venue", "")
        race_number = cached.get("race_number", 0)
        is_chihou = cached.get("race_type", "jra") == "nar"

    # Extract date from race_id (custom format: YYYYMMDD-venue-num)
    if "-" in race_id:
        date_str = race_id.split("-")[0]
    elif race_id.isdigit() and len(race_id) >= 8:
        # netkeiba format: first 4 digits = year, next 2 = month-ish
        # For NAR: 202603120311 → date is embedded differently
        # Try prefetch to get date
        pass

    # Try prefetch for missing info
    if not venue or not race_number or not date_str:
        if date_str:
            pf = _find_prefetch_race(date_str, race_id)
            if pf:
                venue = venue or pf.get("venue", "")
                race_number = race_number or pf.get("race_number", 0)
                is_chihou = pf.get("is_local", True)

    if not venue or not race_number or not date_str:
        return json.dumps({
            "race_id": race_id,
            "stable_comments": {},
            "note": "レース情報が不足しています。先に出馬表を取得してください。",
        }, ensure_ascii=False)

    comments = fetch_comments_for_race(date_str, venue, race_number, is_chihou)

    if not comments:
        return json.dumps({
            "race_id": race_id,
            "stable_comments": {},
            "note": "厩舎コメントが取得できませんでした（未公開、または対象外のレースです）",
        }, ensure_ascii=False)

    result = {
        "race_id": race_id,
        "stable_comments": {str(k): v for k, v in sorted(comments.items())},
    }

    # Cache permanently
    if race_id in _race_cache:
        _race_cache[race_id].setdefault("analysis", {})["stable_comments"] = result

    return json.dumps(result, ensure_ascii=False)


def _scrape_track_condition(race_id: str, race_type: str) -> str:
    """Scrape current track condition from netkeiba shutuba page."""
    from scrapers.base import fetch_with_retry
    from config import NETKEIBA_JRA_BASE, NETKEIBA_NAR_BASE

    if race_type == "nar":
        url = f"{NETKEIBA_NAR_BASE}/race/shutuba.html?race_id={race_id}"
    else:
        url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"

    soup = fetch_with_retry(url, encoding="euc-jp", timeout=10)
    if not soup:
        return ""

    # Try .Item04 in .RaceData01 (works for both JRA and NAR)
    race_data1 = soup.select_one(".RaceData01")
    if race_data1:
        item04 = race_data1.select_one(".Item04")
        if item04:
            cond_text = item04.get_text(strip=True)
            for cond in ["不良", "重", "稍重", "良"]:
                if cond in cond_text:
                    return cond

    return ""


def _search_horse(params: dict) -> str:
    horse_name = params["horse_name"]

    result = search_horse(horse_name)
    if not result:
        return json.dumps({
            "horse_name": horse_name,
            "results": [],
        }, ensure_ascii=False)

    return json.dumps(result, ensure_ascii=False)


def _cache_race_data(race_id: str, entries: list[dict], race_info: dict):
    """Cache race entry data for later use by analysis tools."""
    if race_id not in _race_cache:
        _race_cache[race_id] = {}

    # Detect race_type from venue name
    venue = race_info.get("venue", "")
    race_type = "nar" if any(v in venue for v in NAR_VENUES) else "jra"

    _race_cache[race_id]["entries"] = {
        "horses": [e["horse_name"] for e in entries],
        "horse_numbers": [e["horse_number"] for e in entries],
        "jockeys": [e.get("jockey", "") for e in entries],
        "posts": [e.get("post", 0) for e in entries],
        "venue": venue,
        "race_number": race_info.get("race_number", 0),
        "distance": race_info.get("distance", ""),
        "track_condition": race_info.get("track_condition", "良"),
        "race_type": race_type,
    }
    logger.info(f"Cached race data for {race_id}: {len(entries)} horses")


def _record_user_prediction(params: dict, context: dict | None) -> str:
    """Record user's honmei pick for a race."""
    if not context or not context.get("user_profile_id"):
        return json.dumps({"error": "ユーザー情報が取得できません"}, ensure_ascii=False)

    race_id = params.get("race_id", "")
    horse_number = params.get("horse_number", 0)
    horse_name = params.get("horse_name", "")

    if not race_id or not horse_number or not horse_name:
        return json.dumps({"error": "race_id, horse_number, horse_name は必須です"}, ensure_ascii=False)

    # Get race_date from race_id if possible (format: YYYYMMDDXX... or with date prefix)
    race_date = ""
    if len(race_id) >= 8 and race_id[:8].isdigit():
        y, m, d = race_id[:4], race_id[4:6], race_id[6:8]
        race_date = f"{y}-{m}-{d}"

    # Auto-detect race_type from venue
    venue = params.get("venue", "")
    race_type = params.get("race_type", "jra")
    if venue:
        from scrapers.nar import NAR_VENUES
        if any(v in venue for v in NAR_VENUES):
            race_type = "nar"

    record = record_prediction(
        user_profile_id=context["user_profile_id"],
        race_id=race_id,
        horse_number=horse_number,
        horse_name=horse_name,
        race_name=params.get("race_name", ""),
        venue=venue,
        race_date=race_date,
        race_type=race_type,
    )
    return json.dumps({
        "status": "ok",
        "message": f"{horse_number}番 {horse_name} を本命として登録しました",
        "race_id": race_id,
        "horse_number": horse_number,
        "horse_name": horse_name,
    }, ensure_ascii=False)


def _check_user_prediction(params: dict, context: dict | None) -> str:
    """Check if user already has a prediction for a race."""
    if not context or not context.get("user_profile_id"):
        return json.dumps({"has_prediction": False}, ensure_ascii=False)

    race_id = params.get("race_id", "")
    if not race_id:
        return json.dumps({"has_prediction": False}, ensure_ascii=False)

    existing = check_prediction(context["user_profile_id"], race_id)
    if existing:
        return json.dumps({
            "has_prediction": True,
            "horse_number": existing["horse_number"],
            "horse_name": existing["horse_name"],
        }, ensure_ascii=False)

    return json.dumps({"has_prediction": False}, ensure_ascii=False)


def _call_analysis_api(endpoint: str, params: dict) -> str:
    """展開系サブエンジンAPIを呼び出す汎用関数。キャッシュから不足パラメータを自動補完。"""
    race_id = params.get("race_id", "")

    # Check analysis cache first
    if race_id and race_id in _race_cache:
        analysis_cache = _race_cache[race_id].get("analysis", {})
        if endpoint in analysis_cache:
            logger.info(f"Analysis cache hit: {endpoint} for {race_id}")
            return json.dumps(analysis_cache[endpoint], ensure_ascii=False)

    # Auto-fill missing parameters from race cache
    if race_id and race_id in _race_cache and "entries" in _race_cache[race_id]:
        cached = _race_cache[race_id]["entries"]
        for key in ["horses", "horse_numbers", "jockeys", "posts", "venue",
                     "race_number", "distance", "track_condition"]:
            if key not in params or not params[key]:
                params[key] = cached.get(key)
        logger.info(f"Auto-filled analysis params from cache for {race_id}")
    elif race_id and not params.get("horses"):
        # No cache hit — try to look up from archive/prefetch
        logger.info(f"No cache for {race_id}, trying archive lookup")
        arch = archive.find_archive_race_by_id(race_id)
        if arch:
            params.setdefault("horses", arch.horses)
            params.setdefault("horse_numbers", arch.horse_numbers)
            params.setdefault("jockeys", arch.jockeys)
            params.setdefault("posts", arch.posts)
            params.setdefault("venue", arch.venue)
            params.setdefault("race_number", arch.race_number)
            params.setdefault("distance", arch.distance)
            params.setdefault("track_condition", arch.track_condition)

    if not params.get("horses"):
        return json.dumps({"error": "出馬表データがありません。先にレースの出馬表を取得してください。"}, ensure_ascii=False)

    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}{endpoint}",
            json=params,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        # Cache analysis result
        if race_id and race_id in _race_cache:
            _race_cache[race_id].setdefault("analysis", {})[endpoint] = data
            logger.info(f"Cached analysis result: {endpoint} for {race_id}")

        return json.dumps(data, ensure_ascii=False)
    except requests.RequestException as e:
        return json.dumps({"error": f"分析APIへの接続に失敗: {str(e)}"}, ensure_ascii=False)


def _get_my_stats(params: dict, context: dict | None) -> str:
    """Get user's prediction stats and recent results."""
    if not context or not context.get("user_profile_id"):
        return json.dumps({"error": "ユーザー情報が取得できません"}, ensure_ascii=False)

    from db.result_manager import get_user_stats, get_user_recent_results
    from db.prediction_manager import get_user_predictions

    uid = context["user_profile_id"]
    stats = get_user_stats(uid)
    recent = get_user_recent_results(uid, limit=10)

    # If no stats/recent results, check if user has any predictions at all
    if not stats and not recent:
        predictions = get_user_predictions(uid, limit=5)
        if predictions:
            # User has predictions but results haven't been fetched yet
            pending = []
            for p in predictions:
                pending.append({
                    "race_id": p.get("race_id", ""),
                    "horse_number": p.get("horse_number", 0),
                    "horse_name": p.get("horse_name", ""),
                    "venue": p.get("venue", ""),
                    "race_name": p.get("race_name", ""),
                    "status": "結果待ち",
                })
            return json.dumps({
                "has_data": True,
                "stats": None,
                "pending_predictions": pending,
                "message": f"本命を{len(predictions)}レース登録済み。レース終了後に結果が反映されます。",
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "has_data": False,
                "message": "まだ予想データがありません。レースの本命を登録すると成績が記録されます。",
            }, ensure_ascii=False)

    result = {"has_data": True}

    if stats:
        result["stats"] = {
            "total_picks": stats["total_picks"],
            "total_wins": stats["total_wins"],
            "win_rate": stats["win_rate"],
            "recovery_rate": stats["recovery_rate"],
            "current_streak": stats["current_streak"],
            "best_payout": stats["best_payout"],
        }

    if recent:
        result["recent"] = recent

    return json.dumps(result, ensure_ascii=False)


def _get_prediction_ranking(params: dict) -> str:
    """Get prediction ranking.

    NOTE: ランキング機能は将来有料化予定。現時点では常に「準備中」を返す。
    """
    return json.dumps({
        "ranking": [],
        "message": "まだランキングデータがありません。みんなの予想が集まると表示されます。",
    }, ensure_ascii=False)

    # --- 有料化後に有効化 ---
    from db.result_manager import get_ranking

    limit = params.get("limit", 10)
    ranking = get_ranking(limit=limit)

    if not ranking:
        return json.dumps({
            "ranking": [],
            "message": "まだランキングデータがありません。みんなの予想が集まると表示されます。",
        }, ensure_ascii=False)

    return json.dumps({
        "ranking": ranking,
        "total_ranked": len(ranking),
        "min_picks": 3,
    }, ensure_ascii=False)


def _calc_win_probability(odds: float) -> float:
    """Calculate predicted win probability from odds."""
    if odds <= 0:
        return 0.0
    return 100.0 / (odds + 1.0)


def _calc_place_probability(odds: float) -> float:
    """Calculate predicted place probability from odds (multi-band multiplier)."""
    if odds <= 0:
        return 0.0
    win_prob = _calc_win_probability(odds)

    if odds < 2.5:
        multiplier = 2.8 - odds * 0.1
    elif odds < 3.5:
        ratio = (odds - 2.5) / 1.0
        mult_a = 2.8 - odds * 0.1
        mult_b = 2.3 + math.log10(odds) * 0.2
        multiplier = mult_a * (1 - ratio) + mult_b * ratio
    elif odds < 9.0:
        multiplier = 2.3 + math.log10(odds) * 0.2
    elif odds < 11.0:
        ratio = (odds - 9.0) / 2.0
        mult_b = 2.3 + math.log10(odds) * 0.2
        mult_c = 1.8 + 1.0 / odds * 5.0
        multiplier = mult_b * (1 - ratio) + mult_c * ratio
    else:
        multiplier = 1.8 + 1.0 / odds * 5.0

    return min(win_prob * multiplier, 85.0)


def _get_odds_probability(params: dict) -> str:
    """Calculate win/place probabilities from odds for all horses in a race."""
    race_id = params.get("race_id", "")

    # Get odds from race cache or prefetch
    odds_list = []
    horses = []
    horse_numbers = []

    # Try race cache first
    if race_id in _race_cache and "entries" in _race_cache[race_id]:
        cached = _race_cache[race_id]["entries"]
        horses = cached.get("horses", [])
        horse_numbers = cached.get("horse_numbers", [])

    # Try realtime odds from cache
    if race_id in _race_cache and "realtime" in _race_cache[race_id]:
        rt = _race_cache[race_id]["realtime"]
        odds_map = rt.get("odds", {})
        if odds_map and horse_numbers:
            odds_list = [odds_map.get(n, odds_map.get(str(n), 0)) for n in horse_numbers]

    # If no realtime odds, try prefetch data
    if not odds_list:
        date_part = race_id.split("-")[0] if "-" in race_id else ""
        if date_part:
            pf = _find_prefetch_race(date_part, race_id)
            if pf:
                if not horses:
                    horses = pf.get("horses", [])
                if not horse_numbers:
                    horse_numbers = pf.get("horse_numbers", [])
                odds_list = pf.get("odds", [])

    # Try archive as last resort
    if not odds_list:
        arch = archive.find_archive_race_by_id(race_id)
        if arch and arch.odds:
            if not horses:
                horses = arch.horses
            if not horse_numbers:
                horse_numbers = arch.horse_numbers
            odds_list = arch.odds

    if not odds_list or not horses:
        return json.dumps({
            "error": "オッズデータがありません。出馬表を先に取得するか、オッズが公開されてから試してください。"
        }, ensure_ascii=False)

    # Check analysis cache (calculated result is deterministic for same odds)
    if race_id in _race_cache:
        analysis_cache = _race_cache[race_id].get("analysis", {})
        if "odds-probability" in analysis_cache:
            logger.info(f"Odds probability cache hit for {race_id}")
            return json.dumps(analysis_cache["odds-probability"], ensure_ascii=False)

    # Calculate raw probabilities
    results = []
    raw_win_probs = []
    raw_place_probs = []

    for i in range(len(horses)):
        odds = odds_list[i] if i < len(odds_list) else 0
        if isinstance(odds, str):
            try:
                odds = float(odds)
            except ValueError:
                odds = 0
        win_p = _calc_win_probability(odds)
        place_p = _calc_place_probability(odds)
        raw_win_probs.append(win_p)
        raw_place_probs.append(place_p)

    # Normalize place probabilities
    num_horses = len(horses)
    target_sum = 200.0 if num_horses <= 7 else 300.0
    place_sum = sum(raw_place_probs)

    if place_sum > 0:
        norm_place_probs = [p * target_sum / place_sum for p in raw_place_probs]
        norm_place_probs = [min(p, 85.0) for p in norm_place_probs]
    else:
        norm_place_probs = raw_place_probs

    for i in range(len(horses)):
        odds = odds_list[i] if i < len(odds_list) else 0
        if isinstance(odds, str):
            try:
                odds = float(odds)
            except ValueError:
                odds = 0
        results.append({
            "horse_number": horse_numbers[i] if i < len(horse_numbers) else i + 1,
            "horse_name": horses[i],
            "odds": odds,
            "win_prob": round(raw_win_probs[i], 1),
            "place_prob": round(norm_place_probs[i], 1),
        })

    result_data = {
        "race_id": race_id,
        "probabilities": results,
        "note": "オッズベースの統計的予測勝率。実際の的中率とは異なります。",
    }

    # Cache in analysis cache
    if race_id in _race_cache:
        _race_cache[race_id].setdefault("analysis", {})["odds-probability"] = result_data
        logger.info(f"Cached odds probability for {race_id}")

    return json.dumps(result_data, ensure_ascii=False)


def _send_inquiry(params: dict, context: dict | None = None) -> str:
    """Send user inquiry to admin via Telegram and save to Supabase."""
    from datetime import timezone, timedelta
    from db.supabase_client import get_client
    jst = timezone(timedelta(hours=9))

    category = params.get("category", "other")
    summary = params.get("summary", "")
    detail = params.get("detail", "")

    category_labels = {
        "bug": "🐛 不具合報告",
        "request": "💡 要望",
        "question": "❓ 質問",
        "other": "📩 その他",
    }
    label = category_labels.get(category, "📩 問い合わせ")

    # Get user info from context
    user_name = "不明"
    user_profile_id = None
    line_user_id = ""
    if context and context.get("user_profile_id"):
        user_profile_id = context["user_profile_id"]
        try:
            sb = get_client()
            r = sb.table("user_profiles").select("display_name, line_user_id").eq(
                "id", user_profile_id
            ).limit(1).execute()
            if r.data:
                user_name = r.data[0].get("display_name", "不明")
                line_user_id = r.data[0].get("line_user_id", "")
        except Exception:
            pass

    content = summary
    if detail:
        content += f"\n{detail}"

    # Save to Supabase
    inquiry_id = None
    try:
        sb = get_client()
        row = {
            "user_profile_id": user_profile_id,
            "line_user_id": line_user_id,
            "display_name": user_name,
            "content": content,
            "status": "open",
        }
        res = sb.table("inquiries").insert(row).execute()
        if res.data:
            inquiry_id = res.data[0]["id"]
    except Exception:
        logger.exception("Failed to save inquiry to Supabase")

    now = datetime.now(jst).strftime("%Y-%m-%d %H:%M")
    text = (
        f"{label}\n"
        f"━━━━━━━━━━━━\n"
    )
    if inquiry_id:
        text += f"ID: #{inquiry_id}\n"
    text += (
        f"ユーザー: {user_name}\n"
        f"内容: {content}\n"
        f"時刻: {now} JST\n\n"
        f"/resolve {inquiry_id} で対応完了通知"
    )

    # Send via Telegram Bot API
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": ADMIN_TELEGRAM_CHAT_ID,
            "text": text,
        }, timeout=10)
        if resp.status_code == 200:
            logger.info(f"Inquiry #{inquiry_id} sent to admin: {category} - {summary}")
            return json.dumps({"status": "sent", "message": "問い合わせを運営に送信しました。"}, ensure_ascii=False)
        else:
            logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
            return json.dumps({"status": "error", "message": "送信に失敗しました。時間をおいて再度お試しください。"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Failed to send inquiry via Telegram")
        return json.dumps({"status": "error", "message": "送信に失敗しました。"}, ensure_ascii=False)
