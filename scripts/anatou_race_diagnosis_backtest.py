#!/usr/bin/env python3
"""Backtest diagnostic labels for Anatou race diagnosis AI.

This evaluates whether diagnosis content is useful:
- Do AI hole horses hit the inferred top3?
- Do danger popular horses miss the inferred top3?
- Do market_gap / watch labels capture races with larger wide payouts?
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_DIR / "docs"


@dataclass
class RaceOutcome:
    race_id: str
    inferred_top3: set[int]
    max_wide_payout: int
    avg_wide_payout: float
    wide_count: int


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compact_race_id(race_id: str) -> str:
    # 2026-03-14-中山-1 -> 20260314-中山-1
    if len(race_id) >= 10 and race_id[4] == "-" and race_id[7] == "-":
        return race_id[:10].replace("-", "") + race_id[10:]
    return race_id


def build_outcome_index(race_rows: list[dict[str, Any]]) -> dict[str, RaceOutcome]:
    out: dict[str, RaceOutcome] = {}
    for row in race_rows:
        rid = str(row.get("race_id") or "")
        payouts = ((row.get("result") or {}).get("payouts") or {})
        wide_entries = payouts.get("wide") or []
        top3: set[int] = set()
        wide_payouts: list[int] = []
        for entry in wide_entries:
            combo = entry.get("combo") or []
            for value in combo:
                horse = safe_int(value)
                if horse is not None:
                    top3.add(horse)
            payout = safe_int(entry.get("payout")) or 0
            if payout > 0:
                wide_payouts.append(payout)
        outcome = RaceOutcome(
            race_id=rid,
            inferred_top3=top3,
            max_wide_payout=max(wide_payouts) if wide_payouts else 0,
            avg_wide_payout=sum(wide_payouts) / len(wide_payouts) if wide_payouts else 0.0,
            wide_count=len(wide_payouts),
        )
        for key in {rid, compact_race_id(rid)}:
            out[key] = outcome
    return out


def horse_list(row: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = row.get(key) or []
    return value if isinstance(value, list) else []


def horse_number(item: dict[str, Any]) -> int | None:
    return safe_int(item.get("horse"))


def init_stats() -> dict[str, Any]:
    return {
        "races": 0,
        "with_outcome": 0,
        "hole_horses": 0,
        "hole_top3": 0,
        "danger_horses": 0,
        "danger_missed": 0,
        "max_wide_sum": 0,
        "avg_wide_sum": 0.0,
        "high_wide_races": 0,
        "super_high_wide_races": 0,
        "watch_sum": 0.0,
        "gap_sum": 0.0,
    }


def add_row_stats(stats: dict[str, Any], row: dict[str, Any], outcome: RaceOutcome | None, high_threshold: int, super_high_threshold: int) -> None:
    stats["races"] += 1
    stats["watch_sum"] += float(row.get("watch_score") or 0)
    stats["gap_sum"] += float(row.get("market_gap_score") or 0)
    if not outcome:
        return
    stats["with_outcome"] += 1
    stats["max_wide_sum"] += outcome.max_wide_payout
    stats["avg_wide_sum"] += outcome.avg_wide_payout
    if outcome.max_wide_payout >= high_threshold:
        stats["high_wide_races"] += 1
    if outcome.max_wide_payout >= super_high_threshold:
        stats["super_high_wide_races"] += 1

    for item in horse_list(row, "ai_hole_horses"):
        horse = horse_number(item)
        if horse is None:
            continue
        stats["hole_horses"] += 1
        if horse in outcome.inferred_top3:
            stats["hole_top3"] += 1

    for item in horse_list(row, "danger_popular_horses"):
        horse = horse_number(item)
        if horse is None:
            continue
        stats["danger_horses"] += 1
        if horse not in outcome.inferred_top3:
            stats["danger_missed"] += 1


def finalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    races = stats["races"]
    with_outcome = stats["with_outcome"]
    hole_horses = stats["hole_horses"]
    danger_horses = stats["danger_horses"]
    return {
        **stats,
        "hole_top3_rate": stats["hole_top3"] / hole_horses * 100 if hole_horses else 0.0,
        "danger_miss_rate": stats["danger_missed"] / danger_horses * 100 if danger_horses else 0.0,
        "avg_max_wide": stats["max_wide_sum"] / with_outcome if with_outcome else 0.0,
        "avg_wide": stats["avg_wide_sum"] / with_outcome if with_outcome else 0.0,
        "high_wide_rate": stats["high_wide_races"] / with_outcome * 100 if with_outcome else 0.0,
        "super_high_wide_rate": stats["super_high_wide_races"] / with_outcome * 100 if with_outcome else 0.0,
        "avg_watch": stats["watch_sum"] / races if races else 0.0,
        "avg_gap": stats["gap_sum"] / races if races else 0.0,
    }


def grouped_stats(
    diagnosis_rows: list[dict[str, Any]],
    outcomes: dict[str, RaceOutcome],
    high_threshold: int,
    super_high_threshold: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_label: dict[str, dict[str, Any]] = defaultdict(init_stats)
    by_use: dict[str, dict[str, Any]] = defaultdict(init_stats)
    by_venue: dict[str, dict[str, Any]] = defaultdict(init_stats)
    by_watch_bucket: dict[str, dict[str, Any]] = defaultdict(init_stats)

    for row in diagnosis_rows:
        rid = str(row.get("race_id") or "")
        outcome = outcomes.get(rid) or outcomes.get(compact_race_id(rid))
        label = str(row.get("primary_label") or "unknown")
        use = str(row.get("suggested_use") or "unknown")
        venue = str(row.get("venue") or "unknown")
        watch = float(row.get("watch_score") or 0)
        bucket = "watch_80+" if watch >= 80 else "watch_60_79" if watch >= 60 else "watch_40_59" if watch >= 40 else "watch_0_39"

        for stats in (by_label[label], by_use[use], by_venue[venue], by_watch_bucket[bucket]):
            add_row_stats(stats, row, outcome, high_threshold, super_high_threshold)

    return (
        {k: finalize_stats(v) for k, v in by_label.items()},
        {k: finalize_stats(v) for k, v in by_use.items()},
        {k: finalize_stats(v) for k, v in by_venue.items()},
        {k: finalize_stats(v) for k, v in by_watch_bucket.items()},
    )


def pct(value: float) -> str:
    return f"{value:.1f}%"


def table_rows(group: dict[str, dict[str, Any]], min_races: int = 1, limit: int | None = None) -> list[str]:
    items = [(k, v) for k, v in group.items() if v["races"] >= min_races]
    items.sort(key=lambda item: (-item[1]["high_wide_rate"], -item[1]["races"], item[0]))
    if limit:
        items = items[:limit]
    rows = []
    for key, s in items:
        rows.append(
            f"| {key} | {s['races']:,} | {s['with_outcome']:,} | "
            f"{s['hole_horses']:,} | {pct(s['hole_top3_rate'])} | "
            f"{s['danger_horses']:,} | {pct(s['danger_miss_rate'])} | "
            f"{s['avg_max_wide']:.0f} | {pct(s['high_wide_rate'])} | {pct(s['super_high_wide_rate'])} | "
            f"{s['avg_watch']:.1f} |"
        )
    return rows


def build_report(
    diagnosis_rows: list[dict[str, Any]],
    race_rows: list[dict[str, Any]],
    by_label: dict[str, dict[str, Any]],
    by_use: dict[str, dict[str, Any]],
    by_venue: dict[str, dict[str, Any]],
    by_watch: dict[str, dict[str, Any]],
    args: argparse.Namespace,
) -> str:
    labels = Counter(row.get("primary_label") or "unknown" for row in diagnosis_rows)
    uses = Counter(row.get("suggested_use") or "unknown" for row in diagnosis_rows)
    lines = [
        f"# 穴党参謀AI レース診断ラベル妥当性検証 {date.today().isoformat()}",
        "",
        f"- diagnosis: `{args.diagnosis}`",
        f"- race_dataset: `{args.race_dataset}`",
        f"- diagnosis rows: {len(diagnosis_rows):,}",
        f"- race rows: {len(race_rows):,}",
        f"- high wide threshold: {args.high_wide}",
        f"- super high wide threshold: {args.super_high_wide}",
        "",
        "## primary_label 件数",
        "",
        "| label | races |",
        "|---|---:|",
        *[f"| {k} | {v:,} |" for k, v in labels.most_common()],
        "",
        "## suggested_use 件数",
        "",
        "| suggested_use | races |",
        "|---|---:|",
        *[f"| {k} | {v:,} |" for k, v in uses.most_common()],
        "",
        "## primary_label別",
        "",
        "| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *table_rows(by_label),
        "",
        "## suggested_use別",
        "",
        "| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *table_rows(by_use),
        "",
        "## watch_score帯別",
        "",
        "| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *table_rows(by_watch),
        "",
        "## 競馬場別 top20",
        "",
        "| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *table_rows(by_venue, min_races=args.min_venue_races, limit=20),
        "",
        "## 読み方",
        "",
        "- `hole_top3`: AI穴馬がワイド払戻から推定した3着内に入った率。",
        "- `danger_miss`: 危険人気馬が推定3着内に入らなかった率。高いほど診断としては良い。",
        "- `high_wide`: レース内の最大ワイド払戻が閾値以上だった率。",
        "- この検証は買い目ROIではなく、診断コンテンツとして意味があるかを見るもの。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest Anatou race diagnosis labels")
    parser.add_argument("--diagnosis", required=True, help="diagnosis JSONL")
    parser.add_argument("--race-dataset", required=True, help="race-level wide_rebirth JSONL")
    parser.add_argument("--out", default="", help="output markdown report")
    parser.add_argument("--high-wide", type=int, default=1000)
    parser.add_argument("--super-high-wide", type=int, default=3000)
    parser.add_argument("--min-venue-races", type=int, default=20)
    args = parser.parse_args()

    diagnosis_path = Path(args.diagnosis)
    race_path = Path(args.race_dataset)
    diagnosis_rows = load_jsonl(diagnosis_path)
    race_rows = load_jsonl(race_path)
    outcomes = build_outcome_index(race_rows)
    by_label, by_use, by_venue, by_watch = grouped_stats(
        diagnosis_rows,
        outcomes,
        args.high_wide,
        args.super_high_wide,
    )
    report = build_report(diagnosis_rows, race_rows, by_label, by_use, by_venue, by_watch, args)
    out_path = Path(args.out) if args.out else DOCS_DIR / f"anatou_race_diagnosis_backtest_{date.today().strftime('%Y%m%d')}_{diagnosis_path.stem}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[report] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
