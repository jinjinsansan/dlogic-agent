#!/usr/bin/env python3
"""Condition backtest for Anatou wide-pair datasets."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"


@dataclass(frozen=True)
class Bet:
    condition: str
    race_id: str
    date: str
    race_type: str
    venue: str
    pair: str
    payout: int

    @property
    def profit(self) -> int:
        return self.payout - 100


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


def pop(row: dict[str, Any], key: str) -> int | None:
    return safe_int(row.get(key))


def votes(row: dict[str, Any], key: str) -> int:
    return safe_int(row.get(key)) or 0


def rank(row: dict[str, Any], key: str) -> int | None:
    return safe_int(row.get(key))


def field_size(row: dict[str, Any]) -> int:
    return safe_int(row.get("field_size")) or 0


def is_popular_axis_ai_hole(row: dict[str, Any]) -> bool:
    return (
        bool(row.get("one_popular_one_ai_hole"))
        and (votes(row, "engine_votes_a_top5") >= 2 or votes(row, "engine_votes_b_top5") >= 2)
        and field_size(row) >= 8
    )


def is_popular_axis_ai_hole_strict(row: dict[str, Any]) -> bool:
    min_pop = pop(row, "min_pop")
    max_pop = pop(row, "max_pop")
    return (
        min_pop is not None
        and max_pop is not None
        and min_pop <= 2
        and 6 <= max_pop <= 12
        and (votes(row, "engine_votes_a_top5") >= 3 or votes(row, "engine_votes_b_top5") >= 3)
        and field_size(row) >= 9
    )


def is_multi_engine_mid_hole(row: dict[str, Any]) -> bool:
    min_pop = pop(row, "min_pop")
    max_pop = pop(row, "max_pop")
    return (
        min_pop is not None
        and max_pop is not None
        and 4 <= min_pop <= 10
        and 4 <= max_pop <= 12
        and (votes(row, "engine_votes_a_top5") + votes(row, "engine_votes_b_top5")) >= 4
        and field_size(row) >= 8
    )


def is_both_ai_supported(row: dict[str, Any]) -> bool:
    return (
        votes(row, "engine_votes_a_top5") >= 2
        and votes(row, "engine_votes_b_top5") >= 2
        and field_size(row) >= 8
    )


def is_both_ai_supported_top3(row: dict[str, Any]) -> bool:
    return (
        votes(row, "engine_votes_a_top3") >= 1
        and votes(row, "engine_votes_b_top3") >= 1
        and votes(row, "engine_votes_a_top5") >= 2
        and votes(row, "engine_votes_b_top5") >= 2
        and field_size(row) >= 8
    )


def is_one_top3_one_hole(row: dict[str, Any]) -> bool:
    max_pop = pop(row, "max_pop")
    return (
        max_pop is not None
        and 5 <= max_pop <= 12
        and (votes(row, "engine_votes_a_top3") >= 1 or votes(row, "engine_votes_b_top3") >= 1)
        and (votes(row, "engine_votes_a_top5") >= 2 or votes(row, "engine_votes_b_top5") >= 2)
        and field_size(row) >= 8
    )


def is_ai_hole_pair(row: dict[str, Any]) -> bool:
    min_pop = pop(row, "min_pop")
    max_pop = pop(row, "max_pop")
    return (
        min_pop is not None
        and max_pop is not None
        and 5 <= min_pop <= 12
        and 5 <= max_pop <= 14
        and votes(row, "engine_votes_a_top5") >= 1
        and votes(row, "engine_votes_b_top5") >= 1
        and (votes(row, "engine_votes_a_top5") + votes(row, "engine_votes_b_top5")) >= 3
        and field_size(row) >= 8
    )


def is_low_value_popular_pair(row: dict[str, Any]) -> bool:
    max_pop = pop(row, "max_pop")
    return (
        max_pop is not None
        and max_pop <= 3
        and votes(row, "engine_votes_a_top5") >= 1
        and votes(row, "engine_votes_b_top5") >= 1
    )


def is_rank_sum_good(row: dict[str, Any]) -> bool:
    rs = rank(row, "rank_sum")
    max_pop = pop(row, "max_pop")
    return (
        rs is not None
        and rs <= 5
        and max_pop is not None
        and max_pop >= 4
        and field_size(row) >= 8
    )


CONDITIONS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "popular_axis_ai_hole": is_popular_axis_ai_hole,
    "popular_axis_ai_hole_strict": is_popular_axis_ai_hole_strict,
    "multi_engine_mid_hole": is_multi_engine_mid_hole,
    "both_ai_supported": is_both_ai_supported,
    "both_ai_supported_top3": is_both_ai_supported_top3,
    "one_top3_one_hole": is_one_top3_one_hole,
    "ai_hole_pair": is_ai_hole_pair,
    "low_value_popular_pair": is_low_value_popular_pair,
    "rank_sum_good": is_rank_sum_good,
}


def make_bets(rows: list[dict[str, Any]]) -> dict[str, list[Bet]]:
    grouped: dict[str, list[Bet]] = defaultdict(list)
    for row in rows:
        payout = safe_int(row.get("wide_payout")) or 0
        for name, fn in CONDITIONS.items():
            if not fn(row):
                continue
            grouped[name].append(
                Bet(
                    condition=name,
                    race_id=str(row.get("race_id") or ""),
                    date=str(row.get("date") or ""),
                    race_type=str(row.get("race_type") or "unknown"),
                    venue=str(row.get("venue") or "unknown"),
                    pair=str(row.get("pair") or ""),
                    payout=payout,
                )
            )
    return grouped


def longest_losing_streak(bets: list[Bet]) -> int:
    streak = 0
    best = 0
    for bet in sorted(bets, key=lambda b: (b.date, b.race_id, b.pair)):
        if bet.payout > 0:
            streak = 0
        else:
            streak += 1
            best = max(best, streak)
    return best


def max_drawdown(bets: list[Bet]) -> int:
    equity = 0
    peak = 0
    worst = 0
    for bet in sorted(bets, key=lambda b: (b.date, b.race_id, b.pair)):
        equity += bet.profit
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def bootstrap_ci5(bets: list[Bet], samples: int, seed: int) -> float:
    if not bets or samples <= 0:
        return 0.0
    rng = random.Random(seed)
    payouts = [b.payout for b in bets]
    n = len(payouts)
    values: list[float] = []
    for _ in range(samples):
        total = sum(payouts[rng.randrange(n)] for _ in range(n))
        values.append(total / (n * 100) * 100)
    values.sort()
    idx = max(0, int(samples * 0.05) - 1)
    return values[idx]


def stats(bets: list[Bet], samples: int, seed: int) -> dict[str, Any]:
    n = len(bets)
    payout = sum(b.payout for b in bets)
    hits = sum(1 for b in bets if b.payout > 0)
    payouts = sorted((b.payout for b in bets), reverse=True)
    drop1 = payout - (payouts[0] if payouts else 0)
    drop3 = payout - sum(payouts[:3])
    return {
        "tickets": n,
        "races": len({b.race_id for b in bets}),
        "hits": hits,
        "hit_rate": hits / n * 100 if n else 0.0,
        "roi": payout / (n * 100) * 100 if n else 0.0,
        "ci5": bootstrap_ci5(bets, samples, seed),
        "drop1": drop1 / (n * 100) * 100 if n else 0.0,
        "drop3": drop3 / (n * 100) * 100 if n else 0.0,
        "max_payout": payouts[0] if payouts else 0,
        "longest_losing_streak": longest_losing_streak(bets),
        "max_drawdown": max_drawdown(bets),
    }


def group_by(bets: list[Bet], key: str) -> dict[str, list[Bet]]:
    out: dict[str, list[Bet]] = defaultdict(list)
    for bet in bets:
        if key == "month":
            out[bet.date[:7] or "unknown"].append(bet)
        else:
            out[str(getattr(bet, key))].append(bet)
    return out


def pct(value: float) -> str:
    return f"{value:.1f}%"


def build_report(rows: list[dict[str, Any]], grouped: dict[str, list[Bet]], args: argparse.Namespace, input_path: Path) -> str:
    summary_rows = []
    for condition, bets in grouped.items():
        if len(bets) < args.min_tickets_report:
            continue
        row = stats(bets, args.bootstrap, args.seed)
        row["condition"] = condition
        summary_rows.append(row)
    summary_rows.sort(key=lambda r: (-r["roi"], -r["tickets"], r["condition"]))

    lines = [
        f"# 穴党参謀AI ワイドペア条件別バックテスト {date.today().isoformat()}",
        "",
        f"- input: `{input_path}`",
        f"- pair rows: {len(rows):,}",
        f"- bootstrap samples: {args.bootstrap}",
        "",
        "## 条件サマリ",
        "",
        "| condition | races | tickets | hits | hit% | ROI | CI5 | drop1 | drop3 | max | lose_streak | max_dd |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['condition']} | {row['races']:,} | {row['tickets']:,} | {row['hits']:,} | "
            f"{pct(row['hit_rate'])} | {pct(row['roi'])} | {pct(row['ci5'])} | "
            f"{pct(row['drop1'])} | {pct(row['drop3'])} | {row['max_payout']:,} | "
            f"{row['longest_losing_streak']:,} | {row['max_drawdown']:,} |"
        )

    lines += [
        "",
        "## 月別",
        "",
        "| condition | month | tickets | hit% | ROI |",
        "|---|---|---:|---:|---:|",
    ]
    for row in summary_rows[: args.segment_top]:
        bets = grouped[row["condition"]]
        for month, seg_bets in sorted(group_by(bets, "month").items()):
            if len(seg_bets) < args.min_segment_tickets:
                continue
            seg = stats(seg_bets, 0, args.seed)
            lines.append(f"| {row['condition']} | {month} | {seg['tickets']:,} | {pct(seg['hit_rate'])} | {pct(seg['roi'])} |")

    lines += [
        "",
        "## 競馬場別 top segments",
        "",
        "| condition | venue | tickets | hit% | ROI |",
        "|---|---|---:|---:|---:|",
    ]
    for row in summary_rows[: args.segment_top]:
        bets = grouped[row["condition"]]
        venue_rows = []
        for venue, seg_bets in group_by(bets, "venue").items():
            if len(seg_bets) < args.min_segment_tickets:
                continue
            seg = stats(seg_bets, 0, args.seed)
            venue_rows.append((venue, seg))
        venue_rows.sort(key=lambda item: (-item[1]["roi"], -item[1]["tickets"], item[0]))
        for venue, seg in venue_rows[: args.venue_top]:
            lines.append(f"| {row['condition']} | {venue} | {seg['tickets']:,} | {pct(seg['hit_rate'])} | {pct(seg['roi'])} |")

    lines += [
        "",
        "## 判断メモ",
        "",
        "- ROIだけで採用しない。CI5、drop1、drop3、月別安定を必ず見る。",
        "- drop1/drop3で崩れる条件は高配当1発依存として扱う。",
        "- Phase 2へ進める候補は、最低でもROI 100%近辺、drop1 90%以上、月別で大崩れしない条件に限定する。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest Anatou pair conditions")
    parser.add_argument("--input", required=True, help="pair JSONL")
    parser.add_argument("--out", default="", help="output markdown report")
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--min-tickets-report", type=int, default=50)
    parser.add_argument("--min-segment-tickets", type=int, default=30)
    parser.add_argument("--segment-top", type=int, default=12)
    parser.add_argument("--venue-top", type=int, default=10)
    args = parser.parse_args()

    input_path = Path(args.input)
    rows = load_jsonl(input_path)
    grouped = make_bets(rows)
    report = build_report(rows, grouped, args, input_path)

    out_path = Path(args.out) if args.out else DOCS_DIR / f"anatou_pair_backtest_{date.today().strftime('%Y%m%d')}_{input_path.stem}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[report] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
