#!/usr/bin/env python3
"""Build a race-level JSONL dataset for the Anatou wide-bet rebuild.

This is the first canonical dataset builder. It uses existing Supabase rows
only, so it exposes current gaps instead of hiding them:

- engine_hit_rates may contain top3 or top5 in the top3_horses column.
- NLogic is absent from older stored rows.
- race_results does not have race_number, so it is inferred from race_id.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from supabase import create_client

from wide_rebirth_data_audit import (
    ENGINES,
    DOCS_DIR,
    PROJECT_DIR,
    clean_gap_bucket,
    fetch_all,
    infer_race_number,
    load_supabase_env,
    parse_json_maybe,
    pct,
    race_key,
)


DATA_DIR = PROJECT_DIR / "data"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_top_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in value:
        num = safe_int(item)
        if num is None or num in seen:
            continue
        seen.add(num)
        out.append(num)
    return out


def normalize_odds_map(value: Any) -> dict[int, float]:
    data = parse_json_maybe(value)
    out: dict[int, float] = {}
    for key, raw in data.items():
        num = safe_int(key)
        if num is None:
            continue
        try:
            odds = float(raw)
        except (TypeError, ValueError):
            continue
        if odds > 0:
            out[num] = odds
    return out


def popularity_from_odds(odds: dict[int, float]) -> dict[int, int]:
    ordered = sorted(odds.items(), key=lambda item: (item[1], item[0]))
    return {horse: idx + 1 for idx, (horse, _) in enumerate(ordered)}


def vote_rank(engine_map: dict[str, dict[str, Any]], depth: int) -> list[dict[str, Any]]:
    votes: Counter[int] = Counter()
    best_rank: dict[int, int] = {}
    engines_by_horse: dict[int, list[str]] = defaultdict(list)

    for engine, payload in engine_map.items():
        top = payload.get("top") or []
        for idx, horse in enumerate(top[:depth], start=1):
            votes[horse] += 1
            best_rank[horse] = min(best_rank.get(horse, idx), idx)
            engines_by_horse[horse].append(engine)

    ranked = sorted(votes, key=lambda h: (-votes[h], best_rank.get(h, 99), h))
    return [
        {
            "horse": horse,
            "votes": votes[horse],
            "best_rank": best_rank.get(horse),
            "engines": sorted(engines_by_horse[horse]),
        }
        for horse in ranked
    ]


def wide_pairs(horses: list[int]) -> list[list[int]]:
    return [[a, b] for a, b in combinations(horses, 2)]


def result_top3(result_json: dict[str, Any]) -> list[int]:
    raw = result_json.get("top3") or result_json.get("finish_order") or []
    out = normalize_top_list(raw)
    return out[:3]


def has_wide_payout(result_json: dict[str, Any]) -> bool:
    payouts = result_json.get("payouts")
    return isinstance(payouts, dict) and bool(payouts.get("wide"))


def build_latest_odds(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = race_key(row)
        if not key:
            continue
        snap = str(row.get("snapshot_at") or "")
        if key not in latest or snap > str(latest[key].get("snapshot_at") or ""):
            odds = normalize_odds_map(row.get("odds_data"))
            latest[key] = {
                "snapshot_at": row.get("snapshot_at"),
                "odds": odds,
                "popularity": popularity_from_odds(odds),
            }
    return latest


def build_result_indexes(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]]:
    by_race_id: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != "finished":
            continue
        rid = row.get("race_id")
        if rid:
            by_race_id[str(rid)] = row
        key = race_key(row)
        if key:
            by_key[key] = row
    return by_race_id, by_key


def make_record(
    race_id: str,
    engine_rows: dict[str, dict[str, Any]],
    result_by_id: dict[str, dict[str, Any]],
    result_by_key: dict[tuple[str, str, int], dict[str, Any]],
    odds_by_key: dict[tuple[str, str, int], dict[str, Any]],
) -> dict[str, Any]:
    sample = next(iter(engine_rows.values()))
    race_number = safe_int(sample.get("race_number")) or infer_race_number(sample.get("race_id"))
    record_key = race_key(sample)

    engines: dict[str, dict[str, Any]] = {}
    for engine in ENGINES:
        row = engine_rows.get(engine)
        if not row:
            continue
        top = normalize_top_list(row.get("top3_horses"))
        top1 = safe_int(row.get("top1_horse"))
        engines[engine] = {
            "top1": top1,
            "top": top,
            "top_len": len(top),
            "created_at": row.get("created_at"),
            "clean_gap_bucket": clean_gap_bucket(row),
        }

    result_row = result_by_id.get(race_id)
    result_match = "race_id" if result_row else None
    if not result_row and record_key:
        result_row = result_by_key.get(record_key)
        result_match = "date_venue_race_number" if result_row else None

    rj = parse_json_maybe(result_row.get("result_json") if result_row else None)
    payouts = rj.get("payouts") if isinstance(rj.get("payouts"), dict) else {}
    odds_payload = odds_by_key.get(record_key or ("", "", -1), {})

    odds = odds_payload.get("odds") or {}
    popularity = odds_payload.get("popularity") or {}
    vote_top3 = vote_rank(engines, 3)
    vote_top5 = vote_rank(engines, 5)

    return {
        "schema_version": "wide_rebirth_dataset.v1",
        "source": "supabase_existing",
        "race_id": race_id,
        "date": sample.get("date"),
        "venue": sample.get("venue"),
        "race_number": race_number,
        "race_type": sample.get("race_type"),
        "engines": engines,
        "engine_count": len(engines),
        "has_four_legacy_engines": all(engine in engines for engine in ENGINES[:4]),
        "has_nlogic": "nlogic" in engines,
        "has_any_top5": any((payload.get("top_len") or 0) >= 5 for payload in engines.values()),
        "all_available_engines_top5": all((payload.get("top_len") or 0) >= 5 for payload in engines.values()),
        "vote_rank_top3": vote_top3,
        "vote_rank_top5": vote_top5,
        "candidate_pairs": {
            "vote_top2_wide": wide_pairs([r["horse"] for r in vote_top5[:2]]),
            "vote_top3_box": wide_pairs([r["horse"] for r in vote_top5[:3]]),
            "vote_top4_box": wide_pairs([r["horse"] for r in vote_top5[:4]]),
            "vote_top5_box": wide_pairs([r["horse"] for r in vote_top5[:5]]),
        },
        "result": {
            "matched_by": result_match,
            "status": result_row.get("status") if result_row else None,
            "winner_number": safe_int(result_row.get("winner_number")) if result_row else None,
            "top3": result_top3(rj),
            "has_payouts": bool(payouts),
            "has_wide": has_wide_payout(rj),
            "payouts": payouts,
        },
        "odds": {
            "snapshot_at": odds_payload.get("snapshot_at"),
            "has_odds": bool(odds),
            "odds": {str(k): v for k, v in sorted(odds.items())},
            "popularity": {str(k): v for k, v in sorted(popularity.items())},
        },
    }


def include_record(record: dict[str, Any], args: argparse.Namespace) -> bool:
    if record["engine_count"] < args.min_engines:
        return False
    if args.require_result and not record["result"]["status"]:
        return False
    if args.require_wide and not record["result"]["has_wide"]:
        return False
    if args.require_odds and not record["odds"]["has_odds"]:
        return False
    if args.require_top5 and not record["has_any_top5"]:
        return False
    if args.require_all_top5 and not record["all_available_engines_top5"]:
        return False
    if args.require_nlogic and not record["has_nlogic"]:
        return False
    return True


def summarize(records: list[dict[str, Any]], raw_races: int) -> dict[str, Any]:
    by_type = Counter(r.get("race_type") or "unknown" for r in records)
    by_month = Counter(str(r.get("date") or "")[:7] for r in records)
    engine_counts = Counter(r["engine_count"] for r in records)
    with_result = sum(1 for r in records if r["result"]["status"])
    with_wide = sum(1 for r in records if r["result"]["has_wide"])
    with_odds = sum(1 for r in records if r["odds"]["has_odds"])
    with_top5 = sum(1 for r in records if r["has_any_top5"])
    with_all_top5 = sum(1 for r in records if r["all_available_engines_top5"])
    with_nlogic = sum(1 for r in records if r["has_nlogic"])
    return {
        "raw_races": raw_races,
        "records": len(records),
        "by_type": by_type,
        "by_month": by_month,
        "engine_counts": engine_counts,
        "with_result": with_result,
        "with_wide": with_wide,
        "with_odds": with_odds,
        "with_top5": with_top5,
        "with_all_top5": with_all_top5,
        "with_nlogic": with_nlogic,
    }


def counter_lines(counter: Counter[Any]) -> list[str]:
    return [f"| {key} | {value:,} |" for key, value in counter.most_common()]


def build_report(summary: dict[str, Any], args: argparse.Namespace, out_jsonl: Path) -> str:
    total = summary["records"]
    lines = [
        f"# 穴党参謀AI ワイド再構築 データセット作成 {date.today().isoformat()}",
        "",
        f"- 対象期間: {args.since} 〜 {args.until}",
        f"- 出力: `{out_jsonl}`",
        f"- source: `supabase_existing`",
        "",
        "## 条件",
        "",
        f"- min_engines: {args.min_engines}",
        f"- require_result: {args.require_result}",
        f"- require_wide: {args.require_wide}",
        f"- require_odds: {args.require_odds}",
        f"- require_top5: {args.require_top5}",
        f"- require_all_top5: {args.require_all_top5}",
        f"- require_nlogic: {args.require_nlogic}",
        "",
        "## 件数",
        "",
        f"- raw engine races: {summary['raw_races']:,}",
        f"- dataset records: {total:,}",
        f"- resultあり: {summary['with_result']:,} ({pct(summary['with_result'], total)})",
        f"- wide払戻あり: {summary['with_wide']:,} ({pct(summary['with_wide'], total)})",
        f"- 人気あり: {summary['with_odds']:,} ({pct(summary['with_odds'], total)})",
        f"- top5あり: {summary['with_top5']:,} ({pct(summary['with_top5'], total)})",
        f"- available engines all top5: {summary['with_all_top5']:,} ({pct(summary['with_all_top5'], total)})",
        f"- nlogicあり: {summary['with_nlogic']:,} ({pct(summary['with_nlogic'], total)})",
        "",
        "## race_type",
        "",
        "| race_type | records |",
        "|---|---:|",
        *counter_lines(summary["by_type"]),
        "",
        "## engine_count",
        "",
        "| engine_count | records |",
        "|---|---:|",
        *counter_lines(summary["engine_counts"]),
        "",
        "## month",
        "",
        "| month | records |",
        "|---|---:|",
        *counter_lines(summary["by_month"]),
        "",
        "## 判断",
        "",
        "- このJSONLは既存DBの実態を固定するためのもの。",
        "- NLogicは既存データにないため、5エンジン検証には別途バックエンドAPI再生成データセットが必要。",
        "- top5不足のレースがあるため、top5戦略の本検証では `require_top5` またはAPI再生成版を使う。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build wide rebuild JSONL dataset from existing Supabase rows")
    parser.add_argument("--since", default="2026-03-01", help="start date YYYY-MM-DD")
    parser.add_argument("--until", default=date.today().isoformat(), help="end date YYYY-MM-DD")
    parser.add_argument("--out", default="", help="output JSONL path")
    parser.add_argument("--report", default="", help="output markdown report path")
    parser.add_argument("--min-engines", type=int, default=3)
    parser.add_argument("--require-result", action="store_true", default=True)
    parser.add_argument("--allow-missing-result", action="store_false", dest="require_result")
    parser.add_argument("--require-wide", action="store_true", default=True)
    parser.add_argument("--allow-missing-wide", action="store_false", dest="require_wide")
    parser.add_argument("--require-odds", action="store_true", default=False)
    parser.add_argument("--require-top5", action="store_true", default=False)
    parser.add_argument("--require-all-top5", action="store_true", default=False)
    parser.add_argument("--require-nlogic", action="store_true", default=False)
    parser.add_argument("--no-vps-env", action="store_true", help="do not fetch Supabase env from VPS")
    args = parser.parse_args()

    load_supabase_env(allow_vps=not args.no_vps_env)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    sb = create_client(url, key)

    logger.info("loading engine_hit_rates %s..%s", args.since, args.until)
    engine_rows = fetch_all(
        sb,
        "engine_hit_rates",
        "date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at",
        gte={"date": args.since},
        lte={"date": args.until},
    )
    logger.info("engine rows: %s", len(engine_rows))

    logger.info("loading race_results %s..%s", args.since, args.until)
    result_rows = fetch_all(
        sb,
        "race_results",
        "race_id,race_date,venue,race_type,status,winner_number,result_json",
        gte={"race_date": args.since},
        lte={"race_date": args.until},
    )
    result_by_id, result_by_key = build_result_indexes(result_rows)
    logger.info("finished result races: %s", len(result_by_id))

    logger.info("loading odds_snapshots %s..%s", args.since, args.until)
    odds_rows = fetch_all(
        sb,
        "odds_snapshots",
        "race_date,venue,race_number,odds_data,snapshot_at",
        gte={"race_date": args.since},
        lte={"race_date": args.until},
    )
    odds_by_key = build_latest_odds(odds_rows)
    logger.info("latest odds races: %s", len(odds_by_key))

    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in engine_rows:
        rid = row.get("race_id")
        engine = row.get("engine")
        if not rid or not engine:
            continue
        grouped[str(rid)][str(engine)] = row

    records: list[dict[str, Any]] = []
    for rid in sorted(grouped):
        record = make_record(rid, grouped[rid], result_by_id, result_by_key, odds_by_key)
        if include_record(record, args):
            records.append(record)

    records.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("venue") or ""), int(r.get("race_number") or 0), str(r.get("race_id") or "")))

    out_path = Path(args.out) if args.out else DATA_DIR / f"wide_rebirth_dataset_{args.since.replace('-', '')}_{args.until.replace('-', '')}_existing.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = summarize(records, raw_races=len(grouped))
    report = build_report(summary, args, out_path)
    report_path = Path(args.report) if args.report else DOCS_DIR / f"wide_rebirth_dataset_build_{date.today().strftime('%Y%m%d')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report + "\n", encoding="utf-8")

    print(report)
    print(f"\n[dataset] {out_path}")
    print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
