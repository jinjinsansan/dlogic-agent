#!/usr/bin/env python3
"""Fetch local result data for an Anatou forward log.

Reads a forward manifest and its source wide JSONL, resolves netkeiba IDs from
prefetch JSON, scrapes finished results, and writes a result-enriched wide JSONL.
No Supabase writes are performed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"
sys.path.insert(0, str(PROJECT_DIR))

from scrapers.race_result import fetch_race_result  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def compact_race_id(race_id: str) -> str:
    if len(race_id) >= 10 and race_id[4] == "-" and race_id[7] == "-":
        return race_id[:10].replace("-", "") + race_id[10:]
    return race_id


def race_keys(row: dict[str, Any]) -> list[str]:
    keys = []
    rid = str(row.get("race_id") or "")
    if rid:
        keys.extend([rid, compact_race_id(rid)])
    dt = str(row.get("date") or "")
    venue = row.get("venue")
    race_number = row.get("race_number")
    if dt and venue and race_number is not None:
        keys.append(f"{dt}-{venue}-{race_number}")
        keys.append(f"{dt.replace('-', '')}-{venue}-{race_number}")
    return list(dict.fromkeys([key for key in keys if key]))


def load_prefetch_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for race in data.get("races") or []:
        for key in race_keys({
            "race_id": race.get("race_id"),
            "date": race.get("race_date"),
            "venue": race.get("venue"),
            "race_number": race.get("race_number"),
        }):
            out[key] = race
    return out


def result_to_dataset_result(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {
            "matched_by": "not_finished_or_unavailable",
            "status": "pending",
            "winner_number": None,
            "top3": [],
            "has_payouts": False,
            "has_wide": False,
            "payouts": {},
        }
    rj = result.get("result_json") or {}
    payouts = rj.get("payouts") or {}
    return {
        "matched_by": "netkeiba_scrape",
        "status": result.get("status") or "finished",
        "winner_number": result.get("winner_number"),
        "top3": rj.get("top3") or [],
        "has_payouts": bool(payouts),
        "has_wide": bool(payouts.get("wide")),
        "payouts": payouts,
    }


def build_report(summary: dict[str, Any], out_path: Path, args: argparse.Namespace) -> str:
    lines = [
        "# 穴党参謀AI forward result fetch",
        "",
        f"- manifest: `{args.manifest}`",
        f"- prefetch: `{args.prefetch}`",
        f"- output: `{out_path}`",
        "",
        "## Summary",
        "",
        f"- input records: {summary['input_records']:,}",
        f"- fetched results: {summary['fetched']:,}",
        f"- pending/unavailable: {summary['pending']:,}",
        f"- has wide: {summary['has_wide']:,}",
        f"- errors: {summary['errors']:,}",
        "",
        "## Pending",
        "",
    ]
    if summary["pending_races"]:
        lines.extend(f"- {item}" for item in summary["pending_races"][:80])
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch result-enriched dataset for Anatou forward log")
    parser.add_argument("--manifest", required=True, help="data/anatou_forward/YYYYMMDD/manifest.json")
    parser.add_argument("--prefetch", required=True, help="data/prefetch/races_YYYYMMDD.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_paths = [Path(p) for p in manifest.get("source_wide_jsonl") or []]
    rows = [row for path in source_paths for row in load_jsonl(path)]
    if args.limit:
        rows = rows[: args.limit]
    prefetch_index = load_prefetch_index(Path(args.prefetch))
    date_key = str(manifest.get("date") or "unknown")

    enriched = []
    summary = {
        "input_records": len(rows),
        "fetched": 0,
        "pending": 0,
        "has_wide": 0,
        "errors": 0,
        "pending_races": [],
    }

    for idx, row in enumerate(rows, start=1):
        match = None
        for key in race_keys(row):
            match = prefetch_index.get(key)
            if match:
                break
        race_type = "nar" if (match or {}).get("is_local") else str(row.get("race_type") or "jra")
        netkeiba_id = (match or {}).get("race_id_netkeiba")
        result = None
        if netkeiba_id:
            try:
                result = fetch_race_result(str(netkeiba_id), race_type)
            except Exception:
                summary["errors"] += 1
                result = None
            if args.sleep:
                time.sleep(args.sleep)
        new_row = dict(row)
        new_row["result"] = result_to_dataset_result(result)
        if result:
            summary["fetched"] += 1
            if new_row["result"]["has_wide"]:
                summary["has_wide"] += 1
        else:
            summary["pending"] += 1
            summary["pending_races"].append(f"{row.get('date')} {row.get('venue')}{row.get('race_number')}R")
        enriched.append(new_row)
        if idx == 1 or idx % 20 == 0:
            print(f"[progress] {idx}/{len(rows)} fetched={summary['fetched']} pending={summary['pending']}", flush=True)

    out_path = Path(args.out) if args.out else DATA_DIR / "anatou_forward" / date_key / "results_dataset.jsonl"
    report_path = Path(args.report) if args.report else DOCS_DIR / "anatou_forward" / date_key / "result_fetch.md"
    write_jsonl(out_path, enriched)
    report = build_report(summary, out_path, args)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[dataset] {out_path}")
    print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
