"""Engine hit-rate statistics — save and query prediction accuracy per engine."""

import logging
from datetime import datetime, timezone, timedelta

from db.supabase_client import get_client

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def save_hit_rate(
    date: str,
    race_id: str,
    venue: str,
    race_number: int,
    race_type: str,
    engine: str,
    top1_horse: int,
    top3_horses: list[int],
    result_1st: int,
    result_2nd: int,
    result_3rd: int,
    hit_win: bool,
    hit_place: bool,
    place_hit_count: int,
):
    """Save a single engine's prediction result for one race."""
    sb = get_client()
    if not sb:
        return

    row = {
        "date": date,
        "race_id": race_id,
        "venue": venue,
        "race_number": race_number,
        "race_type": race_type,
        "engine": engine,
        "top1_horse": top1_horse,
        "top3_horses": top3_horses,
        "result_1st": result_1st,
        "result_2nd": result_2nd,
        "result_3rd": result_3rd,
        "hit_win": hit_win,
        "hit_place": hit_place,
        "place_hit_count": place_hit_count,
    }

    try:
        sb.table("engine_hit_rates").upsert(
            row, on_conflict="race_id,engine"
        ).execute()
    except Exception:
        logger.exception(f"Failed to save hit rate: {race_id} {engine}")


def get_engine_stats(days: int = 30) -> dict:
    """Get aggregated engine stats for the last N days.

    Returns:
        {
            "period_days": 30,
            "total_races": 150,
            "engines": {
                "dlogic": {
                    "win_hits": 25, "place_hits": 80, "total": 150,
                    "win_rate": 16.7, "place_rate": 53.3,
                },
                ...
            },
            "best_win_engine": "metalogic",
            "best_place_engine": "dlogic",
        }
    """
    sb = get_client()
    if not sb:
        return {}

    cutoff = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        resp = sb.table("engine_hit_rates").select("*").gte("date", cutoff).execute()
        rows = resp.data or []
    except Exception:
        logger.exception("Failed to query engine stats")
        return {}

    if not rows:
        return {"period_days": days, "total_races": 0, "engines": {}}

    # Aggregate per engine
    engine_data: dict[str, dict] = {}
    race_ids = set()

    for r in rows:
        eng = r["engine"]
        race_ids.add(r["race_id"])
        if eng not in engine_data:
            engine_data[eng] = {"win_hits": 0, "place_hits": 0, "total": 0}
        engine_data[eng]["total"] += 1
        if r["hit_win"]:
            engine_data[eng]["win_hits"] += 1
        if r["hit_place"]:
            engine_data[eng]["place_hits"] += 1

    # Calculate rates
    engines = {}
    best_win = ("", 0.0)
    best_place = ("", 0.0)

    for eng, d in engine_data.items():
        total = d["total"]
        win_rate = round(d["win_hits"] / total * 100, 1) if total else 0
        place_rate = round(d["place_hits"] / total * 100, 1) if total else 0
        engines[eng] = {
            "win_hits": d["win_hits"],
            "place_hits": d["place_hits"],
            "total": total,
            "win_rate": win_rate,
            "place_rate": place_rate,
        }
        if win_rate > best_win[1]:
            best_win = (eng, win_rate)
        if place_rate > best_place[1]:
            best_place = (eng, place_rate)

    return {
        "period_days": days,
        "total_races": len(race_ids),
        "engines": engines,
        "best_win_engine": best_win[0],
        "best_place_engine": best_place[0],
    }
