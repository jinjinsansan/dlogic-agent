#!/usr/bin/env python3
"""Check forward diagnosis results against race outcomes.

This is a diagnosis review, not a betting ROI report.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_DIR / "docs"


@dataclass
class Outcome:
    race_id: str
    inferred_top3: set[int]
    max_wide: int
    wide_count: int


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compact_race_id(race_id: str) -> str:
    if len(race_id) >= 10 and race_id[4] == "-" and race_id[7] == "-":
        return race_id[:10].replace("-", "") + race_id[10:]
    return race_id


def outcome_keys(row: dict[str, Any]) -> list[str]:
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
    return list(dict.fromkeys(keys))


def build_outcomes(paths: list[Path]) -> dict[str, Outcome]:
    out: dict[str, Outcome] = {}
    for path in paths:
        for row in load_jsonl(path):
            result = row.get("result") or {}
            if result.get("status") != "finished" or not result.get("has_wide"):
                continue
            payouts = result.get("payouts") or {}
            wide_entries = payouts.get("wide") or []
            if not wide_entries:
                continue
            inferred_top3: set[int] = set()
            wide_payouts: list[int] = []
            for entry in wide_entries:
                for value in entry.get("combo") or []:
                    horse = safe_int(value)
                    if horse is not None:
                        inferred_top3.add(horse)
                payout = safe_int(entry.get("payout")) or 0
                if payout:
                    wide_payouts.append(payout)
            outcome = Outcome(
                race_id=str(row.get("race_id") or ""),
                inferred_top3=inferred_top3,
                max_wide=max(wide_payouts) if wide_payouts else 0,
                wide_count=len(wide_payouts),
            )
            for key in outcome_keys(row):
                out[key] = outcome
    return out


def preview_races(payload: dict[str, Any]) -> list[dict[str, Any]]:
    seen = set()
    rows = []
    sections = payload.get("sections") or {}
    for section, items in sections.items():
        for item in items or []:
            rid = str(item.get("race_id") or f"{item.get('date')}-{item.get('venue')}-{item.get('race_number')}")
            key = (section, rid)
            if key in seen:
                continue
            seen.add(key)
            row = dict(item)
            row["_section"] = section
            rows.append(row)
    return rows


def horse_numbers(items: list[dict[str, Any]]) -> list[int]:
    out = []
    for item in items or []:
        horse = safe_int(item.get("horse"))
        if horse is not None:
            out.append(horse)
    return out


def row_join_keys(row: dict[str, Any]) -> list[str]:
    rid = str(row.get("race_id") or "")
    keys = [rid, compact_race_id(rid)] if rid else []
    dt = str(row.get("date") or "")
    venue = row.get("venue")
    race_number = row.get("race_number")
    if dt and venue and race_number is not None:
        keys.append(f"{dt}-{venue}-{race_number}")
        keys.append(f"{dt.replace('-', '')}-{venue}-{race_number}")
    return list(dict.fromkeys([key for key in keys if key]))


def find_outcome(row: dict[str, Any], outcomes: dict[str, Outcome]) -> Outcome | None:
    for key in row_join_keys(row):
        if key in outcomes:
            return outcomes[key]
    return None


def mark(value: bool) -> str:
    return "yes" if value else "no"


def build_report(preview: dict[str, Any], preview_rows: list[dict[str, Any]], outcomes: dict[str, Outcome], args: argparse.Namespace) -> str:
    lines = [
        f"# 穴党参謀AI フォワード結果確認 {preview.get('date_filter') or ''}",
        "",
        f"- preview: `{args.preview_json}`",
        f"- race_dataset: `{', '.join(args.race_dataset)}`",
        f"- preview races: {len(preview_rows):,}",
        "",
        "## 診断別結果",
        "",
        "| section | race | label | holes_in_top3 | low_popular_missed | max_wide | result |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    checked = 0
    hole_hits = 0
    hole_total = 0
    low_missed = 0
    low_total = 0
    high_wide = 0

    for row in preview_rows:
        outcome = find_outcome(row, outcomes)
        race = f"{row.get('date')} {row.get('venue')}{row.get('race_number')}R"
        holes = horse_numbers(row.get("ai_hole_horses") or [])
        lows = horse_numbers(row.get("ai_low_rated_popular_horses") or [])
        holes_in_top3 = sum(1 for horse in holes if outcome and horse in outcome.inferred_top3)
        lows_missed = sum(1 for horse in lows if outcome and horse not in outcome.inferred_top3)
        if outcome:
            checked += 1
            high_wide += 1 if outcome.max_wide >= args.high_wide else 0
            hole_hits += holes_in_top3
            hole_total += len(holes)
            low_missed += lows_missed
            low_total += len(lows)
        result = "outcome found" if outcome else "no outcome"
        lines.append(
            f"| {row.get('_section')} | {race} | {row.get('label_text')} | "
            f"{holes_in_top3}/{len(holes)} | {lows_missed}/{len(lows)} | "
            f"{outcome.max_wide if outcome else 0} | {result} |"
        )

    lines.extend([
        "",
        "## Summary",
        "",
        f"- outcome found: {checked:,}/{len(preview_rows):,}",
        f"- AI穴馬 3着内相当: {hole_hits:,}/{hole_total:,}",
        f"- AI低評価人気 3着内相当外: {low_missed:,}/{low_total:,}",
        f"- high wide races: {high_wide:,}/{checked:,} (threshold {args.high_wide})",
        "",
        "## Notes",
        "",
        "- 3着内はワイド払戻組み合わせから推定している。",
        "- これは診断ラベルの妥当性確認であり、買い目ROIではない。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Anatou forward diagnosis results")
    parser.add_argument("--preview-json", required=True)
    parser.add_argument("--race-dataset", action="append", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--high-wide", type=int, default=1000)
    args = parser.parse_args()

    preview_path = Path(args.preview_json)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    outcomes = build_outcomes([Path(path) for path in args.race_dataset])
    rows = preview_races(preview)
    report = build_report(preview, rows, outcomes, args)
    out_path = Path(args.out) if args.out else DOCS_DIR / "anatou_forward" / str(preview.get("date_filter") or "unknown").replace("-", "") / "result_check.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[report] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
