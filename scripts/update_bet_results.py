#!/usr/bin/env python3
"""HorseBet bet_history.bet_result 更新スクリプト.

dlogic-agent の race_results テーブルからレース結果を取得し、
HorseBet 側の pending な bet_history 行を win/lose に確定する。

現状は単勝（bet_type=1）のみ判定。複勝・連系は将来対応。

実行タイミング: 23:00 JST 想定（最終レース後）
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

JST = timezone(timedelta(hours=9))
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env() -> None:
    env_path = os.path.join(PROJECT_DIR, ".env.local")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()

# HorseBet Supabase（bet_history を読み書き）
HORSE_URL = os.environ.get("HORSE_SUPABASE_URL", "").rstrip("/")
HORSE_KEY = os.environ.get("HORSE_SUPABASE_SERVICE_ROLE_KEY", "")

# dlogic-agent 自身の Supabase（race_results を読み取り）
DLOGIC_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
DLOGIC_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger("update_bet_results")


def _sb_get(base: str, key: str, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"{base}/rest/v1/{table}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    last_err: str | None = None
    for attempt in range(1, 4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
            continue
        if 200 <= r.status_code < 300:
            return r.json() if r.text else []
        last_err = f"{r.status_code} {r.text[:300]}"
        time.sleep(2 ** attempt)
    logger.error("supabase GET %s failed: %s", table, last_err)
    return []


def _sb_patch(base: str, key: str, table: str, params: dict[str, Any], payload: dict[str, Any]) -> bool:
    url = f"{base}/rest/v1/{table}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        r = requests.patch(url, params=params, headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        logger.error("supabase PATCH %s network: %s", table, e)
        return False
    if 200 <= r.status_code < 300:
        return True
    logger.error("supabase PATCH %s failed: %s %s", table, r.status_code, r.text[:300])
    return False


def fetch_pending_bets() -> list[dict[str, Any]]:
    return _sb_get(
        HORSE_URL, HORSE_KEY, "bet_history",
        {"bet_result": "eq.pending", "select": "id,signal_id,bet_amount,selected_kaime,bet_date"},
    )


def fetch_signals(signal_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not signal_ids:
        return {}
    in_clause = "(" + ",".join(str(i) for i in signal_ids) + ")"
    rows = _sb_get(
        HORSE_URL, HORSE_KEY, "bet_signals",
        {"id": f"in.{in_clause}", "select": "id,signal_date,jo_name,race_no,bet_type"},
    )
    return {r["id"]: r for r in rows}


def fetch_race_results(date_iso_set: set[str]) -> dict[str, dict[str, Any]]:
    """date_iso_set: {'2026-04-24', ...} → {race_id: result}"""
    if not date_iso_set:
        return {}
    date_list = "(" + ",".join(f'"{d}"' for d in date_iso_set) + ")"
    rows = _sb_get(
        DLOGIC_URL, DLOGIC_KEY, "race_results",
        {"race_date": f"in.{date_list}", "status": "eq.finished",
         "select": "race_id,winner_number,win_payout"},
    )
    return {r["race_id"]: r for r in rows}


def update_bet(bet_id: int, result: str, payout: int) -> bool:
    return _sb_patch(
        HORSE_URL, HORSE_KEY, "bet_history",
        {"id": f"eq.{bet_id}"},
        {"bet_result": result, "payout": payout},
    )


def main() -> int:
    if not (HORSE_URL and HORSE_KEY and DLOGIC_URL and DLOGIC_KEY):
        logger.error("missing required env vars (HORSE_* and SUPABASE_*)")
        return 2

    pending = fetch_pending_bets()
    logger.info("pending bet_history: %d", len(pending))
    if not pending:
        return 0

    signal_ids = [b["signal_id"] for b in pending if b.get("signal_id")]
    signals = fetch_signals(signal_ids)

    # 必要な日付を集計
    dates_iso: set[str] = set()
    for s in signals.values():
        if s.get("signal_date"):
            dates_iso.add(s["signal_date"])

    results = fetch_race_results(dates_iso)
    logger.info("loaded %d race_results across %d dates", len(results), len(dates_iso))

    win_count = 0
    lose_count = 0
    skipped = 0
    failed = 0

    for bet in pending:
        sig = signals.get(bet.get("signal_id"))
        if not sig:
            skipped += 1
            continue
        if sig.get("bet_type") != 1:  # 単勝以外スキップ（将来対応）
            skipped += 1
            continue

        date_str = (sig.get("signal_date") or "").replace("-", "")
        race_id = f"{date_str}-{sig.get('jo_name')}-{sig.get('race_no')}"
        result = results.get(race_id)
        if not result:
            skipped += 1
            continue

        kaime = bet.get("selected_kaime") or []
        try:
            bet_horse = int(kaime[0]) if kaime else 0
        except (ValueError, TypeError):
            bet_horse = 0
        if not bet_horse:
            skipped += 1
            continue

        winner = result.get("winner_number")
        bet_amount = bet.get("bet_amount") or 0

        if bet_horse == winner:
            ratio = bet_amount / 100 if bet_amount else 0
            payout = int((result.get("win_payout") or 0) * ratio)
            if update_bet(bet["id"], "win", payout):
                win_count += 1
                logger.info("bet %d: WIN payout=%d (race=%s horse=%d)",
                            bet["id"], payout, race_id, bet_horse)
            else:
                failed += 1
                logger.error("bet %d: PATCH failed (intended WIN payout=%d)", bet["id"], payout)
        else:
            if update_bet(bet["id"], "lose", 0):
                lose_count += 1
                logger.info("bet %d: LOSE (race=%s bet=%d winner=%s)",
                            bet["id"], race_id, bet_horse, winner)
            else:
                failed += 1
                logger.error("bet %d: PATCH failed (intended LOSE)", bet["id"])

    logger.info("done: win=%d lose=%d skipped=%d failed=%d",
                win_count, lose_count, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
