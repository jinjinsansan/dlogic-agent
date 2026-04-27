#!/usr/bin/env python3
"""Backfill engine_hit_rates from PCKEIBA historical entries.

目的:
- 未来の運用結果を待たず、過去レース出走表を使ってエンジン精度データを蓄積する
- JRA/NAR を分離して同一ロジックで検証可能にする

処理概要:
1) PCKEIBA の jvd_se / nvd_se から出走行を読み込む
2) race 単位に payload を組み立てて /api/v2/predictions/newspaper を叩く
3) 確定着順(1-3着)と照合し、engine_hit_rates に upsert

注意:
- 予想は「当時予想」ではなく「現在のモデルで過去レースを再予想」した結果
- 依存: psycopg2, requests, python-dotenv, supabase
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

try:
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv(".env.local")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
ENGINES = ("dlogic", "ilogic", "viewlogic", "metalogic")

DLOGIC_API_URL = os.getenv("DLOGIC_API_URL", "http://localhost:8000").rstrip("/")
PCKEIBA_CONFIG = {
    "host": os.getenv("PCKEIBA_HOST", "127.0.0.1"),
    "port": int(os.getenv("PCKEIBA_PORT", "5432")),
    "database": os.getenv("PCKEIBA_DB", "pckeiba"),
    "user": os.getenv("PCKEIBA_USER", "postgres"),
    "password": os.getenv("PCKEIBA_PASSWORD", "postgres"),
}

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATHS = [
    os.path.join(PROJECT_DIR, "data", "nar_schedule_master_2020_2026.json"),
    r"E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json",
]

JRA_VENUES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}
NAR_VENUES = {
    "83": "帯広", "30": "門別", "35": "盛岡", "36": "水沢", "45": "浦和",
    "43": "船橋", "42": "大井", "44": "川崎", "46": "金沢", "47": "笠松",
    "48": "名古屋", "50": "園田", "51": "姫路", "54": "高知", "55": "佐賀",
}
NANKAN_CODES = {"42", "43", "44", "45"}
REGION_GROUPS = [
    {"35", "36"},
    {"46", "47", "48"},
    {"50", "51"},
    {"54", "55"},
    {"30", "83"},
]

_SAVE_HIT_RATE = None


def get_save_hit_rate():
    global _SAVE_HIT_RATE
    if _SAVE_HIT_RATE is None:
        from db.engine_stats import save_hit_rate as _fn

        _SAVE_HIT_RATE = _fn
    return _SAVE_HIT_RATE


def load_schedule_master() -> dict[str, Any] | None:
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                logger.info("loaded schedule master: %s", p)
                return json.load(f)
    logger.warning("schedule master not found; NAR venue correction disabled")
    return None


def correct_nar_venue(nen: str, tsukihi: str, original_code: str, schedule: dict[str, Any] | None) -> str:
    if not schedule or "schedule_data" not in schedule:
        return original_code
    race_date = f"{nen}{tsukihi}"
    day_venues = schedule["schedule_data"].get(race_date, [])
    if not day_venues:
        return original_code
    if len(day_venues) == 1:
        return day_venues[0]
    if original_code in day_venues:
        return original_code
    if original_code in NANKAN_CODES:
        nankan_on_day = [c for c in day_venues if c in NANKAN_CODES]
        if len(nankan_on_day) == 1:
            return nankan_on_day[0]
    for group in REGION_GROUPS:
        if original_code in group:
            cands = [c for c in day_venues if c in group]
            if len(cands) == 1:
                return cands[0]
            break
    return original_code


def pick_first(existing: set[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in existing:
            return c
    return None


def quote_col(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def as_int(v: Any) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def as_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def normalize_distance(v: Any) -> str:
    s = as_text(v)
    if not s:
        return ""
    if s.endswith("m"):
        return s
    n = as_int(s)
    return f"{n}m" if n is not None else s


def normalize_track(v: Any) -> str:
    s = as_text(v)
    if not s:
        return "良"
    mapping = {
        "1": "良", "2": "稍重", "3": "重", "4": "不良",
        "A": "良", "B": "稍重", "C": "重", "D": "不良",
    }
    return mapping.get(s, s)


def get_table_columns(conn, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        return {r[0] for r in cur.fetchall()}


def table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.tables
              WHERE table_schema='public' AND table_name=%s
            )
            """,
            (table_name,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def pick_expr(existing: set[str], candidates: list[str], table_alias: str) -> str | None:
    c = pick_first(existing, candidates)
    if not c:
        return None
    return f"{table_alias}.{quote_col(c)}"


def choose_columns(conn, table_se: str, table_ra: str | None) -> dict[str, str | None]:
    cols_se = get_table_columns(conn, table_se)
    cols_ra = get_table_columns(conn, table_ra) if table_ra else set()

    required = ["kaisai_nen", "kaisai_tsukihi", "keibajo_code", "race_bango", "umaban", "kakutei_chakujun"]
    missing = [c for c in required if c not in cols_se]
    if missing:
        raise RuntimeError(f"{table_se} missing required columns: {missing}")

    return {
        "horse_name": (
            pick_expr(cols_se, ["bamei", "umamei", "horse_name", "horse"], "se")
            or pick_expr(cols_ra, ["bamei", "umamei", "horse_name", "horse"], "ra")
        ),
        "jockey": (
            pick_expr(cols_se, ["kishumei_ryakusho", "kishu_mei", "kishumei", "jockey_name", "jockey"], "se")
            or pick_expr(cols_ra, ["kishumei_ryakusho", "kishu_mei", "kishumei", "jockey_name", "jockey"], "ra")
        ),
        "post_no": (
            pick_expr(cols_se, ["wakuban", "waku_bango", "post_no", "post"], "se")
            or pick_expr(cols_ra, ["wakuban", "waku_bango", "post_no", "post"], "ra")
        ),
        # 距離・馬場・レース名は SE に無い場合 RA を利用
        "distance": (
            pick_expr(cols_se, ["kyori", "distance"], "se")
            or pick_expr(cols_ra, ["kyori", "distance"], "ra")
        ),
        "track": (
            pick_expr(cols_se, ["baba_jotai", "track_condition", "track_state"], "se")
            or pick_expr(cols_ra, ["baba_jotai", "track_condition", "track_state"], "ra")
        ),
        "race_name": (
            pick_expr(cols_se, ["race_name", "jushomei", "kyosomei"], "se")
            or pick_expr(cols_ra, ["race_name", "jushomei", "kyosomei"], "ra")
        ),
    }


SELECT_COL_NAMES = [
    "kaisai_nen",
    "kaisai_tsukihi",
    "keibajo_code",
    "race_bango",
    "umaban",
    "kakutei_chakujun",
    "horse_name",
    "jockey",
    "post_no",
    "distance",
    "track",
    "race_name",
]


def build_stream_sql(table_se: str, table_ra: str | None, colmap: dict[str, str | None], with_until: bool = False) -> str:
    fields = [
        f"se.{quote_col('kaisai_nen')}",
        f"se.{quote_col('kaisai_tsukihi')}",
        f"se.{quote_col('keibajo_code')}",
        f"se.{quote_col('race_bango')}",
        f"se.{quote_col('umaban')}",
        f"se.{quote_col('kakutei_chakujun')}",
    ]
    for alias in ("horse_name", "jockey", "post_no", "distance", "track", "race_name"):
        expr = colmap.get(alias)
        if expr:
            fields.append(f"{expr} AS {alias}")
        else:
            fields.append(f"NULL AS {alias}")

    join_sql = ""
    if table_ra:
        join_sql = f"""
        LEFT JOIN {table_ra} ra
          ON se.kaisai_nen = ra.kaisai_nen
         AND se.kaisai_tsukihi = ra.kaisai_tsukihi
         AND se.keibajo_code = ra.keibajo_code
         AND se.race_bango = ra.race_bango
        """

    where_until = ""
    if with_until:
        where_until = "AND (se.kaisai_nen || se.kaisai_tsukihi) <= %s"

    return f"""
        SELECT {", ".join(fields)}
        FROM {table_se} se
        {join_sql}
        WHERE (se.kaisai_nen || se.kaisai_tsukihi) >= %s
          {where_until}
        ORDER BY se.kaisai_nen, se.kaisai_tsukihi, se.keibajo_code, se.race_bango, se.umaban
    """


def get_predictions(payload: dict[str, Any]) -> dict[str, list[int]]:
    try:
        resp = requests.post(
            f"{DLOGIC_API_URL}/api/v2/predictions/newspaper",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        raise RuntimeError(f"prediction API error: {e}") from e

    out: dict[str, list[int]] = {}
    for eng in ENGINES:
        raw = body.get(eng)
        if not isinstance(raw, list):
            continue
        picks = []
        for x in raw:
            v = as_int(x)
            if v is not None:
                picks.append(v)
        if picks:
            out[eng] = picks[:5]
    return out


def build_payload(race: dict[str, Any]) -> dict[str, Any]:
    entries = sorted(race["entries"], key=lambda x: x["horse_no"])
    horse_numbers = [e["horse_no"] for e in entries]
    horses = [e["horse_name"] or f"#{e['horse_no']}" for e in entries]
    jockeys = [e["jockey"] for e in entries]
    posts = [e["post_no"] if e["post_no"] else e["horse_no"] for e in entries]

    return {
        "race_id": race["race_id"],
        "horses": horses,
        "horse_numbers": horse_numbers,
        "venue": race["venue"],
        "race_number": race["race_number"],
        "jockeys": jockeys,
        "posts": posts,
        "distance": race["distance"],
        "track_condition": race["track_condition"],
    }


def finalize_race(
    race: dict[str, Any] | None,
    dry_run: bool,
) -> tuple[int, int]:
    if not race:
        return 0, 0
    entries = race["entries"]
    if len(entries) < 5:
        return 0, 1

    top3 = sorted(
        (e for e in entries if e["finish_pos"] in (1, 2, 3)),
        key=lambda x: x["finish_pos"],
    )
    if len(top3) < 3:
        return 0, 1

    if dry_run:
        # dry-run: 対象レースとして件数だけカウントし、API/DB は叩かない
        return 0, 0

    payload = build_payload(race)
    try:
        preds = get_predictions(payload)
    except Exception as e:
        logger.warning("prediction failed %s: %s", race["race_id"], e)
        return 0, 1

    if not preds:
        logger.warning("no engine predictions returned: %s", race["race_id"])
        return 0, 1

    result_1st, result_2nd, result_3rd = [x["horse_no"] for x in top3[:3]]
    writes = 0
    for eng in ENGINES:
        picks = preds.get(eng)
        if not picks:
            continue
        top1 = picks[0]
        top3_horses = picks[:3]
        result_set = {result_1st, result_2nd, result_3rd}
        hit_win = top1 == result_1st
        place_hit_count = sum(1 for p in top3_horses if p in result_set)
        hit_place = place_hit_count > 0
        if not dry_run:
            save_hit_rate = get_save_hit_rate()
            save_hit_rate(
                date=race["date_iso"],
                race_id=race["race_id"],
                venue=race["venue"],
                race_number=race["race_number"],
                race_type=race["race_type"],
                engine=eng,
                top1_horse=top1,
                top3_horses=top3_horses,
                result_1st=result_1st,
                result_2nd=result_2nd,
                result_3rd=result_3rd,
                hit_win=hit_win,
                hit_place=hit_place,
                place_hit_count=place_hit_count,
            )
        writes += 1
    return writes, 0


def race_from_first_row(
    row: dict[str, Any],
    race_type: str,
    schedule: dict[str, Any] | None,
) -> dict[str, Any] | None:
    nen = as_text(row["kaisai_nen"])
    md = as_text(row["kaisai_tsukihi"]).zfill(4)
    code = as_text(row["keibajo_code"]).zfill(2)
    race_no = as_int(row["race_bango"])
    if not nen or len(md) != 4 or race_no is None:
        return None

    if race_type == "jra":
        venue = JRA_VENUES.get(code)
    else:
        corr = correct_nar_venue(nen, md, code, schedule)
        venue = NAR_VENUES.get(corr)
    if not venue:
        return None

    yyyymmdd = f"{nen}{md}"
    date_iso = f"{nen}-{md[:2]}-{md[2:]}"
    race_id = f"{yyyymmdd}-{venue}-{race_no}"

    return {
        "race_type": race_type,
        "race_id": race_id,
        "date_iso": date_iso,
        "yyyymmdd": yyyymmdd,
        "venue": venue,
        "race_number": race_no,
        "distance": normalize_distance(row.get("distance")),
        "track_condition": normalize_track(row.get("track")),
        "race_name": as_text(row.get("race_name")),
        "entries": [],
    }


def stream_backfill_for_type(
    conn,
    table_se: str,
    race_type: str,
    since_compact: str,
    schedule: dict[str, Any] | None,
    dry_run: bool,
    limit_races: int | None,
    until_compact: str | None = None,
) -> tuple[int, int, int]:
    table_ra = table_se.replace("_se", "_ra")
    if not table_exists(conn, table_ra):
        table_ra = None

    colmap = choose_columns(conn, table_se, table_ra)
    sql = build_stream_sql(table_se, table_ra, colmap, with_until=bool(until_compact))
    logger.info("streaming %s (%s) %s〜%s", table_se, race_type, since_compact, until_compact or "(now)")
    logger.info("joined race table (%s): %s", race_type, table_ra or "none")
    logger.info("column map %s: %s", race_type, colmap)

    cur = conn.cursor(name=f"bf_{race_type}")
    cur.itersize = 5000
    if until_compact:
        cur.execute(sql, (since_compact, until_compact))
    else:
        cur.execute(sql, (since_compact,))
    col_names = list(SELECT_COL_NAMES)

    current_key: tuple[str, str, str, int] | None = None
    current_race: dict[str, Any] | None = None
    races = writes = skipped = 0

    for values in cur:
        row = dict(zip(col_names, values))
        row_key = (
            as_text(row["kaisai_nen"]),
            as_text(row["kaisai_tsukihi"]).zfill(4),
            as_text(row["keibajo_code"]).zfill(2),
            as_int(row["race_bango"]) or 0,
        )

        if current_key is None:
            current_key = row_key
            current_race = race_from_first_row(row, race_type, schedule)
        elif row_key != current_key:
            w, s = finalize_race(current_race, dry_run=dry_run)
            if current_race:
                races += 1
            writes += w
            skipped += s
            if races % 200 == 0 and races > 0:
                logger.info("%s progress races=%d writes=%d skipped=%d", race_type, races, writes, skipped)
            if limit_races and races >= limit_races:
                break
            current_key = row_key
            current_race = race_from_first_row(row, race_type, schedule)

        if not current_race:
            continue

        horse_no = as_int(row["umaban"])
        finish_pos = as_int(row["kakutei_chakujun"])
        if horse_no is None:
            continue
        current_race["entries"].append(
            {
                "horse_no": horse_no,
                "horse_name": as_text(row.get("horse_name")),
                "jockey": as_text(row.get("jockey")),
                "post_no": as_int(row.get("post_no")),
                "finish_pos": finish_pos if finish_pos is not None else 0,
            }
        )

    # flush last race
    if current_race and (not limit_races or races < limit_races):
        w, s = finalize_race(current_race, dry_run=dry_run)
        races += 1
        writes += w
        skipped += s

    cur.close()
    return races, writes, skipped


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill engine_hit_rates from PCKEIBA")
    p.add_argument("--days", type=int, default=365, help="何日前まで遡るか (default: 365)")
    p.add_argument("--since", help="開始日 YYYYMMDD (指定時は --days より優先)")
    p.add_argument("--until", help="終了日 YYYYMMDD (省略時は今日まで)")
    p.add_argument("--race-type", choices=["all", "jra", "nar"], default="all")
    p.add_argument("--dry-run", action="store_true", help="DB保存せず件数確認のみ")
    p.add_argument("--limit-races", type=int, help="デバッグ用: 処理レース数を制限")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if psycopg2 is None:
        logger.error("psycopg2 is required. install with: python3 -m pip install psycopg2-binary")
        return 2

    if args.since:
        since_compact = args.since
    else:
        since_compact = (datetime.now(JST) - timedelta(days=args.days)).strftime("%Y%m%d")

    schedule = load_schedule_master()
    conn = psycopg2.connect(**PCKEIBA_CONFIG)
    logger.info(
        "start backfill since=%s race_type=%s dry_run=%s",
        since_compact,
        args.race_type,
        args.dry_run,
    )

    targets = []
    if args.race_type in ("all", "jra"):
        targets.append(("jvd_se", "jra"))
    if args.race_type in ("all", "nar"):
        targets.append(("nvd_se", "nar"))

    until_compact = args.until if args.until else None

    total_races = total_writes = total_skipped = 0
    for table_se, rt in targets:
        r, w, s = stream_backfill_for_type(
            conn=conn,
            table_se=table_se,
            race_type=rt,
            since_compact=since_compact,
            schedule=schedule,
            dry_run=args.dry_run,
            limit_races=args.limit_races,
            until_compact=until_compact,
        )
        total_races += r
        total_writes += w
        total_skipped += s
        logger.info("%s done races=%d writes=%d skipped=%d", rt, r, w, s)

    conn.close()
    logger.info(
        "ALL DONE races=%d writes=%d skipped=%d since=%s",
        total_races,
        total_writes,
        total_skipped,
        since_compact,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
