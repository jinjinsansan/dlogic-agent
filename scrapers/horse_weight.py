"""Scrape real-time horse weights from netkeiba.com shutuba page."""

import logging
import re
from scrapers.base import fetch_with_retry
from config import NETKEIBA_JRA_BASE, NETKEIBA_NAR_BASE

logger = logging.getLogger(__name__)


def fetch_horse_weights(race_id: str, race_type: str = "jra") -> dict | None:
    """Fetch horse body weights from the entry page (shutuba.html).

    Horse weights are published on race day after weigh-in (typically morning).
    Before weigh-in, the weight column is empty.

    Returns:
        Dict with horse_number (int) -> {"weight": int, "diff": str} mapping,
        or None if no data available.
        Example: {1: {"weight": 480, "diff": "+4"}, 2: {"weight": 456, "diff": "-2"}}
    """
    if race_type == "nar":
        url = f"{NETKEIBA_NAR_BASE}/race/shutuba.html?race_id={race_id}"
    else:
        url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"

    soup = fetch_with_retry(url, encoding="euc-jp")
    if not soup:
        return None

    weight_map = {}

    for tr in soup.select("tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue

        # Horse number is in td[1]
        num_text = tds[1].get_text(strip=True)
        if not num_text.isdigit():
            continue
        horse_num = int(num_text)

        # Horse weight: look for td with class containing "Weight" or "Taiju"
        weight_val = None
        diff_val = ""

        # Pattern 1: td.Weight or span with weight-like text "480(+4)"
        weight_td = tr.select_one("td.Weight")
        if weight_td:
            weight_text = weight_td.get_text(strip=True)
            weight_val, diff_val = _parse_weight_text(weight_text)

        # Pattern 2: scan for weight pattern in all tds
        if weight_val is None:
            for td in tds:
                text = td.get_text(strip=True)
                w, d = _parse_weight_text(text)
                if w is not None:
                    weight_val = w
                    diff_val = d
                    break

        if weight_val is not None:
            weight_map[horse_num] = {"weight": weight_val, "diff": diff_val}

    return weight_map if weight_map else None


def _parse_weight_text(text: str) -> tuple:
    """Parse weight text like '480(+4)', '456(-2)', '470(0)', '480'.

    Returns (weight_int, diff_str) or (None, '') if not parseable.
    """
    if not text:
        return None, ""

    # Pattern: "480(+4)" or "480（+4）" (full-width parens)
    m = re.match(r"(\d{3,4})\s*[\(（]\s*([+\-＋－]?\d+)\s*[\)）]", text)
    if m:
        weight = int(m.group(1))
        diff_raw = m.group(2)
        # Normalize full-width signs
        diff_raw = diff_raw.replace("＋", "+").replace("－", "-")
        if 300 <= weight <= 700:
            diff_str = diff_raw if diff_raw.startswith(("+", "-")) else f"+{diff_raw}"
            if diff_str == "+0":
                diff_str = "0"
            return weight, diff_str

    # Pattern: just "480" (no diff available)
    m2 = re.match(r"^(\d{3,4})$", text.strip())
    if m2:
        weight = int(m2.group(1))
        if 300 <= weight <= 700:
            return weight, ""

    return None, ""
