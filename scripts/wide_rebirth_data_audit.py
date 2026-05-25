#!/usr/bin/env python3
"""Audit data readiness for the Anatou wide-bet rebuild.

This script is read-only. It checks whether existing Supabase tables are
usable for top5 wide backtests before we build a new strategy runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from supabase import create_client


PROJECT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_DIR / "docs"
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic", "nlogic")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def load_supabase_env(allow_vps: bool = True) -> None:
    """Load Supabase credentials from env, .env.local, or VPS fallback."""
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return

    for env_path in (PROJECT_DIR / ".env.local", PROJECT_DIR / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"} and value:
                os.environ.setdefault(key, value)
        if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            return

    if not allow_vps:
        return

    try:
        out = subprocess.check_output(
            [
                "ssh",
                "root@220.158.24.157",
                "grep -E '^(SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=' /opt/dlogic/linebot/.env.local",
            ],
            text=True,
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic fallback
        logger.warning("could not load Supabase env from VPS: %s", exc)
        return

    for line in out.strip().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"} and value:
            os.environ[key] = value


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_json_maybe(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def fetch_all(
    sb: Any,
    table: str,
    select: str,
    *,
    gte: dict[str, Any] | None = None,
    lte: dict[str, Any] | None = None,
    eq: dict[str, Any] | None = None,
    chunk: int = 1000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        for key, value in (gte or {}).items():
            q = q.gte(key, value)
        for key, value in (lte or {}).items():
            q = q.lte(key, value)
        for key, value in (eq or {}).items():
            q = q.eq(key, value)
        res = q.range(offset, offset + chunk - 1).execute()
        data = res.data or []
        if not data:
            break
        rows.extend(data)
        if len(data) < chunk:
            break
        offset += chunk
    return rows


def pct(num: int | float, den: int | float) -> str:
    if not den:
        return "0.0%"
    return f"{num / den * 100:.1f}%"


def top_lengths(rows: list[dict[str, Any]]) -> Counter[int]:
    lengths: Counter[int] = Counter()
    for row in rows:
        horses = row.get("top3_horses") or []
        if not isinstance(horses, list):
            lengths[-1] += 1
        else:
            lengths[len(horses)] += 1
    return lengths


def race_key(row: dict[str, Any]) -> tuple[str, str, int] | None:
    race_date = row.get("date") or row.get("race_date")
    venue = row.get("venue")
    race_number = row.get("race_number")
    if race_number is None:
        race_number = infer_race_number(row.get("race_id"))
    if not race_date or not venue or race_number is None:
        return None
    try:
        return (str(race_date)[:10], str(venue), int(race_number))
    except (TypeError, ValueError):
        return None


def infer_race_number(race_id: Any) -> int | None:
    """Infer race number from local race_id formats when race_results lacks it."""
    if race_id is None:
        return None
    text = str(race_id)
    if "-" in text:
        tail = text.rsplit("-", 1)[-1]
        try:
            return int(tail)
        except ValueError:
            return None
    if len(text) >= 2 and text[-2:].isdigit():
        try:
            num = int(text[-2:])
            return num if 1 <= num <= 18 else None
        except ValueError:
            return None
    return None


def monthly_key(value: str | None) -> str:
    if not value:
        return "unknown"
    return value[:7]


def clean_gap_bucket(row: dict[str, Any]) -> str:
    race_date = parse_iso_date(row.get("date"))
    created = parse_iso_date(row.get("created_at"))
    if not race_date or not created:
        return "unknown"
    gap = (created - race_date).days
    if gap <= -1:
        return "pre_day_or_earlier"
    if gap == 0:
        return "same_day"
    if gap == 1:
        return "next_day"
    return "later"


def summarize_engine_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_engine = Counter(row.get("engine") or "unknown" for row in rows)
    by_type = Counter(row.get("race_type") or "unknown" for row in rows)
    by_month = Counter(monthly_key(row.get("date")) for row in rows)
    by_top_len = top_lengths(rows)
    by_gap = Counter(clean_gap_bucket(row) for row in rows)

    by_race: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    race_meta: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = row.get("race_id")
        engine = row.get("engine")
        if not rid or not engine:
            continue
        by_race[str(rid)][str(engine)] = row
        race_meta[str(rid)] = row

    engine_count_by_race = Counter(len(v) for v in by_race.values())
    top5_ready_races = 0
    four_engine_ready = 0
    five_engine_ready = 0
    nlogic_races = 0
    for engine_rows in by_race.values():
        engines = set(engine_rows)
        if "nlogic" in engines:
            nlogic_races += 1
        if len(engines & set(ENGINES[:4])) >= 4:
            four_engine_ready += 1
        if len(engines & set(ENGINES)) >= 5:
            five_engine_ready += 1
        if any(len(r.get("top3_horses") or []) >= 5 for r in engine_rows.values()):
            top5_ready_races += 1

    return {
        "rows": len(rows),
        "unique_races": len(by_race),
        "by_engine": by_engine,
        "by_type": by_type,
        "by_month": by_month,
        "by_top_len": by_top_len,
        "by_gap": by_gap,
        "engine_count_by_race": engine_count_by_race,
        "top5_ready_races": top5_ready_races,
        "four_engine_ready": four_engine_ready,
        "five_engine_ready": five_engine_ready,
        "nlogic_races": nlogic_races,
        "race_ids": set(by_race),
        "race_keys": {k for k in (race_key(v) for v in race_meta.values()) if k},
    }


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    finished = [r for r in rows if r.get("status") == "finished"]
    with_payouts = []
    with_wide = []
    parse_failed = 0
    by_month = Counter()
    by_type = Counter()
    race_ids: set[str] = set()
    keys: set[tuple[str, str, int]] = set()

    for row in finished:
        rid = row.get("race_id")
        if rid:
            race_ids.add(str(rid))
        key = race_key(row)
        if key:
            keys.add(key)
        by_month[monthly_key(row.get("race_date"))] += 1
        by_type[row.get("race_type") or "unknown"] += 1

        raw = row.get("result_json")
        if isinstance(raw, str):
            try:
                rj = json.loads(raw)
            except json.JSONDecodeError:
                parse_failed += 1
                rj = {}
        else:
            rj = raw if isinstance(raw, dict) else {}
        payouts = rj.get("payouts") if isinstance(rj, dict) else None
        if isinstance(payouts, dict) and payouts:
            with_payouts.append(row)
            if payouts.get("wide"):
                with_wide.append(row)

    return {
        "rows": len(rows),
        "finished": len(finished),
        "with_payouts": len(with_payouts),
        "with_wide": len(with_wide),
        "parse_failed": parse_failed,
        "by_month": by_month,
        "by_type": by_type,
        "race_ids": race_ids,
        "race_keys": keys,
    }


def summarize_odds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[tuple[str, str, int], str] = {}
    valid_payload = 0
    by_month = Counter()
    for row in rows:
        key = race_key(row)
        if not key:
            continue
        by_month[monthly_key(row.get("race_date"))] += 1
        data = parse_json_maybe(row.get("odds_data"))
        if data:
            valid_payload += 1
        snap = str(row.get("snapshot_at") or "")
        if key not in latest or snap > latest[key]:
            latest[key] = snap
    return {
        "rows": len(rows),
        "unique_races": len(latest),
        "valid_payload": valid_payload,
        "by_month": by_month,
        "race_keys": set(latest),
    }


def counter_table(counter: Counter[Any], limit: int | None = None) -> list[str]:
    items = counter.most_common()
    if limit is not None:
        items = items[:limit]
    return [f"| {key} | {value:,} |" for key, value in items]


def build_report(
    *,
    since: str,
    until: str,
    engine_summary: dict[str, Any],
    results_summary: dict[str, Any],
    odds_summary: dict[str, Any],
) -> str:
    engine_rids = engine_summary["race_ids"]
    result_rids = results_summary["race_ids"]
    engine_keys = engine_summary["race_keys"]
    result_keys = results_summary["race_keys"]
    odds_keys = odds_summary["race_keys"]

    rid_result_overlap = len(engine_rids & result_rids)
    key_result_overlap = len(engine_keys & result_keys)
    key_odds_overlap = len(engine_keys & odds_keys)
    top5_ready = engine_summary["top5_ready_races"]
    unique_races = engine_summary["unique_races"]

    lines = [
        f"# 穴党参謀AI ワイド再構築 データ監査 {date.today().isoformat()}",
        "",
        f"- 対象期間: {since} 〜 {until}",
        "- 処理: 読み取りのみ。Supabaseの更新なし。",
        "",
        "## 総合判定",
        "",
    ]

    if not unique_races:
        lines.append("- engine_hit_rates が取得できていない。接続または期間指定を確認する。")
    else:
        lines.append(f"- engine_hit_rates unique races: {unique_races:,}")
        lines.append(f"- top5入り候補レース: {top5_ready:,} ({pct(top5_ready, unique_races)})")
        lines.append(f"- 4エンジン揃い: {engine_summary['four_engine_ready']:,} ({pct(engine_summary['four_engine_ready'], unique_races)})")
        lines.append(f"- 5エンジン揃い: {engine_summary['five_engine_ready']:,} ({pct(engine_summary['five_engine_ready'], unique_races)})")
        lines.append(f"- NLogicあり: {engine_summary['nlogic_races']:,} ({pct(engine_summary['nlogic_races'], unique_races)})")
        lines.append(f"- race_idで結果と一致: {rid_result_overlap:,} ({pct(rid_result_overlap, unique_races)})")
        lines.append(f"- date/venue/race_numberで結果と一致: {key_result_overlap:,} ({pct(key_result_overlap, unique_races)})")
        lines.append(f"- 人気データあり: {key_odds_overlap:,} ({pct(key_odds_overlap, unique_races)})")
        lines.append(f"- wide払戻あり finished results: {results_summary['with_wide']:,} ({pct(results_summary['with_wide'], results_summary['finished'])})")

    lines += [
        "",
        "## engine_hit_rates",
        "",
        f"- rows: {engine_summary['rows']:,}",
        f"- unique races: {unique_races:,}",
        "",
        "### engine別",
        "",
        "| engine | rows |",
        "|---|---:|",
        *counter_table(engine_summary["by_engine"]),
        "",
        "### race_type別",
        "",
        "| race_type | rows |",
        "|---|---:|",
        *counter_table(engine_summary["by_type"]),
        "",
        "### top3_horses配列長",
        "",
        "| length | rows |",
        "|---|---:|",
        *counter_table(engine_summary["by_top_len"]),
        "",
        "### 1レースあたりエンジン数",
        "",
        "| engine_count | races |",
        "|---|---:|",
        *counter_table(engine_summary["engine_count_by_race"]),
        "",
        "### created_atとrace dateの差",
        "",
        "| bucket | rows |",
        "|---|---:|",
        *counter_table(engine_summary["by_gap"]),
        "",
        "### 月別 engine rows",
        "",
        "| month | rows |",
        "|---|---:|",
        *counter_table(engine_summary["by_month"]),
        "",
        "## race_results",
        "",
        f"- rows: {results_summary['rows']:,}",
        f"- finished: {results_summary['finished']:,}",
        f"- payoutsあり: {results_summary['with_payouts']:,}",
        f"- wide払戻あり: {results_summary['with_wide']:,}",
        f"- result_json parse失敗: {results_summary['parse_failed']:,}",
        "",
        "### 月別 finished results",
        "",
        "| month | rows |",
        "|---|---:|",
        *counter_table(results_summary["by_month"]),
        "",
        "## odds_snapshots",
        "",
        f"- rows: {odds_summary['rows']:,}",
        f"- unique races: {odds_summary['unique_races']:,}",
        f"- odds_data有効payload: {odds_summary['valid_payload']:,}",
        "",
        "### 月別 odds rows",
        "",
        "| month | rows |",
        "|---|---:|",
        *counter_table(odds_summary["by_month"]),
        "",
        "## 次の判断",
        "",
        "- top5入り候補レースが少なければ、バックエンドAPIへ過去出馬表を再投入して top5 を再生成する。",
        "- wide払戻カバー率が低ければ、`scripts/fetch_pckeiba_payouts_to_results.py` で補完する。",
        "- 人気データの一致率が低ければ、PCKEIBA側の人気を使う正規データセット作成に切り替える。",
        "- 5エンジン揃いが少なければ、まず4エンジン版と5エンジン版を分けて検証する。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit data readiness for wide-bet rebuild")
    parser.add_argument("--since", default="2026-03-01", help="start date YYYY-MM-DD")
    parser.add_argument("--until", default=date.today().isoformat(), help="end date YYYY-MM-DD")
    parser.add_argument("--out", default="", help="output markdown path")
    parser.add_argument("--no-vps-env", action="store_true", help="do not fetch Supabase env from VPS")
    args = parser.parse_args()

    load_supabase_env(allow_vps=not args.no_vps_env)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    sb = create_client(url, key)

    logger.info("loading engine_hit_rates %s..%s", args.since, args.until)
    engine_rows = fetch_all(
        sb,
        "engine_hit_rates",
        "date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at",
        gte={"date": args.since},
        lte={"date": args.until},
    )
    logger.info("engine_hit_rates rows: %s", len(engine_rows))

    logger.info("loading race_results %s..%s", args.since, args.until)
    result_rows = fetch_all(
        sb,
        "race_results",
        "race_id,race_date,venue,race_type,status,result_json",
        gte={"race_date": args.since},
        lte={"race_date": args.until},
    )
    logger.info("race_results rows: %s", len(result_rows))

    logger.info("loading odds_snapshots %s..%s", args.since, args.until)
    odds_rows = fetch_all(
        sb,
        "odds_snapshots",
        "race_date,venue,race_number,odds_data,snapshot_at",
        gte={"race_date": args.since},
        lte={"race_date": args.until},
    )
    logger.info("odds_snapshots rows: %s", len(odds_rows))

    report = build_report(
        since=args.since,
        until=args.until,
        engine_summary=summarize_engine_rows(engine_rows),
        results_summary=summarize_results(result_rows),
        odds_summary=summarize_odds(odds_rows),
    )

    out_path = Path(args.out) if args.out else DOCS_DIR / f"wide_rebirth_data_audit_{date.today().strftime('%Y%m%d')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n[report] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
