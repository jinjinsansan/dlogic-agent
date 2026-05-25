#!/usr/bin/env python3
"""Format Anatou race diagnosis rows into a daily preview.

This script only reads diagnosis JSONL files and writes preview artifacts.
It does not call or modify backend engines.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"

LABEL_JA = {
    "market_gap": "荒れ警戒",
    "hole_candidate": "AI穴馬候補",
    "ai_consensus": "AI一致",
    "ai_low_rated_popular": "AI低評価人気",
    "low_priority": "低優先度",
    "skip": "低優先度",
    "watch": "注目",
    "volatile": "混戦",
    "solid": "堅実寄り",
}

USE_JA = {
    "ai_low_rated_popular_check": "人気馬の過信注意",
    "hole_check": "AI穴馬チェック",
    "solid_reference": "堅実寄りの参考",
    "forward_watch": "経過観察",
    "low_priority": "低優先度",
    "skip": "低優先度",
    "read_only": "参考",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                row["_source_file"] = str(path)
                rows.append(row)
    return rows


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def race_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("date") or ""),
        str(row.get("venue") or ""),
        safe_int(row.get("race_number")),
    )


def rank_key(row: dict[str, Any]) -> tuple[float, float, int, int]:
    return (
        safe_float(row.get("watch_score")),
        safe_float(row.get("market_gap_score")),
        safe_int(row.get("hole_candidate_count")),
        safe_int(row.get("danger_popular_count")),
    )


def race_title(row: dict[str, Any]) -> str:
    date = row.get("date")
    prefix = f"{date} " if date else ""
    return f"{prefix}{row.get('venue')}{row.get('race_number')}R"


def label_text(row: dict[str, Any]) -> str:
    primary = str(row.get("primary_label") or "")
    return LABEL_JA.get(primary, primary or "診断")


def use_text(row: dict[str, Any]) -> str:
    use = str(row.get("suggested_use") or "")
    return USE_JA.get(use, use or "参考")


def horse_line(items: list[dict[str, Any]], limit: int = 2) -> str:
    parts = []
    for item in items[:limit]:
        horse = item.get("horse")
        pop = item.get("popularity")
        votes = item.get("top5_votes")
        if horse is None:
            continue
        if pop is None:
            parts.append(f"{horse}番(AI{votes}基)")
        else:
            parts.append(f"{horse}番({pop}人気/AI{votes}基)")
    return "、".join(parts)


def diagnosis_reason(row: dict[str, Any]) -> str:
    pieces = []
    holes = row.get("ai_hole_horses") or []
    low_popular = row.get("danger_popular_horses") or []
    consensus = row.get("consensus_horses") or []
    if holes:
        pieces.append(f"AI穴: {horse_line(holes)}")
    if low_popular:
        pieces.append(f"過信注意: {horse_line(low_popular)}")
    if consensus:
        pieces.append(f"AI中心: {horse_line(consensus, 1)}")
    if not pieces:
        pieces.append(str(row.get("summary_text") or "特徴は薄め"))
    return " / ".join(pieces)


def split_sections(rows: list[dict[str, Any]], limit: int) -> dict[str, list[dict[str, Any]]]:
    usable = [r for r in rows if str(r.get("primary_label")) not in {"skip", "low_priority"}]
    attention = [
        r for r in usable
        if r.get("primary_label") in {"market_gap", "hole_candidate"}
        or r.get("suggested_use") in {"ai_low_rated_popular_check", "hole_check"}
    ]
    attention.sort(key=rank_key, reverse=True)

    low_popular = [r for r in usable if r.get("danger_popular_horses")]
    low_popular.sort(key=rank_key, reverse=True)

    holes = [r for r in usable if r.get("ai_hole_horses")]
    holes.sort(key=lambda r: (safe_int(r.get("hole_candidate_count")), *rank_key(r)), reverse=True)

    consensus = [r for r in usable if r.get("primary_label") == "ai_consensus"]
    consensus.sort(key=lambda r: (safe_float(r.get("ai_consensus_score")), safe_float(r.get("watch_score"))), reverse=True)

    low_priority = [r for r in rows if str(r.get("primary_label")) in {"skip", "low_priority"}]
    low_priority.sort(key=race_key)

    return {
        "attention": attention[:limit],
        "low_popular": low_popular[:limit],
        "holes": holes[:limit],
        "consensus": consensus[: max(3, limit // 2)],
        "low_priority": low_priority,
    }


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "race_id": row.get("race_id"),
        "date": row.get("date"),
        "race_type": row.get("race_type"),
        "venue": row.get("venue"),
        "race_number": row.get("race_number"),
        "primary_label": row.get("primary_label"),
        "label_text": label_text(row),
        "suggested_use": row.get("suggested_use"),
        "use_text": use_text(row),
        "watch_score": row.get("watch_score"),
        "market_gap_score": row.get("market_gap_score"),
        "ai_hole_horses": row.get("ai_hole_horses") or [],
        "ai_low_rated_popular_horses": row.get("danger_popular_horses") or [],
        "consensus_horses": row.get("consensus_horses") or [],
        "reason": diagnosis_reason(row),
    }


def build_payload(rows: list[dict[str, Any]], input_paths: list[Path], date_filter: str, limit: int) -> dict[str, Any]:
    sections = split_sections(rows, limit)
    labels = Counter(str(row.get("primary_label") or "unknown") for row in rows)
    uses = Counter(str(row.get("suggested_use") or "unknown") for row in rows)
    by_type = Counter(str(row.get("race_type") or "unknown") for row in rows)
    by_venue = Counter(str(row.get("venue") or "unknown") for row in rows)

    return {
        "schema_version": "anatou_today_diagnosis_preview.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date_filter": date_filter,
        "source_files": [str(path) for path in input_paths],
        "total_races": len(rows),
        "counts": {
            "by_label": dict(labels),
            "by_use": dict(uses),
            "by_type": dict(by_type),
            "by_venue": dict(by_venue),
            "low_priority_count": len(sections["low_priority"]),
        },
        "sections": {
            key: [compact_row(row) for row in value]
            for key, value in sections.items()
            if key != "low_priority"
        },
        "low_priority_races": [compact_row(row) for row in sections["low_priority"]],
    }


def section_lines(title: str, rows: list[dict[str, Any]], empty_text: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        lines.extend([empty_text, ""])
        return lines
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"{idx}. {race_title(row)} {label_text(row)} / {use_text(row)} "
            f"(watch {safe_float(row.get('watch_score')):.1f}, gap {safe_float(row.get('market_gap_score')):.1f})"
        )
        lines.append(f"   - {diagnosis_reason(row)}")
    lines.append("")
    return lines


def build_markdown(payload: dict[str, Any]) -> str:
    rows_by_section = payload["sections"]
    low_priority = payload["low_priority_races"]
    counts = payload["counts"]
    lines = [
        "# 穴党参謀AI 本日のレース診断プレビュー",
        "",
        "これは購入推奨ではなく、AIによるレース診断のフォワード検証用プレビューです。",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- date_filter: `{payload['date_filter'] or 'all'}`",
        f"- total_races: {payload['total_races']:,}",
        f"- low_priority: {counts['low_priority_count']:,}",
        "",
        "## サマリ",
        "",
        "| item | count |",
        "|---|---:|",
    ]
    for key, value in counts["by_label"].items():
        lines.append(f"| label:{LABEL_JA.get(key, key)} | {value:,} |")
    lines.extend([
        "",
        *section_lines("今日見るべきレース", rows_by_section.get("attention", []), "強い注目レースはありません。"),
        *section_lines("AI穴馬候補", rows_by_section.get("holes", []), "AI穴馬候補はありません。"),
        *section_lines("AI低評価人気", rows_by_section.get("low_popular", []), "AI低評価人気はありません。"),
        *section_lines("AI一致レース", rows_by_section.get("consensus", []), "AI一致レースはありません。"),
        "## 低優先度レース",
        "",
    ])
    if low_priority:
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in low_priority:
            grouped[str(row.get("venue") or "unknown")].append(f"{row.get('date')} {row.get('race_number')}R")
        for venue, races in sorted(grouped.items()):
            shown = ", ".join(races[:12])
            suffix = f" ... 他{len(races) - 12}件" if len(races) > 12 else ""
            lines.append(f"- {venue}: {len(races)}件 ({shown}{suffix})")
    else:
        lines.append("低優先度レースはありません。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Anatou daily diagnosis preview")
    parser.add_argument("--input", action="append", required=True, help="diagnosis JSONL. Can be specified multiple times")
    parser.add_argument("--date", default="", help="filter date. Accepts YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--limit", type=int, default=10, help="max races per section")
    parser.add_argument("--out-md", default="", help="output markdown path")
    parser.add_argument("--out-json", default="", help="output json path")
    args = parser.parse_args()

    input_paths = [Path(value) for value in args.input]
    rows = [row for path in input_paths for row in load_jsonl(path)]
    if args.date:
        normalized = args.date[:4] + "-" + args.date[4:6] + "-" + args.date[6:8] if len(args.date) == 8 else args.date
        rows = [row for row in rows if str(row.get("date") or "") == normalized]
    else:
        normalized = ""
    rows.sort(key=race_key)

    payload = build_payload(rows, input_paths, normalized, args.limit)
    markdown = build_markdown(payload)

    suffix = normalized.replace("-", "") if normalized else "sample"
    md_path = Path(args.out_md) if args.out_md else DOCS_DIR / f"anatou_today_diagnosis_preview_{suffix}.md"
    json_path = Path(args.out_json) if args.out_json else DATA_DIR / f"anatou_today_diagnosis_preview_{suffix}.json"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(markdown)
    print(f"\n[markdown] {md_path}")
    print(f"[json] {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
