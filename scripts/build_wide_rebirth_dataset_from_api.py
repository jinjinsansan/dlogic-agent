#!/usr/bin/env python3
"""Build a wide_rebirth JSONL dataset by replaying race payloads to backend API.

Input is the Step 1 export format produced by audit_5eng_step1_export.py:
    data/5eng_races_{race_type}_{since}_{until}.json

The input contains race entries and popularity. This script calls
/api/v2/predictions/newspaper to regenerate top5 predictions, then joins
wide payouts from an existing wide_rebirth dataset when available.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

import requests

from build_wide_rebirth_dataset import popularity_from_odds, vote_rank


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def race_id_from_input(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    meta = record.get("meta") or {}
    if payload.get("race_id"):
        text = str(payload["race_id"])
        if len(text) >= 8 and text[:8].isdigit():
            # Normalize 20260301-名古屋-1 -> 2026-03-01-名古屋-1 is not desired.
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}{text[8:]}" if text[8:9] != "-" else f"{text[:4]}-{text[4:6]}-{text[6:8]}{text[8:]}"
        return text
    return f"{meta.get('date')}-{meta.get('venue')}-{meta.get('race_no')}"


def canonical_race_id(record: dict[str, Any]) -> str:
    meta = record.get("meta") or {}
    return f"{meta.get('date')}-{meta.get('venue')}-{meta.get('race_no')}"


def load_input(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def existing_join_keys(record: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    rid = str(record.get("race_id") or "")
    if rid:
        keys.append(rid)
    dt = str(record.get("date") or "")
    venue = record.get("venue")
    race_number = record.get("race_number")
    if dt and venue and race_number is not None:
        compact = dt.replace("-", "")
        keys.append(f"{dt}-{venue}-{race_number}")
        keys.append(f"{compact}-{venue}-{race_number}")
    return list(dict.fromkeys(keys))


def load_existing_join(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            for key in existing_join_keys(record):
                out[key] = record
    return out


def call_predictions(api_url: str, payload: dict[str, Any], timeout: int, retries: int, sleep_sec: float) -> tuple[dict[str, list[int]], str | None]:
    url = f"{api_url.rstrip('/')}/api/v2/predictions/newspaper"
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            out: dict[str, list[int]] = {}
            for engine in ENGINES:
                raw = body.get(engine)
                if not isinstance(raw, list):
                    continue
                picks: list[int] = []
                for item in raw[:5]:
                    num = safe_int(item)
                    if num is not None and num not in picks:
                        picks.append(num)
                if picks:
                    out[engine] = picks
            return out, None
        except Exception as exc:  # noqa: BLE001 - report API failures per race
            last_error = str(exc)
            if attempt < retries:
                time.sleep(sleep_sec)
    return {}, last_error


def wide_pairs(horses: list[int]) -> list[list[int]]:
    return [[a, b] for a, b in combinations(horses, 2)]


def normalize_existing_payouts(existing: dict[str, Any] | None) -> dict[str, Any]:
    if not existing:
        return {}
    return ((existing.get("result") or {}).get("payouts") or {})


def build_record(input_record: dict[str, Any], preds: dict[str, list[int]], existing: dict[str, Any] | None) -> dict[str, Any]:
    meta = input_record.get("meta") or {}
    result = input_record.get("result") or {}
    pop_map_raw = input_record.get("pop_map") or {}
    pop_map = {safe_int(k): safe_int(v) for k, v in pop_map_raw.items() if safe_int(k) is not None and safe_int(v) is not None}

    engines = {
        engine: {
            "top1": picks[0] if picks else None,
            "top": picks,
            "top_len": len(picks),
            "created_at": None,
            "clean_gap_bucket": "api_replay",
        }
        for engine, picks in preds.items()
    }
    vote_top3 = vote_rank(engines, 3)
    vote_top5 = vote_rank(engines, 5)
    payouts = normalize_existing_payouts(existing)
    odds = {}
    if pop_map:
        # Keep popularity from PCKEIBA. Odds are not available in Step 1 export.
        odds = {
            "snapshot_at": None,
            "has_odds": False,
            "odds": {},
            "popularity": {str(k): v for k, v in sorted(pop_map.items())},
        }
    else:
        odds = {"snapshot_at": None, "has_odds": False, "odds": {}, "popularity": {}}

    rid = canonical_race_id(input_record)
    return {
        "schema_version": "wide_rebirth_dataset.v1",
        "source": "backend_api_replay",
        "race_id": rid,
        "date": meta.get("date"),
        "venue": meta.get("venue"),
        "race_number": meta.get("race_no"),
        "race_type": meta.get("race_type"),
        "engines": engines,
        "engine_count": len(engines),
        "has_four_legacy_engines": all(engine in engines for engine in ENGINES[:4]),
        "has_nlogic": "nlogic" in engines,
        "has_any_top5": any((payload.get("top_len") or 0) >= 5 for payload in engines.values()),
        "all_available_engines_top5": all((payload.get("top_len") or 0) >= 5 for payload in engines.values()) if engines else False,
        "vote_rank_top3": vote_top3,
        "vote_rank_top5": vote_top5,
        "candidate_pairs": {
            "vote_top2_wide": wide_pairs([r["horse"] for r in vote_top5[:2]]),
            "vote_top3_box": wide_pairs([r["horse"] for r in vote_top5[:3]]),
            "vote_top4_box": wide_pairs([r["horse"] for r in vote_top5[:4]]),
            "vote_top5_box": wide_pairs([r["horse"] for r in vote_top5[:5]]),
        },
        "result": {
            "matched_by": "existing_dataset" if payouts else "input_win_only",
            "status": "finished",
            "winner_number": safe_int(result.get("winner")),
            "top3": [],
            "has_payouts": bool(payouts),
            "has_wide": bool(payouts.get("wide")) if isinstance(payouts, dict) else False,
            "payouts": payouts,
        },
        "odds": odds,
    }


def should_keep(record: dict[str, Any], args: argparse.Namespace) -> bool:
    if record["engine_count"] < args.min_engines:
        return False
    if args.require_wide and not record["result"]["has_wide"]:
        return False
    if args.require_nlogic and not record["has_nlogic"]:
        return False
    return True


def summarize(records: list[dict[str, Any]], api_errors: int, total_input: int) -> dict[str, Any]:
    by_type = Counter(r.get("race_type") or "unknown" for r in records)
    by_engine_count = Counter(r.get("engine_count") for r in records)
    with_nlogic = sum(1 for r in records if r.get("has_nlogic"))
    with_top5 = sum(1 for r in records if r.get("has_any_top5"))
    all_top5 = sum(1 for r in records if r.get("all_available_engines_top5"))
    with_wide = sum(1 for r in records if (r.get("result") or {}).get("has_wide"))
    return {
        "total_input": total_input,
        "records": len(records),
        "api_errors": api_errors,
        "by_type": by_type,
        "by_engine_count": by_engine_count,
        "with_nlogic": with_nlogic,
        "with_top5": with_top5,
        "all_top5": all_top5,
        "with_wide": with_wide,
    }


def counter_rows(counter: Counter[Any]) -> list[str]:
    return [f"| {k} | {v:,} |" for k, v in counter.most_common()]


def pct(num: int | float, den: int | float) -> str:
    return f"{(num / den * 100):.1f}%" if den else "0.0%"


def build_report(summary: dict[str, Any], args: argparse.Namespace, out_path: Path) -> str:
    lines = [
        f"# 穴党参謀AI ワイド再構築 API再生成データセット {date.today().isoformat()}",
        "",
        f"- input: `{args.input}`",
        f"- output: `{out_path}`",
        f"- api_url: `{args.api_url}`",
        "",
        "## 件数",
        "",
        f"- input races: {summary['total_input']:,}",
        f"- output records: {summary['records']:,}",
        f"- api errors: {summary['api_errors']:,}",
        f"- NLogicあり: {summary['with_nlogic']:,} ({pct(summary['with_nlogic'], summary['records'])})",
        f"- top5あり: {summary['with_top5']:,} ({pct(summary['with_top5'], summary['records'])})",
        f"- all available engines top5: {summary['all_top5']:,} ({pct(summary['all_top5'], summary['records'])})",
        f"- wide払戻あり: {summary['with_wide']:,} ({pct(summary['with_wide'], summary['records'])})",
        "",
        "## race_type",
        "",
        "| race_type | records |",
        "|---|---:|",
        *counter_rows(summary["by_type"]),
        "",
        "## engine_count",
        "",
        "| engine_count | records |",
        "|---|---:|",
        *counter_rows(summary["by_engine_count"]),
        "",
        "## 注意",
        "",
        "- これは現在のバックエンドモデルで過去レースを再予測したデータ。",
        "- 当時の配信時点モデルではないため、実運用検証とは区別する。",
        "- ワイド払戻は既存wide_rebirth datasetから突合している。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay race payloads to backend API and build wide_rebirth JSONL")
    parser.add_argument("--input", default=str(DATA_DIR / "5eng_races_nar_20260301_20260430.json"))
    parser.add_argument("--existing-dataset", default=str(DATA_DIR / "wide_rebirth_dataset_20260301_20260525_existing.jsonl"))
    parser.add_argument("--out", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-sleep", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--min-engines", type=int, default=4)
    parser.add_argument("--require-wide", action="store_true", default=True)
    parser.add_argument("--allow-missing-wide", action="store_false", dest="require_wide")
    parser.add_argument("--require-nlogic", action="store_true", default=False)
    parser.add_argument("--resume", action="store_true", help="append to existing output and skip already written race_ids")
    args = parser.parse_args()

    input_path = Path(args.input)
    existing_path = Path(args.existing_dataset) if args.existing_dataset else None
    source_records = load_input(input_path)
    if args.skip and args.skip > 0:
        source_records = source_records[args.skip:]
    if args.limit and args.limit > 0:
        source_records = source_records[: args.limit]
    existing = load_existing_join(existing_path)

    out_path = Path(args.out) if args.out else DATA_DIR / f"wide_rebirth_dataset_api_{input_path.stem}.jsonl"
    report_path = Path(args.report) if args.report else DOCS_DIR / f"wide_rebirth_dataset_api_{date.today().strftime('%Y%m%d')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    output_records: list[dict[str, Any]] = []
    written_ids: set[str] = set()
    if args.resume and out_path.exists():
        with out_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    existing_record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = str(existing_record.get("race_id") or "")
                if rid:
                    written_ids.add(rid)
                    output_records.append(existing_record)
        logger.info("resume enabled: loaded %s existing records", len(written_ids))

    api_errors = 0
    open_mode = "a" if args.resume else "w"
    with out_path.open(open_mode, encoding="utf-8", newline="\n") as f:
        for idx, source in enumerate(source_records, start=1):
            rid = canonical_race_id(source)
            if rid in written_ids:
                continue
            if idx == 1 or idx % 50 == 0:
                logger.info("replaying %s/%s", idx, len(source_records))
            preds, err = call_predictions(args.api_url, source.get("payload") or {}, args.timeout, args.retries, args.retry_sleep)
            if not preds:
                api_errors += 1
                if api_errors <= 5:
                    logger.warning("API error for %s: %s", canonical_race_id(source), err)
                continue

            compact_rid = rid.replace("-", "", 2) if len(rid) >= 10 else rid
            record = build_record(source, preds, existing.get(rid) or existing.get(compact_rid))
            if should_keep(record, args):
                output_records.append(record)
                written_ids.add(record["race_id"])
                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
            if args.sleep > 0:
                time.sleep(args.sleep)

    summary = summarize(output_records, api_errors, len(source_records))
    report = build_report(summary, args, out_path)
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[dataset] {out_path}")
    print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
