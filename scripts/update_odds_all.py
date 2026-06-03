#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh win odds (+ popularities) in a prefetch JSON for NAR and JRA races.

NAR: odds are in static shutuba HTML. JRA: rendered via Lightpanda (Playwright
fallback). Odds-only and light — designed to run every ~10 minutes during race
hours so netkeita serves near-real-time odds (data_fetcher reflects the new
mtime immediately).

Usage:
    python scripts/update_odds_all.py            # today (JST)
    python scripts/update_odds_all.py 20260604   # specific date
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scrapers.odds import fetch_realtime_odds  # noqa: E402

PREFETCH_DIR = os.path.join(_ROOT, "data", "prefetch")
JST = timezone(timedelta(hours=9))


def _popularities(odds_list):
    """Rank by ascending odds (1 = favorite). 0/invalid odds get rank 0."""
    ranks = [0] * len(odds_list)
    valid = sorted(
        (i for i, o in enumerate(odds_list) if o and o > 0),
        key=lambda i: odds_list[i],
    )
    for rank, i in enumerate(valid, 1):
        ranks[i] = rank
    return ranks


def update(date_str):
    path = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
    if not os.path.exists(path):
        print(f"no prefetch: {path}")
        return False

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    races = data.get("races", [])
    updated = 0
    for r in races:
        rid = r.get("race_id_netkeiba")
        hn = r.get("horse_numbers") or []
        if not rid or not hn:
            continue
        rtype = "nar" if r.get("is_local") else "jra"
        try:
            odds_map = fetch_realtime_odds(rid, rtype)
        except Exception as e:
            print(f"  {r.get('venue')}{r.get('race_number')}R fetch error: {e}")
            odds_map = None
        if not odds_map:
            continue

        odds_list = list(r.get("odds") or [])
        if len(odds_list) != len(hn):
            odds_list = [0.0] * len(hn)

        changed = False
        for i, num in enumerate(hn):
            val = odds_map.get(num)
            if val and val > 0 and odds_list[i] != val:
                odds_list[i] = val
                changed = True

        if changed:
            r["odds"] = odds_list
            r["popularities"] = _popularities(odds_list)
            updated += 1

    if updated:
        data.setdefault("metadata", {})["odds_updated_at"] = datetime.now(JST).isoformat()
        fd, tmp = tempfile.mkstemp(dir=PREFETCH_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    print(f"odds updated: {updated}/{len(races)} races ({date_str})")
    return updated > 0


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else datetime.now(JST).strftime("%Y%m%d")
    update(ds)
