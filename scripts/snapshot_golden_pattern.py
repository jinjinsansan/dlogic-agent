#!/usr/bin/env python3
"""Snapshot the golden-pattern API output for a given date to a local JSON file.

Run after race results are confirmed (post 22:00 JST) so that finished
result data is included. Snapshots persist beyond the prefetch retention
window (9 days), enabling long-term review on /v2/golden-pattern.

Usage:
    python scripts/snapshot_golden_pattern.py [YYYYMMDD]
        (default: today JST)
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(PROJECT_DIR, 'data', 'golden_history')
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

JST = timezone(timedelta(hours=9))
API_BASE = os.environ.get('GOLDEN_API_BASE', 'http://127.0.0.1:5000')

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(JST).strftime('%Y%m%d')

    if len(date_str) != 8 or not date_str.isdigit():
        logger.error(f"invalid date: {date_str}")
        return 1

    url = f"{API_BASE}/api/data/golden-pattern/today"
    logger.info(f"fetch {url}?date={date_str}")
    try:
        resp = requests.get(url, params={"date": date_str, "race_type": "both"}, timeout=180)
    except Exception as e:
        logger.error(f"request failed: {e}")
        return 1

    if resp.status_code != 200:
        logger.error(f"non-200 ({resp.status_code}): {resp.text[:300]}")
        return 1

    data = resp.json()
    summary = data.get("summary") or {}
    logger.info(f"got total={summary.get('total')} loose={summary.get('loose_golden')} strict={summary.get('strict_golden')}")

    out_path = os.path.join(SNAPSHOT_DIR, f"{date_str}.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)
    size_kb = os.path.getsize(out_path) / 1024
    logger.info(f"saved → {out_path} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
