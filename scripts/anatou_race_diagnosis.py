#!/usr/bin/env python3
"""Build race-level diagnosis records for Anatou AI.

This is a content/decision-support layer. It does not modify backend engines
or produce purchase recommendations.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")
NAR_FOCUS_VENUES = {"大井", "船橋", "名古屋", "帯広"}


def diagnosis_rules(record: dict[str, Any], profile: str) -> dict[str, Any]:
    if profile != "v2":
        return {
            "min_pop": 5,
            "max_pop": 99,
            "min_top5": 2,
            "min_gap": 0.0,
            "require_top3_or_top1": False,
            "market_gap_threshold": 45,
            "watch_threshold": 55,
            "low_priority_threshold": 35,
            "skip_threshold": 35,
        }

    race_type = str(record.get("race_type") or "").lower()
    venue = str(record.get("venue") or "")
    if race_type == "nar":
        rules = {
            "min_pop": 5,
            "max_pop": 11,
            "min_top5": 4,
            "min_gap": 4.0,
            "require_top3_or_top1": True,
            "market_gap_threshold": 70,
            "watch_threshold": 75,
            "low_priority_threshold": 60,
            "skip_threshold": 45,
        }
        if venue in {"大井", "船橋", "名古屋"}:
            rules.update({
                "max_pop": 12,
                "min_top5": 3,
                "min_gap": 3.0,
                "market_gap_threshold": 55,
                "watch_threshold": 70,
            })
        elif venue == "帯広":
            rules.update({
                "max_pop": 12,
                "min_top5": 3,
                "min_gap": 2.5,
                "market_gap_threshold": 55,
                "watch_threshold": 70,
            })
        return rules

    return {
        "min_pop": 5,
        "max_pop": 12,
        "min_top5": 3,
        "min_gap": 3.0,
        "require_top3_or_top1": True,
        "market_gap_threshold": 55,
        "watch_threshold": 70,
        "low_priority_threshold": 60,
        "skip_threshold": 45,
    }


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def get_popularity(record: dict[str, Any]) -> dict[int, int]:
    raw = ((record.get("odds") or {}).get("popularity") or {})
    out: dict[int, int] = {}
    for key, value in raw.items():
        horse = safe_int(key)
        pop = safe_int(value)
        if horse is not None and pop is not None:
            out[horse] = pop
    return out


def engine_support(record: dict[str, Any]) -> dict[int, dict[str, Any]]:
    support: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "top5_votes": 0,
        "top3_votes": 0,
        "top1_votes": 0,
        "best_rank": None,
        "rank_sum": 0,
        "engines": [],
        "top3_engines": [],
        "top1_engines": [],
    })
    for engine in ENGINES:
        payload = (record.get("engines") or {}).get(engine) or {}
        top = [safe_int(h) for h in (payload.get("top") or [])]
        top = [h for h in top if h is not None]
        for idx, horse in enumerate(top[:5], start=1):
            item = support[horse]
            item["top5_votes"] += 1
            item["rank_sum"] += idx
            item["engines"].append(engine)
            item["best_rank"] = idx if item["best_rank"] is None else min(item["best_rank"], idx)
            if idx <= 3:
                item["top3_votes"] += 1
                item["top3_engines"].append(engine)
            if idx == 1:
                item["top1_votes"] += 1
                item["top1_engines"].append(engine)
    return support


def all_horses(record: dict[str, Any], support: dict[int, dict[str, Any]], popularity: dict[int, int]) -> list[int]:
    horses = set(support) | set(popularity)
    for entry in (((record.get("result") or {}).get("payouts") or {}).get("wide") or []):
        combo = entry.get("combo") or []
        for value in combo:
            horse = safe_int(value)
            if horse is not None:
                horses.add(horse)
    return sorted(horses)


def ranked_support(support: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for horse, item in support.items():
        rows.append({
            "horse": horse,
            **item,
        })
    rows.sort(key=lambda r: (-r["top5_votes"], -r["top3_votes"], r["best_rank"] or 99, r["horse"]))
    return rows


def ai_hole_horses(
    support: dict[int, dict[str, Any]],
    popularity: dict[int, int],
    profile: str,
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for horse, item in support.items():
        pop = popularity.get(horse)
        if pop is None:
            continue
        if profile == "v2":
            top5_votes = item["top5_votes"]
            avg_rank = item["rank_sum"] / top5_votes if top5_votes else 99.0
            popularity_gap = pop - avg_rank
            vote_condition = top5_votes >= rules["min_top5"]
            rank_condition = (item["top3_votes"] >= 2 or item["top1_votes"] >= 1)
            matched = (
                rules["min_pop"] <= pop <= rules["max_pop"]
                and vote_condition
                and popularity_gap >= rules["min_gap"]
                and (rank_condition or not rules["require_top3_or_top1"])
            )
        else:
            avg_rank = item["rank_sum"] / item["top5_votes"] if item["top5_votes"] else 99.0
            popularity_gap = pop - avg_rank
            matched = pop >= 5 and item["top5_votes"] >= 2
        if matched:
            rows.append({
                "horse": horse,
                "popularity": pop,
                "top5_votes": item["top5_votes"],
                "top3_votes": item["top3_votes"],
                "top1_votes": item["top1_votes"],
                "best_rank": item["best_rank"],
                "avg_rank": round(avg_rank, 2),
                "popularity_gap": round(popularity_gap, 2),
                "engines": sorted(item["engines"]),
            })
    rows.sort(key=lambda r: (-r["top5_votes"], -r["top3_votes"], -r["popularity_gap"], r["popularity"], r["horse"]))
    return rows


def danger_popular_horses(support: dict[int, dict[str, Any]], popularity: dict[int, int], profile: str) -> list[dict[str, Any]]:
    rows = []
    for horse, pop in popularity.items():
        if pop > 3:
            continue
        item = support.get(horse, {})
        top5_votes = safe_int(item.get("top5_votes")) or 0
        top3_votes = safe_int(item.get("top3_votes")) or 0
        if profile == "v2":
            matched = top5_votes == 0
        else:
            matched = top5_votes <= 1 and top3_votes == 0
        if matched:
            rows.append({
                "horse": horse,
                "popularity": pop,
                "top5_votes": top5_votes,
                "top3_votes": top3_votes,
                "engines": sorted(item.get("engines") or []),
            })
    rows.sort(key=lambda r: (r["popularity"], r["top5_votes"], r["horse"]))
    return rows


def consensus_horses(support: dict[int, dict[str, Any]], popularity: dict[int, int]) -> list[dict[str, Any]]:
    rows = []
    for item in ranked_support(support):
        if item["top5_votes"] >= 3 or item["top3_votes"] >= 2:
            horse = item["horse"]
            rows.append({
                "horse": horse,
                "popularity": popularity.get(horse),
                "top5_votes": item["top5_votes"],
                "top3_votes": item["top3_votes"],
                "top1_votes": item["top1_votes"],
                "best_rank": item["best_rank"],
                "engines": sorted(item["engines"]),
            })
    return rows


def score_record(record: dict[str, Any], profile: str) -> dict[str, Any]:
    rules = diagnosis_rules(record, profile)
    popularity = get_popularity(record)
    support = engine_support(record)
    horses = all_horses(record, support, popularity)
    field_size = len(horses)
    supported = ranked_support(support)
    consensus = consensus_horses(support, popularity)
    holes = ai_hole_horses(support, popularity, profile, rules)
    dangers = danger_popular_horses(support, popularity, profile)

    max_votes = max((row["top5_votes"] for row in supported), default=0)
    max_top3 = max((row["top3_votes"] for row in supported), default=0)
    unique_top5 = len(supported)
    engine_count = safe_int(record.get("engine_count")) or len(record.get("engines") or {})
    top1_unique = len({row["horse"] for row in supported if row["top1_votes"] > 0})

    ai_consensus_score = clamp(max_votes * 18 + max_top3 * 8 + (10 if len(consensus) <= 3 and consensus else 0))
    ai_disagreement_score = clamp(unique_top5 * 5 + top1_unique * 12 - max_votes * 8)
    if profile == "v2":
        market_gap_score = clamp(len(holes) * 26 + len(dangers) * 10)
        volatility_score = clamp(ai_disagreement_score * 0.50 + market_gap_score * 0.50)
        watch_score = clamp(market_gap_score * 0.50 + ai_consensus_score * 0.20 + volatility_score * 0.30)
    else:
        market_gap_score = clamp(len(holes) * 18 + len(dangers) * 16)
        volatility_score = clamp(ai_disagreement_score * 0.45 + market_gap_score * 0.55)
        watch_score = clamp(market_gap_score * 0.45 + ai_consensus_score * 0.25 + volatility_score * 0.30)

    labels: list[str] = []
    if ai_consensus_score >= 65:
        labels.append("ai_consensus")
    if ai_disagreement_score >= 60:
        labels.append("ai_disagreement")
    if market_gap_score >= rules["market_gap_threshold"]:
        labels.append("market_gap")
    if holes:
        labels.append("hole_candidate")
    if dangers:
        labels.append("ai_low_rated_popular")
    if volatility_score >= 60:
        labels.append("volatile")
    if ai_consensus_score >= 65 and volatility_score < 45:
        labels.append("solid")
    if watch_score >= rules["watch_threshold"]:
        labels.append("watch")

    if profile == "v2":
        if watch_score < rules["low_priority_threshold"] and not holes:
            labels.append("low_priority")
        if watch_score < rules["skip_threshold"] and not holes:
            labels.append("skip")
    elif not labels or (watch_score < 35 and not holes and not dangers):
        labels.append("skip")

    primary_label = choose_primary_label(labels, watch_score, volatility_score, ai_consensus_score, profile)
    suggested_use = choose_suggested_use(labels, holes, dangers, watch_score, profile)

    return {
        "schema_version": f"anatou_race_diagnosis.{profile}",
        "source_dataset": record.get("source"),
        "race_id": record.get("race_id"),
        "date": record.get("date"),
        "race_type": record.get("race_type"),
        "venue": record.get("venue"),
        "race_number": record.get("race_number"),
        "field_size": field_size,
        "engine_count": engine_count,
        "has_nlogic": bool(record.get("has_nlogic")),
        "diagnosis_rules": {
            "focus_venue": str(record.get("venue") or "") in NAR_FOCUS_VENUES,
            "min_pop": rules["min_pop"],
            "max_pop": rules["max_pop"],
            "min_top5": rules["min_top5"],
            "min_gap": rules["min_gap"],
            "market_gap_threshold": rules["market_gap_threshold"],
            "watch_threshold": rules["watch_threshold"],
            "skip_threshold": rules["skip_threshold"],
        },
        "ai_consensus_score": round(ai_consensus_score, 1),
        "ai_disagreement_score": round(ai_disagreement_score, 1),
        "market_gap_score": round(market_gap_score, 1),
        "volatility_score": round(volatility_score, 1),
        "watch_score": round(watch_score, 1),
        "hole_candidate_count": len(holes),
        "danger_popular_count": len(dangers),
        "primary_label": primary_label,
        "labels": labels,
        "suggested_use": suggested_use,
        "consensus_horses": consensus[:5],
        "ai_hole_horses": holes[:5],
        "danger_popular_horses": dangers[:5],
        "top_support_horses": supported[:8],
        "summary_text": make_summary_text(record, primary_label, suggested_use, holes, dangers, consensus, profile),
    }


def choose_primary_label(labels: list[str], watch_score: float, volatility_score: float, consensus_score: float, profile: str) -> str:
    low_popular_label = "ai_low_rated_popular" if profile == "v2" else "danger_popular"
    if "skip" in labels:
        return "skip"
    if "low_priority" in labels and "hole_candidate" not in labels:
        return "low_priority"
    if low_popular_label in labels and "hole_candidate" in labels:
        return "market_gap"
    if low_popular_label in labels:
        return low_popular_label
    if "hole_candidate" in labels and volatility_score >= 50:
        return "hole_candidate"
    if "ai_consensus" in labels and consensus_score >= 70:
        return "ai_consensus"
    if "volatile" in labels:
        return "volatile"
    if watch_score >= 55:
        return "watch"
    return "skip"


def choose_suggested_use(labels: list[str], holes: list[dict[str, Any]], dangers: list[dict[str, Any]], watch_score: float, profile: str) -> str:
    if "skip" in labels and watch_score < 35:
        return "skip"
    if profile == "v2" and "low_priority" in labels and not holes:
        return "low_priority"
    if dangers:
        return "ai_low_rated_popular_check" if profile == "v2" else "danger_popular_check"
    if holes:
        return "hole_check"
    if "ai_consensus" in labels:
        return "solid_reference"
    if watch_score >= 55:
        return "forward_watch"
    return "read_only"


def make_summary_text(
    record: dict[str, Any],
    primary_label: str,
    suggested_use: str,
    holes: list[dict[str, Any]],
    dangers: list[dict[str, Any]],
    consensus: list[dict[str, Any]],
    profile: str,
) -> str:
    venue = record.get("venue")
    race_number = record.get("race_number")
    parts = [f"{venue}{race_number}R", f"診断={primary_label}", f"用途={suggested_use}"]
    if holes:
        h = holes[0]
        parts.append(f"AI穴馬 {h['horse']}番({h['popularity']}人気, {h['top5_votes']}基支持)")
    if dangers:
        d = dangers[0]
        label = "AI低評価人気" if profile == "v2" else "危険人気"
        parts.append(f"{label} {d['horse']}番({d['popularity']}人気, AI支持{d['top5_votes']}基)")
    if consensus:
        c = consensus[0]
        parts.append(f"AI中心 {c['horse']}番({c['top5_votes']}基支持)")
    return " / ".join(parts)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_label = Counter(row["primary_label"] for row in rows)
    by_use = Counter(row["suggested_use"] for row in rows)
    by_type = Counter(row.get("race_type") or "unknown" for row in rows)
    by_venue = Counter(row.get("venue") or "unknown" for row in rows)
    return {
        "rows": len(rows),
        "by_label": by_label,
        "by_use": by_use,
        "by_type": by_type,
        "by_venue": by_venue,
        "watch_count": sum(1 for row in rows if "watch" in row.get("labels", [])),
        "hole_count": sum(1 for row in rows if row.get("hole_candidate_count", 0) > 0),
        "danger_count": sum(1 for row in rows if row.get("danger_popular_count", 0) > 0),
    }


def counter_table(counter: Counter[Any], limit: int = 30) -> list[str]:
    return [f"| {key} | {value:,} |" for key, value in counter.most_common(limit)]


def build_report(rows: list[dict[str, Any]], summary: dict[str, Any], input_path: Path, output_path: Path, sample_limit: int) -> str:
    samples = sorted(rows, key=lambda r: (-float(r.get("watch_score") or 0), -float(r.get("market_gap_score") or 0)))[:sample_limit]
    lines = [
        f"# 穴党参謀AI レース診断データセット作成 {date.today().isoformat()}",
        "",
        f"- input: `{input_path}`",
        f"- output: `{output_path}`",
        f"- records: {summary['rows']:,}",
        f"- watch labels: {summary['watch_count']:,}",
        f"- with AI holes: {summary['hole_count']:,}",
        f"- with danger popular: {summary['danger_count']:,}",
        "",
        "## primary_label",
        "",
        "| label | races |",
        "|---|---:|",
        *counter_table(summary["by_label"]),
        "",
        "## suggested_use",
        "",
        "| suggested_use | races |",
        "|---|---:|",
        *counter_table(summary["by_use"]),
        "",
        "## race_type",
        "",
        "| race_type | races |",
        "|---|---:|",
        *counter_table(summary["by_type"]),
        "",
        "## venue top30",
        "",
        "| venue | races |",
        "|---|---:|",
        *counter_table(summary["by_venue"], 30),
        "",
        "## watch_score上位サンプル",
        "",
        "| race | label | use | watch | gap | holes | dangers | summary |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in samples:
        race = f"{row.get('date')} {row.get('venue')}{row.get('race_number')}R"
        lines.append(
            f"| {race} | {row['primary_label']} | {row['suggested_use']} | "
            f"{row['watch_score']:.1f} | {row['market_gap_score']:.1f} | "
            f"{row['hole_candidate_count']} | {row['danger_popular_count']} | {row['summary_text']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Anatou race diagnosis JSONL")
    parser.add_argument("--input", required=True, help="race-level wide_rebirth JSONL")
    parser.add_argument("--out", default="", help="output diagnosis JSONL")
    parser.add_argument("--report", default="", help="output markdown report")
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--profile", choices=("v1", "v2"), default="v2", help="diagnosis rule profile")
    args = parser.parse_args()

    input_path = Path(args.input)
    records = load_jsonl(input_path)
    rows = [score_record(record, args.profile) for record in records]
    rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("venue") or ""), int(r.get("race_number") or 0)))

    out_path = Path(args.out) if args.out else DATA_DIR / f"anatou_race_diagnosis_{input_path.stem}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = summarize(rows)
    report = build_report(rows, summary, input_path, out_path, args.sample_limit)
    report_path = Path(args.report) if args.report else DOCS_DIR / f"anatou_race_diagnosis_build_{date.today().strftime('%Y%m%d')}_{input_path.stem}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[dataset] {out_path}")
    print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
