#!/usr/bin/env python3
"""Backtest wide-bet strategies on wide_rebirth JSONL datasets."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")


@dataclass(frozen=True)
class Ticket:
    strategy: str
    date: str
    race_id: str
    race_type: str
    venue: str
    pair: tuple[int, int]
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


def pair_key(pair: Iterable[Any]) -> tuple[int, int] | None:
    nums = [safe_int(v) for v in pair]
    nums = [n for n in nums if n is not None]
    if len(nums) != 2 or nums[0] == nums[1]:
        return None
    a, b = sorted(nums)
    return (a, b)


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def clean_record(record: dict[str, Any], mode: str) -> bool:
    if mode == "all":
        return True
    buckets = [
        payload.get("clean_gap_bucket")
        for payload in (record.get("engines") or {}).values()
    ]
    if not buckets:
        return False
    if mode == "no_later":
        return all(bucket in {"same_day", "pre_day_or_earlier"} for bucket in buckets)
    if mode == "pre_day_only":
        return all(bucket == "pre_day_or_earlier" for bucket in buckets)
    raise ValueError(f"unknown clean mode: {mode}")


def wide_payouts(record: dict[str, Any]) -> dict[tuple[int, int], int]:
    payouts = (((record.get("result") or {}).get("payouts") or {}).get("wide") or [])
    out: dict[tuple[int, int], int] = {}
    for entry in payouts:
        key = pair_key(entry.get("combo") or [])
        payout = safe_int(entry.get("payout")) or 0
        if key and payout > 0:
            out[key] = payout
    return out


def popularity(record: dict[str, Any]) -> dict[int, int]:
    raw = ((record.get("odds") or {}).get("popularity") or {})
    return {safe_int(k): safe_int(v) for k, v in raw.items() if safe_int(k) is not None and safe_int(v) is not None}


def ranked_horses(record: dict[str, Any], key: str = "vote_rank_top5") -> list[int]:
    out: list[int] = []
    for item in record.get(key) or []:
        horse = safe_int(item.get("horse"))
        if horse is not None and horse not in out:
            out.append(horse)
    return out


def add_ticket(tickets: list[Ticket], record: dict[str, Any], strategy: str, pair: tuple[int, int], payouts: dict[tuple[int, int], int]) -> None:
    tickets.append(
        Ticket(
            strategy=strategy,
            date=str(record.get("date") or ""),
            race_id=str(record.get("race_id") or ""),
            race_type=str(record.get("race_type") or "unknown"),
            venue=str(record.get("venue") or "unknown"),
            pair=pair,
            payout=payouts.get(pair, 0),
        )
    )


def pairs_from_horses(horses: list[int], size: int) -> list[tuple[int, int]]:
    selected = horses[:size]
    pairs: list[tuple[int, int]] = []
    for i, a in enumerate(selected):
        for b in selected[i + 1:]:
            pairs.append(tuple(sorted((a, b))))
    return pairs


def generate_tickets(records: list[dict[str, Any]], args: argparse.Namespace) -> list[Ticket]:
    tickets: list[Ticket] = []
    for record in records:
        payouts = wide_payouts(record)
        if not payouts:
            continue

        vote5 = ranked_horses(record, "vote_rank_top5")
        vote3 = ranked_horses(record, "vote_rank_top3")
        pop = popularity(record)

        for pair in pairs_from_horses(vote5, 2):
            add_ticket(tickets, record, "W1_vote_top2_1pt", pair, payouts)

        for pair in pairs_from_horses(vote3, 3):
            add_ticket(tickets, record, "W2_vote_top3_box3", pair, payouts)

        if record.get("has_any_top5"):
            for pair in pairs_from_horses(vote5, 4):
                add_ticket(tickets, record, "W3_vote_top4_box6", pair, payouts)
            for pair in pairs_from_horses(vote5, 5):
                add_ticket(tickets, record, "W4_vote_top5_box10", pair, payouts)

        if vote5 and pop:
            axis = vote5[0]
            hole_partners = [
                h for h in vote5[1:]
                if args.hole_pop_min <= (pop.get(h) or 999) <= args.hole_pop_max
            ]
            for h in hole_partners[: args.max_flow_partners]:
                add_ticket(tickets, record, "W5_vote_axis_to_ai_holes", tuple(sorted((axis, h))), payouts)

            popular_axis = next((h for h, p in sorted(pop.items(), key=lambda item: (item[1], item[0])) if p <= args.popular_axis_max), None)
            if popular_axis is not None:
                partners = [
                    h for h in vote5
                    if h != popular_axis and args.hole_pop_min <= (pop.get(h) or 999) <= args.hole_pop_max
                ]
                for h in partners[: args.max_flow_partners]:
                    add_ticket(tickets, record, "W6_popular_axis_to_ai_holes", tuple(sorted((popular_axis, h))), payouts)

        engines = record.get("engines") or {}
        for engine in ENGINES:
            payload = engines.get(engine) or {}
            top = [safe_int(h) for h in (payload.get("top") or [])]
            top = [h for h in top if h is not None]
            if len(top) >= 2:
                add_ticket(tickets, record, f"E1_{engine}_top2_1pt", tuple(sorted((top[0], top[1]))), payouts)
            if len(top) >= 3:
                for pair in pairs_from_horses(top, 3):
                    add_ticket(tickets, record, f"E2_{engine}_top3_box3", pair, payouts)
            if len(top) >= 5:
                for pair in pairs_from_horses(top, 5):
                    add_ticket(tickets, record, f"E3_{engine}_top5_box10", pair, payouts)

    return tickets


def longest_losing_streak(tickets: list[Ticket]) -> int:
    streak = 0
    best = 0
    for ticket in sorted(tickets, key=lambda t: (t.date, t.race_id, t.strategy, t.pair)):
        if ticket.payout > 0:
            streak = 0
        else:
            streak += 1
            best = max(best, streak)
    return best


def max_drawdown(tickets: list[Ticket]) -> int:
    equity = 0
    peak = 0
    worst = 0
    for ticket in sorted(tickets, key=lambda t: (t.date, t.race_id, t.strategy, t.pair)):
        equity += ticket.profit
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def bootstrap_ci_lower(tickets: list[Ticket], samples: int, seed: int) -> float:
    if not tickets or samples <= 0:
        return 0.0
    rng = random.Random(seed)
    n = len(tickets)
    values: list[float] = []
    payouts = [t.payout for t in tickets]
    for _ in range(samples):
        total = sum(payouts[rng.randrange(n)] for _ in range(n))
        values.append(total / (n * 100) * 100)
    values.sort()
    idx = max(0, int(samples * 0.05) - 1)
    return values[idx]


def stats_for(tickets: list[Ticket], bootstrap_samples: int, seed: int) -> dict[str, Any]:
    total = len(tickets)
    payout = sum(t.payout for t in tickets)
    hits = sum(1 for t in tickets if t.payout > 0)
    race_count = len({t.race_id for t in tickets})
    payouts = sorted([t.payout for t in tickets], reverse=True)
    payout_drop1 = payout - (payouts[0] if payouts else 0)
    payout_drop3 = payout - sum(payouts[:3])
    return {
        "tickets": total,
        "races": race_count,
        "hits": hits,
        "hit_rate": hits / total * 100 if total else 0.0,
        "payout": payout,
        "bet": total * 100,
        "roi": payout / (total * 100) * 100 if total else 0.0,
        "roi_drop1": payout_drop1 / (total * 100) * 100 if total else 0.0,
        "roi_drop3": payout_drop3 / (total * 100) * 100 if total else 0.0,
        "ci5": bootstrap_ci_lower(tickets, bootstrap_samples, seed),
        "max_payout": payouts[0] if payouts else 0,
        "longest_losing_streak": longest_losing_streak(tickets),
        "max_drawdown": max_drawdown(tickets),
    }


def group_tickets(tickets: list[Ticket], attr: str) -> dict[str, list[Ticket]]:
    grouped: dict[str, list[Ticket]] = defaultdict(list)
    for ticket in tickets:
        grouped[str(getattr(ticket, attr))].append(ticket)
    return grouped


def month_tickets(tickets: list[Ticket]) -> dict[str, list[Ticket]]:
    grouped: dict[str, list[Ticket]] = defaultdict(list)
    for ticket in tickets:
        grouped[ticket.date[:7] or "unknown"].append(ticket)
    return grouped


def format_pct(value: float) -> str:
    return f"{value:.1f}%"


def strategy_rows(grouped: dict[str, list[Ticket]], args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = []
    for strategy, tickets in grouped.items():
        if len(tickets) < args.min_tickets_report:
            continue
        row = stats_for(tickets, args.bootstrap, args.seed)
        row["strategy"] = strategy
        rows.append(row)
    rows.sort(key=lambda r: (-r["roi"], -r["tickets"], r["strategy"]))
    return rows


def build_report(records: list[dict[str, Any]], tickets: list[Ticket], args: argparse.Namespace, dataset_path: Path) -> str:
    by_strategy = defaultdict(list)
    for ticket in tickets:
        by_strategy[ticket.strategy].append(ticket)
    rows = strategy_rows(by_strategy, args)

    sources = Counter(str(record.get("source") or "unknown") for record in records)
    nlogic_records = sum(1 for record in records if record.get("has_nlogic"))
    top5_records = sum(1 for record in records if record.get("has_any_top5"))
    lines = [
        f"# 穴党参謀AI ワイド再構築 バックテスト {date.today().isoformat()}",
        "",
        f"- dataset: `{dataset_path}`",
        f"- records: {len(records):,}",
        f"- tickets: {len(tickets):,}",
        f"- clean mode: {args.clean_mode}",
        f"- bootstrap samples: {args.bootstrap}",
        f"- sources: {dict(sources)}",
        f"- NLogic records: {nlogic_records:,}",
        f"- top5 records: {top5_records:,}",
        "",
        "## 全戦略サマリ",
        "",
        "| strategy | races | tickets | hits | hit% | ROI | CI5 | drop1 | drop3 | max | lose_streak | max_dd |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['strategy']} | {row['races']:,} | {row['tickets']:,} | {row['hits']:,} | "
            f"{format_pct(row['hit_rate'])} | {format_pct(row['roi'])} | {format_pct(row['ci5'])} | "
            f"{format_pct(row['roi_drop1'])} | {format_pct(row['roi_drop3'])} | {row['max_payout']:,} | "
            f"{row['longest_losing_streak']:,} | {row['max_drawdown']:,} |"
        )

    lines += [
        "",
        "## JRA/NAR別",
        "",
        "| strategy | race_type | tickets | hit% | ROI | CI5 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows[: args.segment_top]:
        strategy_tickets = by_strategy[row["strategy"]]
        for race_type, seg_tickets in sorted(group_tickets(strategy_tickets, "race_type").items()):
            if len(seg_tickets) < args.min_segment_tickets:
                continue
            seg = stats_for(seg_tickets, args.bootstrap, args.seed)
            lines.append(
                f"| {row['strategy']} | {race_type} | {seg['tickets']:,} | "
                f"{format_pct(seg['hit_rate'])} | {format_pct(seg['roi'])} | {format_pct(seg['ci5'])} |"
            )

    lines += [
        "",
        "## 月別",
        "",
        "| strategy | month | tickets | hit% | ROI |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows[: args.segment_top]:
        strategy_tickets = by_strategy[row["strategy"]]
        for month, seg_tickets in sorted(month_tickets(strategy_tickets).items()):
            if len(seg_tickets) < args.min_segment_tickets:
                continue
            seg = stats_for(seg_tickets, 0, args.seed)
            lines.append(
                f"| {row['strategy']} | {month} | {seg['tickets']:,} | "
                f"{format_pct(seg['hit_rate'])} | {format_pct(seg['roi'])} |"
            )

    lines += [
        "",
        "## 注意",
        "",
        "- この結果は指定JSONLデータセットに対する検証。",
        "- NLogic records が0でなければ、NLogic系戦略も集計に含まれる。",
        "- top5が未保存のレースでは、top4/top5系戦略はスキップしている。",
        "- `clean_mode=no_later` は翌日以降作成の行を除外するが、同日内の発走後作成までは除外できない。",
        "- 配信採用前に発走時刻・配信時刻ベースのclean検証が必要。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest wide strategies on wide_rebirth JSONL")
    parser.add_argument("--dataset", default="", help="input JSONL dataset")
    parser.add_argument("--out", default="", help="output markdown report")
    parser.add_argument("--hole-pop-min", type=int, default=4)
    parser.add_argument("--hole-pop-max", type=int, default=12)
    parser.add_argument("--popular-axis-max", type=int, default=3)
    parser.add_argument("--max-flow-partners", type=int, default=4)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--min-tickets-report", type=int, default=50)
    parser.add_argument("--min-segment-tickets", type=int, default=30)
    parser.add_argument("--segment-top", type=int, default=12)
    parser.add_argument("--clean-mode", choices=("all", "no_later", "pre_day_only"), default="no_later")
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else DATA_DIR / "wide_rebirth_dataset_20260301_20260525_existing.jsonl"
    raw_records = load_records(dataset_path)
    records = [record for record in raw_records if clean_record(record, args.clean_mode)]
    tickets = generate_tickets(records, args)

    report = build_report(records, tickets, args, dataset_path)
    out_path = Path(args.out) if args.out else DOCS_DIR / f"wide_rebirth_backtest_{date.today().strftime('%Y%m%d')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[report] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
