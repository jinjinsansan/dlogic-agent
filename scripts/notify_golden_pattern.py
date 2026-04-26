#!/usr/bin/env python3
"""Detect today's strict golden-pattern races and push Telegram notification.

Run morning of race day (e.g. 9:00 JST) so jin sees buy candidates
before first race. Stays silent when no strict pattern (e.g. 月金土日).

Usage:
    python scripts/notify_golden_pattern.py [YYYYMMDD]
        default: today JST
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Read .env.local for tokens
env_path = os.path.join(PROJECT_DIR, '.env.local')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

JST = timezone(timedelta(hours=9))
API_BASE = os.environ.get('GOLDEN_API_BASE', 'http://127.0.0.1:5000')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get(
    'ADMIN_TELEGRAM_CHAT_ID',
    os.environ.get('TELEGRAM_CHAT_ID', '197618639'),  # jin's default
)

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def fetch_pattern(date_str: str) -> dict | None:
    url = f"{API_BASE}/api/data/golden-pattern/today"
    try:
        resp = requests.get(url, params={"date": date_str, "race_type": "both"}, timeout=180)
    except Exception as e:
        logger.error(f"API fetch failed: {e}")
        return None
    if resp.status_code != 200:
        logger.error(f"API non-200 ({resp.status_code}): {resp.text[:200]}")
        return None
    return resp.json()


def format_message(date_str: str, data: dict) -> str:
    weekday = data.get("weekday", "?")
    summary = data.get("summary", {})
    races = data.get("races", []) or []

    strict = [r for r in races if r.get("is_golden_strict")]
    if not strict:
        return ""  # silent on non-strict days (avoid daily noise)

    date_disp = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"
    lines = [
        f"🚀 <b>厳格パターン {len(strict)}件</b> ({date_disp} {weekday})",
        "=" * 22,
    ]
    strict_sorted = sorted(strict, key=lambda r: r.get("start_time") or "99:99")
    for r in strict_sorted:
        cons = r.get("consensus") or {}
        agreed = cons.get("agreed_engines", []) or []
        eng_short = "+".join(e[0].upper() for e in agreed)
        time_str = r.get("start_time") or "—"
        pop = r.get("popularity_rank")
        pop_str = f"{pop}番人気" if pop else "?番"
        lines.append(
            f"📍 {r.get('venue', '')} {r.get('race_number', 0)}R {time_str}"
        )
        lines.append(
            f"   ◎{cons.get('horse_number', '?')}.{cons.get('horse_name', '?')} "
            f"({pop_str}, {cons.get('count', 0)}/4一致 [{eng_short}])"
        )
    lines.append("")
    lines.append("💰 単勝100円ずつ買え (期待回収率: 約450%)")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN or ADMIN_TELEGRAM_CHAT_ID not set")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error(f"Telegram error: {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(JST).strftime("%Y%m%d")
    logger.info(f"target date: {date_str}")

    data = fetch_pattern(date_str)
    if not data:
        return 1

    summary = data.get("summary", {})
    logger.info(
        f"loose={summary.get('loose_golden')} strict={summary.get('strict_golden')}"
    )

    msg = format_message(date_str, data)
    if not msg:
        logger.info("no signals — silent (no telegram send)")
        return 0

    ok = send_telegram(msg)
    if ok:
        logger.info("telegram sent")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
