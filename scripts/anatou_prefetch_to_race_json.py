#!/usr/bin/env python3
"""Convert prefetch_races.py output to Anatou race payload JSON.

The output format matches audit_5eng_step1_export.py closely enough for
build_wide_rebirth_dataset_from_api.py.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"


def safe_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_date(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def race_type_of(race: dict[str, Any]) -> str:
    return "nar" if race.get("is_local") else "jra"


def distance_text(race: dict[str, Any]) -> str:
    raw = str(race.get("distance") or "")
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"{digits}m" if digits else raw


def popularity_map(race: dict[str, Any]) -> dict[str, int]:
    numbers = race.get("horse_numbers") or []
    popularities = race.get("popularities") or []
    out: dict[str, int] = {}
    for idx, horse in enumerate(numbers):
        pop = safe_int(popularities[idx]) if idx < len(popularities) else 0
        if horse and pop:
            out[str(horse)] = pop
    return out


def convert_race(race: dict[str, Any]) -> dict[str, Any] | None:
    horses = race.get("horses") or []
    horse_numbers = race.get("horse_numbers") or []
    if len(horses) < 5 or len(horse_numbers) != len(horses):
        return None

    date_iso = normalize_date(race.get("race_date") or "")
    date_compact = date_iso.replace("-", "")
    venue = race.get("venue") or ""
    race_number = safe_int(race.get("race_number"))
    if not date_compact or not venue or not race_number:
        return None

    posts = race.get("posts") or []
    jockeys = race.get("jockeys") or []
    payload = {
        "race_id": race.get("race_id") or f"{date_compact}-{venue}-{race_number}",
        "race_id_netkeiba": race.get("race_id_netkeiba"),
        "horses": horses,
        "horse_numbers": horse_numbers,
        "venue": venue,
        "race_number": race_number,
        "jockeys": jockeys,
        "posts": posts if len(posts) == len(horses) else horse_numbers,
        "distance": distance_text(race),
        "track_condition": race.get("track_condition") or "良",
    }

    return {
        "payload": payload,
        "result": {},
        "pop_map": popularity_map(race),
        "meta": {
            "date": date_iso,
            "venue": venue,
            "race_no": race_number,
            "weekday": ["月", "火", "水", "木", "金", "土", "日"][datetime.strptime(date_iso, "%Y-%m-%d").weekday()],
            "race_type": race_type_of(race),
            "distance": distance_text(race),
            "start_time": race.get("start_time") or "",
            "race_name": race.get("race_name") or "",
            "race_id_netkeiba": race.get("race_id_netkeiba"),
        },
    }


def filter_records(records: list[dict[str, Any]], race_type: str) -> list[dict[str, Any]]:
    if race_type == "both":
        return records
    return [record for record in records if (record.get("meta") or {}).get("race_type") == race_type]


def build_report(records: list[dict[str, Any]], input_path: Path, out_path: Path) -> str:
    by_type: dict[str, int] = {}
    by_venue: dict[str, int] = {}
    with_pop = 0
    for record in records:
        meta = record.get("meta") or {}
        by_type[meta.get("race_type") or "unknown"] = by_type.get(meta.get("race_type") or "unknown", 0) + 1
        by_venue[meta.get("venue") or "unknown"] = by_venue.get(meta.get("venue") or "unknown", 0) + 1
        if record.get("pop_map"):
            with_pop += 1
    lines = [
        "# 穴党参謀AI prefetch to race-json",
        "",
        f"- input: `{input_path}`",
        f"- output: `{out_path}`",
        f"- records: {len(records):,}",
        f"- with popularity: {with_pop:,}",
        "",
        "## race_type",
        "",
        "| race_type | races |",
        "|---|---:|",
        *[f"| {k} | {v:,} |" for k, v in sorted(by_type.items())],
        "",
        "## venue",
        "",
        "| venue | races |",
        "|---|---:|",
        *[f"| {k} | {v:,} |" for k, v in sorted(by_venue.items(), key=lambda x: (-x[1], x[0]))],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert prefetch JSON to Anatou race payload JSON")
    parser.add_argument("--input", required=True, help="data/prefetch/races_YYYYMMDD.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--race-type", choices=("jra", "nar", "both"), default="both")
    args = parser.parse_args()

    input_path = Path(args.input)
    source = json.loads(input_path.read_text(encoding="utf-8"))
    converted = [record for race in (source.get("races") or []) if (record := convert_race(race))]
    records = filter_records(converted, args.race_type)
    date_str = str((source.get("metadata") or {}).get("date") or input_path.stem.replace("races_", ""))
    out_path = Path(args.out) if args.out else DATA_DIR / f"anatou_races_{args.race_type}_{date_str}.json"
    report_path = Path(args.report) if args.report else PROJECT_DIR / "docs" / f"anatou_prefetch_to_race_json_{args.race_type}_{date_str}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    report = build_report(records, input_path, out_path)
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[race_json] {out_path}")
    print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
