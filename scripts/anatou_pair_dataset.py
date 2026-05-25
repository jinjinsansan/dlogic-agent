#!/usr/bin/env python3
"""Build Anatou wide-pair datasets from race-level wide_rebirth JSONL.

This script does not call or modify backend engines. It consumes existing
race-level JSONL and expands every possible wide pair into one record.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def pair_key(a: int, b: int) -> str:
    x, y = sorted((a, b))
    return f"{x}-{y}"


def parse_pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    a = safe_int(value[0])
    b = safe_int(value[1])
    if a is None or b is None or a == b:
        return None
    return tuple(sorted((a, b)))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def get_popularity(record: dict[str, Any]) -> dict[int, int]:
    raw = ((record.get("odds") or {}).get("popularity") or {})
    out: dict[int, int] = {}
    for key, value in raw.items():
        horse = safe_int(key)
        pop = safe_int(value)
        if horse is not None and pop is not None:
            out[horse] = pop
    return out


def get_horses(record: dict[str, Any]) -> list[int]:
    horses: set[int] = set()
    for payload in (record.get("engines") or {}).values():
        for horse in payload.get("top") or []:
            num = safe_int(horse)
            if num is not None:
                horses.add(num)
    for entry in (((record.get("result") or {}).get("payouts") or {}).get("wide") or []):
        pair = parse_pair(entry.get("combo"))
        if pair:
            horses.update(pair)
    horses.update(get_popularity(record))
    return sorted(horses)


def get_wide_payouts(record: dict[str, Any]) -> dict[tuple[int, int], int]:
    out: dict[tuple[int, int], int] = {}
    for entry in (((record.get("result") or {}).get("payouts") or {}).get("wide") or []):
        pair = parse_pair(entry.get("combo"))
        payout = safe_int(entry.get("payout")) or 0
        if pair and payout > 0:
            out[pair] = payout
    return out


def engine_rank_maps(record: dict[str, Any]) -> tuple[dict[int, list[str]], dict[int, list[str]], dict[int, int], dict[int, int]]:
    top5_engines: dict[int, list[str]] = {}
    top3_engines: dict[int, list[str]] = {}
    best_rank: dict[int, int] = {}
    rank_sum: dict[int, int] = {}

    for engine in ENGINES:
        payload = (record.get("engines") or {}).get(engine) or {}
        top = [safe_int(h) for h in (payload.get("top") or [])]
        top = [h for h in top if h is not None]
        for idx, horse in enumerate(top[:5], start=1):
            top5_engines.setdefault(horse, []).append(engine)
            best_rank[horse] = min(best_rank.get(horse, idx), idx)
            rank_sum[horse] = rank_sum.get(horse, 0) + idx
            if idx <= 3:
                top3_engines.setdefault(horse, []).append(engine)
    return top5_engines, top3_engines, best_rank, rank_sum


def classify_pair(pop_a: int | None, pop_b: int | None, votes_a: int, votes_b: int, top3_a: int, top3_b: int) -> dict[str, bool]:
    pops = [p for p in (pop_a, pop_b) if p is not None]
    min_pop = min(pops) if pops else None
    max_pop = max(pops) if pops else None
    one_popular = min_pop is not None and min_pop <= 3
    one_hole = max_pop is not None and 5 <= max_pop <= 12
    both_mid = pop_a is not None and pop_b is not None and 4 <= pop_a <= 10 and 4 <= pop_b <= 10
    both_supported = votes_a >= 2 and votes_b >= 2
    one_top3 = top3_a >= 1 or top3_b >= 1
    return {
        "is_popular_axis_pair": bool(one_popular),
        "is_mid_pop_pair": bool(both_mid),
        "is_ai_hole_pair": bool(one_hole and (votes_a >= 2 or votes_b >= 2)),
        "one_popular_one_ai_hole": bool(one_popular and one_hole and (votes_a >= 2 or votes_b >= 2)),
        "both_ai_supported": bool(both_supported),
        "one_top3_one_hole": bool(one_top3 and one_hole),
    }


def build_pair_records(record: dict[str, Any], source_dataset: str) -> list[dict[str, Any]]:
    horses = get_horses(record)
    if len(horses) < 2:
        return []

    popularity = get_popularity(record)
    payouts = get_wide_payouts(record)
    top5_engines, top3_engines, best_rank, rank_sum = engine_rank_maps(record)
    field_size = len(horses)

    rows: list[dict[str, Any]] = []
    for a, b in combinations(horses, 2):
        pair = tuple(sorted((a, b)))
        payout = payouts.get(pair, 0)
        pop_a = popularity.get(a)
        pop_b = popularity.get(b)
        votes_a_top5 = len(top5_engines.get(a, []))
        votes_b_top5 = len(top5_engines.get(b, []))
        votes_a_top3 = len(top3_engines.get(a, []))
        votes_b_top3 = len(top3_engines.get(b, []))
        ranks = [r for r in (best_rank.get(a), best_rank.get(b)) if r is not None]
        pop_values = [p for p in (pop_a, pop_b) if p is not None]
        flags = classify_pair(pop_a, pop_b, votes_a_top5, votes_b_top5, votes_a_top3, votes_b_top3)

        rows.append({
            "schema_version": "anatou_pair_dataset.v1",
            "source_dataset": source_dataset,
            "source": record.get("source"),
            "race_id": record.get("race_id"),
            "date": record.get("date"),
            "race_type": record.get("race_type"),
            "venue": record.get("venue"),
            "race_number": record.get("race_number"),
            "field_size": field_size,
            "horse_a": a,
            "horse_b": b,
            "pair": pair_key(a, b),
            "wide_hit": payout > 0,
            "wide_payout": payout,
            "profit": payout - 100,
            "pop_a": pop_a,
            "pop_b": pop_b,
            "min_pop": min(pop_values) if pop_values else None,
            "max_pop": max(pop_values) if pop_values else None,
            "pop_gap": abs(pop_a - pop_b) if pop_a is not None and pop_b is not None else None,
            "engine_votes_a_top5": votes_a_top5,
            "engine_votes_b_top5": votes_b_top5,
            "engine_votes_a_top3": votes_a_top3,
            "engine_votes_b_top3": votes_b_top3,
            "best_rank_a": best_rank.get(a),
            "best_rank_b": best_rank.get(b),
            "rank_sum": sum(ranks) if len(ranks) == 2 else None,
            "rank_sum_all_engines": rank_sum.get(a, 0) + rank_sum.get(b, 0),
            "both_in_top5": votes_a_top5 > 0 and votes_b_top5 > 0,
            "both_in_top3": votes_a_top3 > 0 and votes_b_top3 > 0,
            "engines_a": sorted(top5_engines.get(a, [])),
            "engines_b": sorted(top5_engines.get(b, [])),
            **flags,
        })
    return rows


def summarize(rows: list[dict[str, Any]], race_count: int) -> dict[str, Any]:
    by_type = Counter(row.get("race_type") or "unknown" for row in rows)
    by_venue = Counter(row.get("venue") or "unknown" for row in rows)
    by_month = Counter(str(row.get("date") or "")[:7] for row in rows)
    hits = sum(1 for row in rows if row.get("wide_hit"))
    payout = sum(safe_int(row.get("wide_payout")) or 0 for row in rows)
    return {
        "races": race_count,
        "pairs": len(rows),
        "hits": hits,
        "hit_rate": hits / len(rows) * 100 if rows else 0.0,
        "roi": payout / (len(rows) * 100) * 100 if rows else 0.0,
        "by_type": by_type,
        "by_venue": by_venue,
        "by_month": by_month,
        "flags": {
            "one_popular_one_ai_hole": sum(1 for r in rows if r.get("one_popular_one_ai_hole")),
            "both_ai_supported": sum(1 for r in rows if r.get("both_ai_supported")),
            "one_top3_one_hole": sum(1 for r in rows if r.get("one_top3_one_hole")),
            "is_mid_pop_pair": sum(1 for r in rows if r.get("is_mid_pop_pair")),
        },
    }


def counter_table(counter: Counter[Any], limit: int = 20) -> list[str]:
    return [f"| {key} | {value:,} |" for key, value in counter.most_common(limit)]


def build_report(summary: dict[str, Any], input_path: Path, output_path: Path) -> str:
    flags = summary["flags"]
    lines = [
        f"# 穴党参謀AI ワイドペアデータセット作成 {date.today().isoformat()}",
        "",
        f"- input: `{input_path}`",
        f"- output: `{output_path}`",
        "",
        "## 件数",
        "",
        f"- races: {summary['races']:,}",
        f"- pairs: {summary['pairs']:,}",
        f"- wide hits: {summary['hits']:,}",
        f"- hit rate: {summary['hit_rate']:.1f}%",
        f"- all-pair ROI: {summary['roi']:.1f}%",
        "",
        "## 初期フラグ件数",
        "",
        f"- one_popular_one_ai_hole: {flags['one_popular_one_ai_hole']:,}",
        f"- both_ai_supported: {flags['both_ai_supported']:,}",
        f"- one_top3_one_hole: {flags['one_top3_one_hole']:,}",
        f"- is_mid_pop_pair: {flags['is_mid_pop_pair']:,}",
        "",
        "## race_type",
        "",
        "| race_type | pairs |",
        "|---|---:|",
        *counter_table(summary["by_type"]),
        "",
        "## month",
        "",
        "| month | pairs |",
        "|---|---:|",
        *counter_table(summary["by_month"]),
        "",
        "## venue top20",
        "",
        "| venue | pairs |",
        "|---|---:|",
        *counter_table(summary["by_venue"], limit=20),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build wide-pair JSONL from race-level wide_rebirth JSONL")
    parser.add_argument("--input", required=True, help="race-level JSONL")
    parser.add_argument("--out", default="", help="output pair JSONL")
    parser.add_argument("--report", default="", help="output markdown report")
    args = parser.parse_args()

    input_path = Path(args.input)
    records = load_jsonl(input_path)
    source_dataset = str(input_path)

    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(build_pair_records(record, source_dataset))

    out_path = Path(args.out) if args.out else DATA_DIR / f"anatou_pair_dataset_{input_path.stem}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = summarize(rows, race_count=len(records))
    report = build_report(summary, input_path, out_path)
    report_path = Path(args.report) if args.report else DOCS_DIR / f"anatou_pair_dataset_build_{date.today().strftime('%Y%m%d')}_{input_path.stem}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[dataset] {out_path}")
    print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
