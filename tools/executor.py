"""Tool execution logic - bridges Claude tool calls to actual data fetching."""

import json
import logging
import os
from datetime import datetime

import requests

from config import DLOGIC_API_URL
from scrapers import jra, nar, archive
from scrapers.odds import fetch_realtime_odds
from scrapers.horse import search_horse

logger = logging.getLogger(__name__)

# Prefetch JSON directory
PREFETCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'prefetch')

# Race data cache: stores the latest race entry data per race_id
# so analysis tools can auto-fill parameters without Claude needing to pass them
_race_cache: dict[str, dict] = {}


# Display engine brand names
ENGINE_LABEL_MAP = {
    "dlogic": "Dlogic",
    "ilogic": "Ilogic",
    "viewlogic": "ViewLogic",
    "metalogic": "MetaLogic",
}


def _rename_prediction_keys(predictions: dict) -> dict:
    """Rename engine keys to generic labels."""
    renamed = {}
    for key, value in predictions.items():
        label = ENGINE_LABEL_MAP.get(key, key)
        renamed[label] = value
    return renamed


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a JSON string."""
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
                result.append({
                    "race_id": r.get('race_id', ''),
                    "race_number": r.get('race_number', 0),
                    "race_name": r.get('race_name', ''),
                    "venue": r.get('venue', ''),
                    "distance": r.get('distance', ''),
                    "headcount": len(r.get('horses', [])),
                    "track_condition": r.get('track_condition', '−'),
                    "has_predictions": bool(r.get('predictions')),
                })
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
    if arch:
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

        # Include predictions if available
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

        # Cache race data for analysis tools
        _cache_race_data(arch.race_id, entries, result)
        return json.dumps(result, ensure_ascii=False)

    # Step 2: Fallback to scraping
    if race_type == "jra":
        detail = jra.fetch_race_entries(race_id)
    else:
        detail = nar.fetch_race_entries(race_id)

    if not detail:
        return json.dumps({"error": f"レース情報の取得に失敗しました: {race_id}"}, ensure_ascii=False)

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
    # Cache race data for analysis tools
    _cache_race_data(race_id, entries, result)
    return json.dumps(result, ensure_ascii=False)


def _get_predictions(params: dict) -> str:
    race_id = params.get("race_id", "")

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

        return json.dumps({
            "race_id": race_id,
            "predictions": _rename_prediction_keys(predictions),
        }, ensure_ascii=False)

    # Step 2: Call Render backend API
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

        return json.dumps({
            "race_id": params.get("race_id", ""),
            "predictions": _rename_prediction_keys(result),
        }, ensure_ascii=False)

    except requests.RequestException as e:
        return json.dumps({"error": f"予想APIへの接続に失敗しました: {str(e)}"}, ensure_ascii=False)


def _get_realtime_odds(params: dict) -> str:
    race_id = params["race_id"]
    race_type = params.get("race_type", "jra")

    odds_map = fetch_realtime_odds(race_id, race_type)
    if not odds_map:
        return json.dumps({
            "race_id": race_id,
            "odds": {},
        }, ensure_ascii=False)

    # Sort by horse number
    sorted_odds = dict(sorted(odds_map.items()))

    return json.dumps({
        "race_id": race_id,
        "odds": {str(k): v for k, v in sorted_odds.items()},
    }, ensure_ascii=False)


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
    _race_cache[race_id] = {
        "horses": [e["horse_name"] for e in entries],
        "horse_numbers": [e["horse_number"] for e in entries],
        "jockeys": [e.get("jockey", "") for e in entries],
        "posts": [e.get("post", 0) for e in entries],
        "venue": race_info.get("venue", ""),
        "race_number": race_info.get("race_number", 0),
        "distance": race_info.get("distance", ""),
        "track_condition": race_info.get("track_condition", "良"),
    }
    logger.info(f"Cached race data for {race_id}: {len(entries)} horses")


def _call_analysis_api(endpoint: str, params: dict) -> str:
    """展開系サブエンジンAPIを呼び出す汎用関数。キャッシュから不足パラメータを自動補完。"""
    race_id = params.get("race_id", "")

    # Auto-fill missing parameters from race cache
    if race_id and race_id in _race_cache:
        cached = _race_cache[race_id]
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
        return json.dumps(resp.json(), ensure_ascii=False)
    except requests.RequestException as e:
        return json.dumps({"error": f"分析APIへの接続に失敗: {str(e)}"}, ensure_ascii=False)
