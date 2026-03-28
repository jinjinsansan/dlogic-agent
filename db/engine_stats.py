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


RANK_MARKS = {0: "◎", 1: "○", 2: "▲", 3: "△", 4: "×"}


def get_engine_stats(days: int = 30) -> dict:
    """Get aggregated engine stats for the last N days.

    Returns overall engine stats + rank-level (◎○▲△×) hit rates.
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

    engine_data: dict[str, dict] = {}
    race_ids = set()
    rank_stats: dict[str, dict[str, dict]] = {}

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

        # Rank-level analysis (◎○▲△×)
        top_horses = r.get("top3_horses", [])
        result_set = {r["result_1st"], r["result_2nd"], r["result_3rd"]}
        if eng not in rank_stats:
            rank_stats[eng] = {}
        for i, horse in enumerate(top_horses[:5]):
            mark = RANK_MARKS.get(i, "×")
            if mark not in rank_stats[eng]:
                rank_stats[eng][mark] = {"total": 0, "win": 0, "place": 0}
            rank_stats[eng][mark]["total"] += 1
            if horse == r["result_1st"]:
                rank_stats[eng][mark]["win"] += 1
            if horse in result_set:
                rank_stats[eng][mark]["place"] += 1

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

    # Format rank stats per engine
    rank_summary = {}
    for eng, marks in rank_stats.items():
        rank_summary[eng] = {}
        for mark in ["◎", "○", "▲", "△", "×"]:
            s = marks.get(mark)
            if not s or s["total"] == 0:
                continue
            rank_summary[eng][mark] = {
                "total": s["total"],
                "win_rate": round(s["win"] / s["total"] * 100, 1),
                "place_rate": round(s["place"] / s["total"] * 100, 1),
            }

    return {
        "period_days": days,
        "total_races": len(race_ids),
        "engines": engines,
        "rank_stats": rank_summary,
        "best_win_engine": best_win[0],
        "best_place_engine": best_place[0],
    }
