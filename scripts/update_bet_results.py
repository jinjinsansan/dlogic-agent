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
    import json as _json
    if not date_iso_set:
        return {}
    date_list = "(" + ",".join(f'"{d}"' for d in date_iso_set) + ")"
    rows = _sb_get(
        DLOGIC_URL, DLOGIC_KEY, "race_results",
        {"race_date": f"in.{date_list}", "status": "eq.finished",
         "select": "race_id,winner_number,win_payout,result_json"},
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        rj = r.get("result_json")
        if isinstance(rj, str):
            try:
                r["result_json"] = _json.loads(rj)
            except Exception:
                r["result_json"] = {}
        elif not isinstance(rj, dict):
            r["result_json"] = {}
        out[r["race_id"]] = r
    return out


def update_bet(bet_id: int, result: str, payout: int) -> bool:
    return _sb_patch(
        HORSE_URL, HORSE_KEY, "bet_history",
        {"id": f"eq.{bet_id}"},
        {"bet_result": result, "payout": payout},
    )


# ────── GANTZ outcome（個人投票と独立した「全体結果」） ──────
def fetch_pending_gantz_signals() -> list[dict[str, Any]]:
    """outcome_status='pending' な GANTZ signals を取得。直近 30 日分のみ。
    L1 単勝 / L2 複勝・ワイド / L3 複勝・馬連・三連複 を全て対象とする。"""
    cutoff = (datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")
    return _sb_get(
        HORSE_URL, HORSE_KEY, "bet_signals",
        {
            "source": "like.gantz_*",
            "outcome_status": "eq.pending",
            "signal_date": f"gte.{cutoff}",
            # bet_type フィルタ削除: L2(2,5)/L3(2,4,7) も対象
            "select": "id,signal_date,jo_name,race_no,bet_type,kaime_data",
        },
    )


def update_signal_outcome(
    signal_id: int,
    outcome: str,
    winner_number: int | None,
    payout_per_100: int | None,
) -> bool:
    return _sb_patch(
        HORSE_URL, HORSE_KEY, "bet_signals",
        {"id": f"eq.{signal_id}"},
        {
            "outcome_status": outcome,
            "outcome_winner_number": winner_number,
            "outcome_payout_per_100": payout_per_100,
            "outcome_updated_at": datetime.now(JST).isoformat(),
        },
    )


def _resolve_gantz_outcome(
    sig: dict[str, Any], result: dict[str, Any]
) -> tuple[str, int | None, int | None]:
    """bet_type ごとの勝敗を判定。
    Returns: (outcome, winner_number_or_none, payout_per_100_or_none)
    outcome は 'win' | 'lose' | 'unknown'
    """
    rj = result.get("result_json") or {}
    top3_list = rj.get("top3") or []
    top3_horses = [t.get("horse_number") for t in top3_list if t.get("horse_number")]
    payouts = rj.get("payouts") or {}

    bet_type = int(sig.get("bet_type") or 1)
    kaime = sig.get("kaime_data") or []

    def _horse(idx: int) -> int:
        try:
            return int(kaime[idx]) if len(kaime) > idx else 0
        except (ValueError, TypeError):
            return 0

    if bet_type == 1:  # 単勝
        h = _horse(0)
        if not h:
            return ("unknown", None, None)
        winner = result.get("winner_number")
        win_payout = int(result.get("win_payout") or 0)
        if h == winner:
            return ("win", winner, win_payout)
        return ("lose", winner, 0)

    if bet_type == 2:  # 複勝
        h = _horse(0)
        if not h or not top3_horses:
            return ("unknown", None, None)
        fuku_payout = 0
        for entry in (payouts.get("fukusho") or []):
            if entry.get("horse_number") == h:
                fuku_payout = entry.get("payout") or 0
                break
        if h in top3_horses:
            return ("win", None, fuku_payout)
        return ("lose", None, 0)

    if bet_type == 4:  # 馬連
        h1, h2 = _horse(0), _horse(1)
        if not h1 or not h2 or len(top3_horses) < 2:
            return ("unknown", None, None)
        top2_set = frozenset(top3_horses[:2])
        umaren_payout = 0
        um = payouts.get("umaren") or {}
        if frozenset(um.get("combo") or []) == frozenset([h1, h2]):
            umaren_payout = um.get("payout") or 0
        if frozenset([h1, h2]) == top2_set:
            return ("win", None, umaren_payout)
        return ("lose", None, 0)

    if bet_type == 5:  # ワイド
        h1, h2 = _horse(0), _horse(1)
        if not h1 or not h2 or not top3_horses:
            return ("unknown", None, None)
        top3_set = set(top3_horses[:3])
        wide_payout = 0
        target = frozenset([h1, h2])
        for entry in (payouts.get("wide") or []):
            if frozenset(entry.get("combo") or []) == target:
                wide_payout = entry.get("payout") or 0
                break
        if h1 in top3_set and h2 in top3_set:
            return ("win", None, wide_payout)
        return ("lose", None, 0)

    if bet_type == 7:  # 三連複
        h1, h2, h3 = _horse(0), _horse(1), _horse(2)
        if not h1 or not h2 or not h3 or len(top3_horses) < 3:
            return ("unknown", None, None)
        top3_set = frozenset(top3_horses[:3])
        san_payout = 0
        san = payouts.get("sanrenpuku") or {}
        if frozenset(san.get("combo") or []) == frozenset([h1, h2, h3]):
            san_payout = san.get("payout") or 0
        if frozenset([h1, h2, h3]) == top3_set:
            return ("win", None, san_payout)
        return ("lose", None, 0)

    return ("unknown", None, None)


def update_gantz_outcomes(results_cache: dict[str, dict[str, Any]]) -> tuple[int, int, int]:
    """
    bet_signals.outcome_* を更新。L1(単勝)/L2(複勝,ワイド)/L3(複勝,馬連,三連複) 全対応。
    引数の results_cache は既に取得済みの race_results を使い回し、
    不足分は本関数内で追加 fetch する。
    Returns (win, lose, failed)
    """
    pending = fetch_pending_gantz_signals()
    logger.info("pending GANTZ signals: %d", len(pending))
    if not pending:
        return 0, 0, 0

    # 不足する race_date を集計し、追加 fetch
    needed_dates: set[str] = set()
    for s in pending:
        d = s.get("signal_date")
        if d:
            needed_dates.add(d)
    # L6: results_cache のキーは "YYYYMMDD-JO-NO" 形式。race_date 列が存在しない場合でも
    #     キーから日付を抽出して比較することで不要な再 fetch を防ぐ
    cached_dates: set[str] = set()
    for race_id_key in results_cache.keys():
        parts = race_id_key.split("-")
        if parts and len(parts[0]) == 8:
            d = parts[0]
            cached_dates.add(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
    missing = needed_dates - cached_dates
    if missing:
        extra = fetch_race_results(missing)
        results_cache = {**results_cache, **extra}

    win = lose = failed = 0
    for sig in pending:
        date_str = (sig.get("signal_date") or "").replace("-", "")
        race_id = f"{date_str}-{sig.get('jo_name')}-{sig.get('race_no')}"
        result = results_cache.get(race_id)
        if not result:
            continue  # まだ結果未確定。pending のまま据え置き

        outcome, winner_num, payout = _resolve_gantz_outcome(sig, result)
        if outcome == "unknown":
            logger.debug("GANTZ signal %d: outcome unknown (bet_type=%s, kaime=%s)",
                         sig["id"], sig.get("bet_type"), sig.get("kaime_data"))
            continue

        if outcome == "win":
            if update_signal_outcome(sig["id"], "win", winner_num, payout):
                win += 1
                logger.info("GANTZ signal %d: WIN race=%s bet_type=%s payout/100=%s",
                            sig["id"], race_id, sig.get("bet_type"), payout)
            else:
                failed += 1
        else:
            if update_signal_outcome(sig["id"], "lose", winner_num, 0):
                lose += 1
                logger.info("GANTZ signal %d: LOSE race=%s bet_type=%s",
                            sig["id"], race_id, sig.get("bet_type"))
            else:
                failed += 1

    return win, lose, failed


def main() -> int:
    if not (HORSE_URL and HORSE_KEY and DLOGIC_URL and DLOGIC_KEY):
        logger.error("missing required env vars (HORSE_* and SUPABASE_*)")
        return 2

    pending = fetch_pending_bets()
    logger.info("pending bet_history: %d", len(pending))

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
        # bet_type 1/2/4/5/7 に対応。未対応 bet_type はスキップ
        if sig.get("bet_type") not in (1, 2, 4, 5, 7):
            skipped += 1
            continue

        date_str = (sig.get("signal_date") or "").replace("-", "")
        race_id = f"{date_str}-{sig.get('jo_name')}-{sig.get('race_no')}"
        result = results.get(race_id)
        if not result:
            skipped += 1
            continue

        # bet_history の selected_kaime を sig の kaime_data 相当として使用
        fake_sig = {**sig, "kaime_data": bet.get("selected_kaime") or sig.get("kaime_data") or []}
        outcome, _winner_num, payout_per_100 = _resolve_gantz_outcome(fake_sig, result)
        if outcome == "unknown":
            skipped += 1
            continue

        bet_amount = bet.get("bet_amount") or 0
        ratio = bet_amount / 100 if bet_amount else 1

        if outcome == "win":
            payout = int((payout_per_100 or 0) * ratio)
            if update_bet(bet["id"], "win", payout):
                win_count += 1
                logger.info("bet %d: WIN payout=%d (race=%s bet_type=%s)",
                            bet["id"], payout, race_id, sig.get("bet_type"))
            else:
                failed += 1
                logger.error("bet %d: PATCH failed (intended WIN payout=%d)", bet["id"], payout)
        else:
            if update_bet(bet["id"], "lose", 0):
                lose_count += 1
                logger.info("bet %d: LOSE (race=%s bet_type=%s)",
                            bet["id"], race_id, sig.get("bet_type"))
            else:
                failed += 1
                logger.error("bet %d: PATCH failed (intended LOSE)", bet["id"])

    logger.info("bet_history done: win=%d lose=%d skipped=%d failed=%d",
                win_count, lose_count, skipped, failed)

    # ─── GANTZ 全体 outcome 更新（個人投票とは独立） ───
    g_win, g_lose, g_failed = update_gantz_outcomes(results)
    logger.info("GANTZ outcomes: win=%d lose=%d failed=%d", g_win, g_lose, g_failed)

    total_failed = failed + g_failed
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
