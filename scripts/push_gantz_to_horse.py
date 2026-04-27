#!/usr/bin/env python3
"""GANTZ → HorseBet ブリッジ.

dlogic-agent の /api/data/golden-pattern/today から strict レースを取得し、
HorseBet 用 Supabase の bet_signals テーブルに upsert する。

GANTZ Telegram 配信 (anatou_post_strict.py) の直後 (09:01 JST) に走る想定。
"""
from __future__ import annotations

import argparse
import json
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

API_BASE = os.environ.get("GOLDEN_API_BASE", "http://127.0.0.1:5000")
HORSE_SUPABASE_URL = os.environ.get("HORSE_SUPABASE_URL", "")
HORSE_SUPABASE_KEY = os.environ.get("HORSE_SUPABASE_SERVICE_ROLE_KEY", "")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger("push_gantz_to_horse")


# ---- venue → jo_code 逆引きテーブル ----
# horse/horsebet-system/shared/types/business.types.ts と完全一致
JRA_JO_CODES: dict[str, str] = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}
NAR_JO_CODES: dict[str, str] = {
    "30": "門別", "31": "盛岡", "32": "水沢", "33": "浦和", "34": "船橋",
    "35": "大井", "36": "川崎", "37": "金沢", "38": "笠松", "39": "名古屋",
    "40": "園田", "41": "姫路", "42": "高知", "43": "佐賀", "44": "帯広",
}
NAME_TO_CODE: dict[str, str] = {v: k for k, v in {**JRA_JO_CODES, **NAR_JO_CODES}.items()}


def resolve_jo_code(venue: str, is_local: bool) -> str | None:
    code = NAME_TO_CODE.get(venue)
    if code is None:
        logger.warning("unknown venue: %r (is_local=%s)", venue, is_local)
        return None
    if is_local and code not in NAR_JO_CODES:
        logger.warning("venue %r reported is_local but maps to JRA code %s", venue, code)
        return None
    if not is_local and code not in JRA_JO_CODES:
        logger.warning("venue %r reported as JRA but maps to NAR code %s", venue, code)
        return None
    return code


class TransientApiError(Exception):
    """API への通信失敗 / 5xx — pipeline は失敗扱いにすべきエラー"""


# ---- API fetch ----
def fetch_pattern(date_str: str) -> dict | None:
    """data を返す。404 (= データなし) のみ None を返す。
    通信失敗・サーバ 5xx 等は TransientApiError を raise（呼び出し側で exit 1 を判断）。
    """
    url = f"{API_BASE}/api/data/golden-pattern/today"
    try:
        resp = requests.get(url, params={"date": date_str, "race_type": "both"}, timeout=180)
    except requests.RequestException as e:
        raise TransientApiError(f"network error: {e}") from e
    if resp.status_code == 404:
        logger.info("no prefetch data for %s (404) — silent skip", date_str)
        return None
    if 500 <= resp.status_code < 600:
        raise TransientApiError(f"API 5xx: {resp.status_code} {resp.text[:200]}")
    if resp.status_code != 200:
        raise TransientApiError(f"API unexpected status: {resp.status_code} {resp.text[:200]}")
    return resp.json()


# ---- mapping ----
def date_to_iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def build_note(race: dict[str, Any]) -> str:
    cons = race.get("consensus") or {}
    pop = race.get("popularity_rank")
    pop_str = f"{pop}人気" if pop else "?人気"
    hn = cons.get("horse_number", "?")
    name = cons.get("horse_name", "?")
    start = race.get("start_time") or "—"
    agreed = cons.get("agreed_engines") or []
    agreed_short = "+".join(e[0].upper() for e in agreed) if agreed else "—"
    count = cons.get("count", 0)
    return (
        f"GANTZ strict | {hn}番{name} | {pop_str} | "
        f"発走{start} | 一致{count}/4({agreed_short})"
    )


def race_to_signal_row(race: dict[str, Any], signal_date_iso: str, source: str) -> dict[str, Any] | None:
    """Layer 1 (NAR本命厳格 単勝) — 1 row per race."""
    venue = race.get("venue") or ""
    is_local = bool(race.get("is_local"))
    jo_code = resolve_jo_code(venue, is_local)
    if jo_code is None:
        return None

    cons = race.get("consensus") or {}
    horse_number = cons.get("horse_number")
    if not horse_number:
        logger.warning("missing consensus.horse_number for %s", race.get("race_id"))
        return None

    race_no = race.get("race_number")
    if not race_no:
        logger.warning("missing race_number for %s", race.get("race_id"))
        return None

    return {
        "signal_date": signal_date_iso,
        "race_type": "NAR" if is_local else "JRA",
        "jo_code": jo_code,
        "jo_name": venue,
        "race_no": int(race_no),
        "bet_type": 1,            # 単勝
        "bet_type_name": "単勝",
        "method": 0,              # 単勝は方式不要
        "suggested_amount": 100,  # GANTZ 仕様
        "kaime_data": [str(horse_number)],
        "note": build_note(race),
        "status": "active",
        "start_time": race.get("start_time") or None,
        "source": source,
        "created_by": None,
    }


def _build_base_row(race: dict[str, Any], signal_date_iso: str) -> dict[str, Any] | None:
    """Layer 2/3 共通のベース row 部分."""
    venue = race.get("venue") or ""
    is_local = bool(race.get("is_local"))
    jo_code = resolve_jo_code(venue, is_local)
    if jo_code is None:
        return None
    race_no = race.get("race_number")
    if not race_no:
        return None
    return {
        "signal_date": signal_date_iso,
        "race_type": "NAR" if is_local else "JRA",
        "jo_code": jo_code,
        "jo_name": venue,
        "race_no": int(race_no),
        "suggested_amount": 100,
        "status": "active",
        "start_time": race.get("start_time") or None,
        "created_by": None,
    }


def race_to_jra_layer3_rows(race: dict[str, Any], signal_date_iso: str) -> list[dict[str, Any]]:
    """Layer 3 (JRA S級) — F5複勝 + U2馬連BOX3 + S1三連複1点.

    各馬/各組合せを独立 row、unique source で uniqueness 確保。
    """
    from itertools import combinations
    base = _build_base_row(race, signal_date_iso)
    if not base:
        return []

    rows: list[dict[str, Any]] = []
    venue = race.get("venue") or ""

    # F5複勝: 3エンジン以上 top3一致馬 → 各馬 複勝
    f5_horses = race.get("jra_f5_horses") or []
    for i, h in enumerate(f5_horses, 1):
        hn = h.get("horse_number")
        if not hn:
            continue
        rows.append({
            **base,
            "bet_type": 2, "bet_type_name": "複勝", "method": 0,
            "kaime_data": [str(hn)],
            "note": (
                f"GANTZ jra-f5 複勝 | {hn}番{h.get('horse_name','?')} | "
                f"{h.get('popularity','?')}人気 | 一致{h.get('vote_count','?')}/4"
            ),
            "source": f"gantz_jra_f5_p{i}",
        })

    # U2馬連BOX3 + S1三連複1点: 投票TOP3頭 (jra_top3_horses)
    top3 = race.get("jra_top3_horses") or []
    if len(top3) == 3:
        nums = [h.get("horse_number") for h in top3]
        # U2 馬連BOX3 (3点)
        for i, (h1, h2) in enumerate(combinations(nums, 2), 1):
            rows.append({
                **base,
                "bet_type": 4, "bet_type_name": "馬連", "method": 0,
                "kaime_data": [str(h1), str(h2)],
                "note": (
                    f"GANTZ jra-u2 馬連 | {h1}-{h2} | {venue}"
                ),
                "source": f"gantz_jra_u2_w{i}",
            })
        # S1 三連複1点 (TOP3 BOX = 1組)
        rows.append({
            **base,
            "bet_type": 7, "bet_type_name": "３連複", "method": 0,
            "kaime_data": [str(n) for n in nums],
            "note": (
                f"GANTZ jra-s1 三連複 | {nums[0]}-{nums[1]}-{nums[2]} | {venue}"
            ),
            "source": "gantz_jra_s1",
        })

    return rows


def race_to_obihiro_rows(race: dict[str, Any], signal_date_iso: str) -> list[dict[str, Any]]:
    """Layer 2 (帯広中穴 複勝+ワイドBOX) — 複数 rows per race.

    複勝: 各馬を個別 row として、source='gantz_obihiro_p{i}' で uniqueness 確保
    ワイドBOX: 各ペアを個別 row、source='gantz_obihiro_w{i}'
    """
    from itertools import combinations
    venue = race.get("venue") or ""
    is_local = bool(race.get("is_local"))
    jo_code = resolve_jo_code(venue, is_local)
    if jo_code is None:
        return []

    horses = race.get("obihiro_horses") or []
    if not horses:
        return []

    race_no = race.get("race_number")
    if not race_no:
        return []

    base = {
        "signal_date": signal_date_iso,
        "race_type": "NAR" if is_local else "JRA",
        "jo_code": jo_code,
        "jo_name": venue,
        "race_no": int(race_no),
        "suggested_amount": 100,
        "status": "active",
        "start_time": race.get("start_time") or None,
        "created_by": None,
    }

    rows: list[dict[str, Any]] = []
    # 複勝: 1 row per horse
    for i, h in enumerate(horses, 1):
        hn = h.get("horse_number")
        if not hn:
            continue
        rows.append({
            **base,
            "bet_type": 2,
            "bet_type_name": "複勝",
            "method": 0,
            "kaime_data": [str(hn)],
            "note": (
                f"GANTZ obihiro 複勝 | {hn}番{h.get('horse_name','?')} | "
                f"{h.get('popularity','?')}人気 | 一致{h.get('vote_count','?')}/4"
            ),
            "source": f"gantz_obihiro_p{i}",
        })

    # ワイドBOX: 1 row per pair
    if len(horses) >= 2:
        for i, (h1, h2) in enumerate(combinations(horses, 2), 1):
            n1 = h1.get("horse_number"); n2 = h2.get("horse_number")
            if not n1 or not n2:
                continue
            rows.append({
                **base,
                "bet_type": 5,
                "bet_type_name": "ワイド",
                "method": 0,
                "kaime_data": [str(n1), str(n2)],
                "note": (
                    f"GANTZ obihiro ワイド | {n1}-{n2} | "
                    f"{h1.get('popularity','?')}人気×{h2.get('popularity','?')}人気"
                ),
                "source": f"gantz_obihiro_w{i}",
            })

    return rows


# ---- Supabase upsert ----
def upsert_signals(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Returns (inserted_or_updated_count, error_count)."""
    if not rows:
        return 0, 0
    if not HORSE_SUPABASE_URL or not HORSE_SUPABASE_KEY:
        logger.error("HORSE_SUPABASE_URL or HORSE_SUPABASE_SERVICE_ROLE_KEY not set")
        return 0, len(rows)

    url = f"{HORSE_SUPABASE_URL.rstrip('/')}/rest/v1/bet_signals"
    headers = {
        "apikey": HORSE_SUPABASE_KEY,
        "Authorization": f"Bearer {HORSE_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    params = {"on_conflict": "source,signal_date,jo_code,race_no,bet_type"}

    last_err: str | None = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, params=params, headers=headers, json=rows, timeout=30)
        except requests.RequestException as e:
            last_err = str(e)
            logger.warning("supabase upsert network error (attempt %d): %s", attempt, e)
            time.sleep(2 ** attempt)
            continue
        if 200 <= resp.status_code < 300:
            try:
                returned = resp.json()
                ok_count = len(returned) if isinstance(returned, list) else len(rows)
            except ValueError:
                ok_count = len(rows)
            return ok_count, 0
        last_err = f"{resp.status_code} {resp.text[:300]}"
        logger.warning("supabase upsert non-2xx (attempt %d): %s", attempt, last_err)
        time.sleep(2 ** attempt)
    logger.error("supabase upsert failed after retries: %s", last_err)
    return 0, len(rows)


# ---- main ----
def main() -> int:
    p = argparse.ArgumentParser(description="GANTZ → HorseBet bridge")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y%m%d"), help="YYYYMMDD")
    p.add_argument("--source", default="gantz_strict", choices=["gantz_strict", "gantz_loose"])
    p.add_argument("--include-loose", action="store_true",
                   help="include is_golden_loose races (default: strict only)")
    p.add_argument("--dry-run", action="store_true", help="print rows but do not write")
    args = p.parse_args()

    date_str = args.date
    if len(date_str) != 8 or not date_str.isdigit():
        logger.error("invalid --date %r (expected YYYYMMDD)", date_str)
        return 2

    logger.info("target date: %s", date_str)
    try:
        data = fetch_pattern(date_str)
    except TransientApiError as e:
        logger.error("fatal: %s", e)
        return 1
    if not data:
        return 0

    races = data.get("races") or []
    # Layer 1: strict のみがデフォルト。--include-loose で strict OR loose も対象
    if args.include_loose:
        layer1_targets = [r for r in races if r.get("is_golden_strict") or r.get("is_golden_loose")]
        logger.info("--include-loose active: strict+loose races included for L1")
    else:
        layer1_targets = [r for r in races if r.get("is_golden_strict")]
    layer2_targets = [r for r in races if r.get("is_layer2_obihiro")]
    layer3_targets = [r for r in races
                      if r.get("is_layer3_jra_f5") or r.get("is_layer3_jra_combo")]

    logger.info("fetched %d races: L1=%d L2=%d L3=%d",
                len(races), len(layer1_targets), len(layer2_targets), len(layer3_targets))

    iso_date = date_to_iso(date_str)
    rows: list[dict[str, Any]] = []

    # Layer 1: NAR本命厳格 単勝 (1 row per race)
    for r in layer1_targets:
        # loose のみのレースには source を 'gantz_loose' に上書き
        src = args.source
        if args.include_loose and not r.get("is_golden_strict") and r.get("is_golden_loose"):
            src = "gantz_loose"
        row = race_to_signal_row(r, iso_date, src)
        if row is not None:
            rows.append(row)
        else:
            logger.warning("skip race %s due to mapping failure", r.get("race_id"))

    # Layer 2: 帯広中穴 複勝+ワイドBOX (multiple rows per race)
    for r in layer2_targets:
        rows.extend(race_to_obihiro_rows(r, iso_date))

    # Layer 3: JRA S級 (週末) 複勝 + 馬連BOX3 + 三連複1点
    for r in layer3_targets:
        rows.extend(race_to_jra_layer3_rows(r, iso_date))

    if not rows:
        logger.info("nothing to push — exit")
        return 0

    logger.info("prepared %d signal row(s)", len(rows))

    if args.dry_run:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        logger.info("dry-run complete")
        return 0

    ok, err = upsert_signals(rows)
    logger.info("upsert result: ok=%d err=%d", ok, err)
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
