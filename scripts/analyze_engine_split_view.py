#!/usr/bin/env python3
"""Split analysis for JRA vs NAR using engine_hit_rates.

1年分を対象に JRA/NAR を完全分離して集計する:
- エンジン別 (win/place/recovery)
- 合議度別 (1/4, 2/4, 3/4, 4/4)
- 曜日別 (回収率)
- 会場別 (回収率・サンプル閾値付き)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv(".env.local")

JST = timezone(timedelta(hours=9))
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic")
WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Split analysis for JRA/NAR")
    p.add_argument("--days", type=int, default=365, help="対象日数 (default: 365)")
    p.add_argument("--since", help="開始日 YYYY-MM-DD (指定時は --days より優先)")
    p.add_argument("--min-venue-samples", type=int, default=30, help="会場別の最小サンプル")
    p.add_argument("--out", help="出力mdパス (省略時: docs/engine_split_analysis_YYYYMMDD.md)")
    return p.parse_args()


def fetch_all(sb, table: str, select: str, gte: dict | None = None, chunk: int = 1000):
    rows = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items():
                q = q.gte(k, v)
        res = q.range(offset, offset + chunk - 1).execute()
        batch = res.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < chunk:
            break
        offset += chunk
    return rows


def weekday_jp(date_iso: str) -> str:
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d")
        return WEEKDAYS[d.weekday()]
    except Exception:
        return "?"


def fmt_pct(n: float) -> str:
    return f"{n:.1f}%"


def render_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    out.extend("| " + " | ".join(r) + " |" for r in rows)
    return out


def summarize_by_type(hits: list[dict], payout_map: dict[str, int], min_venue_samples: int) -> dict:
    # engine-level
    engine_stats = defaultdict(lambda: defaultdict(lambda: {
        "n": 0, "win": 0, "place": 0, "payout": 0,
    }))
    # race-level aggregates (consensus / weekday / venue)
    by_race: dict[str, dict] = {}

    for h in hits:
        rt = h.get("race_type") or "?"
        eng = h.get("engine") or "?"
        rid = h.get("race_id") or ""
        if not rid:
            continue

        s = engine_stats[rt][eng]
        s["n"] += 1
        if h.get("hit_win"):
            s["win"] += 1
            s["payout"] += int(payout_map.get(rid, 0) or 0)
        if h.get("hit_place"):
            s["place"] += 1

        r = by_race.setdefault(
            rid,
            {
                "race_type": rt,
                "date": h.get("date") or "",
                "venue": h.get("venue") or "不明",
                "result_1st": h.get("result_1st"),
                "top1": {},
            },
        )
        top1 = h.get("top1_horse")
        if top1 is not None:
            r["top1"][eng] = int(top1)

    consensus = defaultdict(lambda: defaultdict(lambda: {"n": 0, "win": 0, "payout": 0}))
    weekday = defaultdict(lambda: defaultdict(lambda: {"n": 0, "win": 0, "payout": 0}))
    venue = defaultdict(lambda: defaultdict(lambda: {"n": 0, "win": 0, "payout": 0}))

    for rid, r in by_race.items():
        rt = r["race_type"]
        winner = r["result_1st"]
        picks = list(r["top1"].values())
        if not picks:
            continue
        c = Counter(picks)
        max_vote = max(c.values())
        voted = min(horse for horse, cnt in c.items() if cnt == max_vote)
        bucket = f"{max_vote}/4"
        is_win = winner is not None and int(winner) == voted
        payout = int(payout_map.get(rid, 0) or 0)

        consensus[rt][bucket]["n"] += 1
        consensus[rt][bucket]["win"] += 1 if is_win else 0
        consensus[rt][bucket]["payout"] += payout if is_win else 0

        wd = weekday_jp(r["date"])
        weekday[rt][wd]["n"] += 1
        weekday[rt][wd]["win"] += 1 if is_win else 0
        weekday[rt][wd]["payout"] += payout if is_win else 0

        v = r["venue"]
        venue[rt][v]["n"] += 1
        venue[rt][v]["win"] += 1 if is_win else 0
        venue[rt][v]["payout"] += payout if is_win else 0

    return {
        "engine": engine_stats,
        "consensus": consensus,
        "weekday": weekday,
        "venue": venue,
        "min_venue_samples": min_venue_samples,
    }


def render_markdown(since_iso: str, total_hits: int, summary: dict) -> str:
    lines: list[str] = []
    lines.append("# エンジン分離分析レポート (JRA / NAR)")
    lines.append("")
    lines.append(f"- 対象開始日: **{since_iso}**")
    lines.append(f"- engine_hit_rates 行数: **{total_hits:,}**")
    lines.append("")

    for rt in ("jra", "nar"):
        title = "JRA (中央)" if rt == "jra" else "NAR (地方)"
        lines.append(f"## {title}")
        lines.append("")

        # Engine
        rows = []
        for eng in ENGINES:
            s = summary["engine"][rt].get(eng)
            if not s or s["n"] == 0:
                continue
            n = s["n"]
            win_rate = s["win"] / n * 100
            place_rate = s["place"] / n * 100
            rec = s["payout"] / (n * 100) * 100
            rows.append([
                eng, f"{n:,}", f"{s['win']:,}", fmt_pct(win_rate), fmt_pct(place_rate), fmt_pct(rec),
            ])
        lines.append("### 1) エンジン別")
        lines.extend(render_table(["engine", "races", "win", "win%", "place%", "recovery%"], rows))
        lines.append("")

        # Consensus
        rows = []
        for b in ("4/4", "3/4", "2/4", "1/4"):
            s = summary["consensus"][rt].get(b)
            if not s or s["n"] == 0:
                continue
            n = s["n"]
            wr = s["win"] / n * 100
            rec = s["payout"] / (n * 100) * 100
            rows.append([b, f"{n:,}", f"{s['win']:,}", fmt_pct(wr), fmt_pct(rec)])
        lines.append("### 2) 合議度別 (top1一致)")
        lines.extend(render_table(["consensus", "races", "wins", "win%", "recovery%"], rows))
        lines.append("")

        # Weekday
        rows = []
        for wd in WEEKDAYS:
            s = summary["weekday"][rt].get(wd)
            if not s or s["n"] == 0:
                continue
            n = s["n"]
            wr = s["win"] / n * 100
            rec = s["payout"] / (n * 100) * 100
            rows.append([wd, f"{n:,}", f"{s['win']:,}", fmt_pct(wr), fmt_pct(rec)])
        lines.append("### 3) 曜日別 (多数決top1)")
        lines.extend(render_table(["weekday", "races", "wins", "win%", "recovery%"], rows))
        lines.append("")

        # Venue top
        rows = []
        min_n = summary["min_venue_samples"]
        venue_items = []
        for v, s in summary["venue"][rt].items():
            if s["n"] < min_n:
                continue
            rec = s["payout"] / (s["n"] * 100) * 100
            wr = s["win"] / s["n"] * 100
            venue_items.append((rec, wr, v, s))
        venue_items.sort(reverse=True)
        for rec, wr, v, s in venue_items[:15]:
            rows.append([v, f"{s['n']:,}", f"{s['win']:,}", fmt_pct(wr), fmt_pct(rec)])
        lines.append(f"### 4) 会場別 (n >= {min_n})")
        lines.extend(render_table(["venue", "races", "wins", "win%", "recovery%"], rows))
        lines.append("")

    lines.append("## メモ")
    lines.append("- このレポートは **JRA/NARを混ぜずに** 集計しています。")
    lines.append("- 回収率は「1レース100円固定の単勝」換算です。")
    lines.append("- 会場別はサンプルが少ないと歪むため、最小件数でフィルタしています。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if args.since:
        since_iso = args.since
    else:
        since_iso = (datetime.now(JST) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    try:
        from db.supabase_client import get_client
    except ImportError as e:
        print(f"ERROR: missing dependency for Supabase client: {e}")
        return 2

    sb = get_client()
    hits = fetch_all(
        sb,
        "engine_hit_rates",
        "date,race_id,race_type,venue,engine,top1_horse,result_1st,hit_win,hit_place",
        gte={"date": since_iso},
    )
    results = fetch_all(
        sb,
        "race_results",
        "race_id,win_payout,status",
        gte={"race_date": since_iso},
    )
    payout_map = {
        r["race_id"]: int(r.get("win_payout") or 0)
        for r in results
        if r.get("status") == "finished" and r.get("race_id")
    }

    summary = summarize_by_type(hits, payout_map, min_venue_samples=args.min_venue_samples)
    md = render_markdown(since_iso=since_iso, total_hits=len(hits), summary=summary)

    out = args.out
    if not out:
        today = datetime.now(JST).strftime("%Y%m%d")
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = os.path.join(project_dir, "docs", f"engine_split_analysis_{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"DONE: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
