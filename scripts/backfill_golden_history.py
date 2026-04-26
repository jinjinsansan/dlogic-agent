#!/usr/bin/env python3
"""Backfill golden_history snapshots from Supabase data alone.

Uses engine_hit_rates + race_results + odds_snapshots to reconstruct
snapshot JSONs for dates older than the prefetch retention window.

Display compromises (vs live API):
- distance, track_condition, start_time: empty (not in DB)
- horse_name in engine_picks: best-effort from result_json.top3, else "#N"
- only races where all 4 engines logged predictions are included

Usage:
    python scripts/backfill_golden_history.py [START_YYYYMMDD] [END_YYYYMMDD]
        defaults: 20260311 → yesterday JST
"""
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")
from db.supabase_client import get_client

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(PROJECT_DIR, 'data', 'golden_history')
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

JST = timezone(timedelta(hours=9))
BEST_VENUES = {"園田", "水沢", "高知", "笠松", "金沢"}
BEST_WEEKDAYS = {1, 2, 3}  # Tue, Wed, Thu

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def fetch_all(sb, table, select, gte=None, lte=None, eq=None, chunk=1000):
    rows = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items():
                q = q.gte(k, v)
        if lte:
            for k, v in lte.items():
                q = q.lte(k, v)
        if eq:
            for k, v in eq.items():
                q = q.eq(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < chunk:
            break
        offset += chunk
    return rows


def date_iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def date_yyyymmdd(iso: str) -> str:
    return iso.replace("-", "")


def daterange(start_yyyymmdd: str, end_yyyymmdd: str):
    s = datetime.strptime(start_yyyymmdd, "%Y%m%d")
    e = datetime.strptime(end_yyyymmdd, "%Y%m%d")
    cur = s
    while cur <= e:
        yield cur.strftime("%Y%m%d")
        cur += timedelta(days=1)


def build_snapshot_for_date(yyyymmdd: str, hits, results_by_rid, latest_odds) -> dict | None:
    """Build a single-date snapshot from in-memory data."""
    iso = date_iso(yyyymmdd)
    date_hits = [h for h in hits if h["date"] == iso]
    if not date_hits:
        return None

    weekday_idx = datetime.strptime(yyyymmdd, "%Y%m%d").weekday()
    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][weekday_idx]

    by_race = defaultdict(dict)
    for h in date_hits:
        by_race[h["race_id"]][h["engine"]] = h

    races_out = []
    summary = {
        "total": 0,
        "loose_golden": 0, "strict_golden": 0,
        "loose_finished": 0, "strict_finished": 0,
        "loose_hits": 0, "strict_hits": 0,
        "loose_profit": 0, "strict_profit": 0,
    }

    for rid, eng_rows in by_race.items():
        if len(eng_rows) < 4:
            continue  # Skip incomplete (less than 4 engines logged)

        any_row = next(iter(eng_rows.values()))
        venue = any_row["venue"]
        race_num = any_row["race_number"]
        race_type = any_row["race_type"]
        is_nar = (race_type == "nar")

        result = results_by_rid.get(rid)
        race_name = result.get("race_name", "") if result else ""
        rj = result.get("result_json") if result else None
        if isinstance(rj, str):
            try: rj = json.loads(rj)
            except Exception: rj = None
        horse_name_map = {}
        total_horses = 0
        top3_entries = []
        if rj:
            top3_entries = rj.get("top3", []) or []
            for t in top3_entries:
                hn = t.get("horse_number")
                if hn is not None:
                    horse_name_map[hn] = t.get("horse_name", "")
            total_horses = rj.get("total_horses", 0) or 0

        # Engine picks
        engine_picks = {}
        for eng_name in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
            h = eng_rows.get(eng_name)
            if not h: continue
            top1 = h.get("top1_horse")
            engine_picks[eng_name] = {
                "horse_number": top1,
                "horse_name": horse_name_map.get(top1, f"#{top1}" if top1 else ""),
            }

        # Consensus
        picks = [p["horse_number"] for p in engine_picks.values() if p.get("horse_number")]
        cons_horse, cons_count, agreed = None, 0, []
        if picks:
            cnt = Counter(picks)
            cons_horse, cons_count = cnt.most_common(1)[0]
            agreed = [eng for eng, p in engine_picks.items() if p.get("horse_number") == cons_horse]

        # Popularity
        cons_pop = None
        odds_key = (iso, venue, race_num)
        odds_map = latest_odds.get(odds_key)
        if odds_map and cons_horse and cons_horse in odds_map:
            sorted_pairs = sorted(odds_map.items(), key=lambda x: x[1])
            for i, (hn, _) in enumerate(sorted_pairs, 1):
                if hn == cons_horse:
                    cons_pop = i
                    break

        # Filters
        is_loose = (
            cons_count in (2, 3)
            and cons_pop is not None
            and 5 <= cons_pop <= 8
        )
        is_strict = (
            is_loose
            and is_nar
            and venue in BEST_VENUES
            and 6 <= total_horses <= 12
            and weekday_idx in BEST_WEEKDAYS
        )

        # Result
        race_result = None
        if result and result.get("status") == "finished":
            winner_number = result.get("winner_number")
            win_payout = result.get("win_payout") or 0
            top3_numbers = [t.get("horse_number") for t in top3_entries if t.get("horse_number") is not None]
            did_win = bool(cons_horse and cons_horse == winner_number)
            did_place = bool(cons_horse and cons_horse in top3_numbers)
            profit = None
            if is_loose or is_strict:
                profit = (win_payout - 100) if did_win else -100
            race_result = {
                "status": "finished",
                "winner_number": winner_number,
                "win_payout": win_payout,
                "top3": top3_entries,
                "did_consensus_win": did_win,
                "did_consensus_place": did_place,
                "profit_yen": profit,
            }

        races_out.append({
            "race_id": rid,
            "venue": venue,
            "race_number": race_num,
            "race_name": race_name,
            "start_time": "",
            "is_local": is_nar,
            "distance": "",
            "track_condition": "−",
            "total_horses": total_horses,
            "engine_picks": engine_picks,
            "consensus": {
                "horse_number": cons_horse,
                "horse_name": horse_name_map.get(cons_horse, f"#{cons_horse}" if cons_horse else ""),
                "agreed_engines": agreed,
                "count": cons_count,
            },
            "popularity_rank": cons_pop,
            "is_golden_loose": is_loose,
            "is_golden_strict": is_strict,
            "result": race_result,
        })

        # Update summary
        summary["total"] += 1
        if is_loose: summary["loose_golden"] += 1
        if is_strict: summary["strict_golden"] += 1
        if race_result:
            if is_loose:
                summary["loose_finished"] += 1
                if race_result["did_consensus_win"]:
                    summary["loose_hits"] += 1
                if race_result["profit_yen"] is not None:
                    summary["loose_profit"] += race_result["profit_yen"]
            if is_strict:
                summary["strict_finished"] += 1
                if race_result["did_consensus_win"]:
                    summary["strict_hits"] += 1
                if race_result["profit_yen"] is not None:
                    summary["strict_profit"] += race_result["profit_yen"]

    races_out.sort(key=lambda r: (r["venue"], r["race_number"]))

    return {
        "date": yyyymmdd,
        "weekday": weekday_ja,
        "summary": summary,
        "races": races_out,
        "source": "backfilled",
    }


def main():
    end_default = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    start_str = sys.argv[1] if len(sys.argv) > 1 else "20260311"
    end_str = sys.argv[2] if len(sys.argv) > 2 else end_default

    logger.info(f"backfill range: {start_str} → {end_str}")

    sb = get_client()

    logger.info("loading engine_hit_rates...")
    hits = fetch_all(sb, "engine_hit_rates",
        select="date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses",
        gte={"date": date_iso(start_str)},
        lte={"date": date_iso(end_str)},
    )
    logger.info(f"  {len(hits)} rows")

    logger.info("loading race_results...")
    results = fetch_all(sb, "race_results",
        select="race_id,race_date,venue,race_name,winner_number,win_payout,result_json,status",
        gte={"race_date": date_iso(start_str)},
        lte={"race_date": date_iso(end_str)},
    )
    results_by_rid = {r["race_id"]: r for r in results}
    logger.info(f"  {len(results)} rows")

    logger.info("loading odds_snapshots...")
    odds_rows = fetch_all(sb, "odds_snapshots",
        select="race_date,venue,race_number,odds_data,snapshot_at",
        gte={"race_date": date_iso(start_str)},
        lte={"race_date": date_iso(end_str)},
    )
    latest_at, latest_odds = {}, {}
    for o in odds_rows:
        key = (o["race_date"], o["venue"], o["race_number"])
        ts = o["snapshot_at"]
        if key not in latest_at or ts > latest_at[key]:
            latest_at[key] = ts
            data = o["odds_data"]
            if isinstance(data, str):
                try: data = json.loads(data)
                except Exception: continue
            try:
                latest_odds[key] = {int(k): float(v) for k, v in (data or {}).items() if v}
            except Exception:
                pass
    logger.info(f"  unique races with odds: {len(latest_odds)}")

    written = 0
    skipped = 0
    for d in daterange(start_str, end_str):
        out_path = os.path.join(SNAPSHOT_DIR, f"{d}.json")
        if os.path.exists(out_path):
            logger.info(f"  {d}: skip (exists)")
            skipped += 1
            continue
        snap = build_snapshot_for_date(d, hits, results_by_rid, latest_odds)
        if not snap:
            logger.info(f"  {d}: no engine data")
            continue
        s = snap["summary"]
        logger.info(f"  {d} ({snap['weekday']}): total={s['total']} loose={s['loose_golden']} strict={s['strict_golden']} (hits={s['loose_hits']}/{s['loose_finished']}, +{s['loose_profit']}円)")
        tmp = out_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out_path)
        written += 1

    logger.info(f"done: written={written} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
