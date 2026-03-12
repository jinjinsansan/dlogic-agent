"""Scrape training comments and evaluations from netkeiba.com oikiri page (JRA only)."""

import logging
from scrapers.base import fetch_with_retry
from config import NETKEIBA_JRA_BASE

logger = logging.getLogger(__name__)


def fetch_training_comments(race_id: str) -> dict | None:
    """Fetch training evaluations and stable comments for a JRA race.

    Scrapes two pages:
    1. Default oikiri page: short critic + rank (A-D) for ALL horses
    2. type=2 page: detailed reviewer comments for SOME horses

    Returns:
        Dict with horse_number (int) -> {
            "critic": str,   # e.g. "好調子", "気配平凡"
            "rank": str,     # e.g. "B", "C"
            "comment": str,  # detailed comment (may be empty)
        } mapping, or None if no data.
    """
    base_url = f"{NETKEIBA_JRA_BASE}/race/oikiri.html?race_id={race_id}"

    # Step 1: Default page — short evaluations for all horses
    soup = fetch_with_retry(base_url, encoding="euc-jp")
    if not soup:
        return None

    result = {}

    for row in soup.select("tr.HorseList"):
        tds = row.select("td")
        num = _extract_horse_number(tds)
        if num is None:
            continue

        critic = ""
        rank = ""

        for td in tds:
            cls = td.get("class", [])
            if "Training_Critic" in cls:
                critic = td.get_text(strip=True)
            elif any(c.startswith("Rank_") for c in cls):
                rank = td.get_text(strip=True)

        if critic or rank:
            result[num] = {"critic": critic, "rank": rank, "comment": ""}

    if not result:
        return None

    # Step 2: type=2 page — detailed comments for some horses
    soup2 = fetch_with_retry(f"{base_url}&type=2", encoding="euc-jp")
    if soup2:
        for row in soup2.select("tr.HorseList"):
            tds = row.select("td")
            num = _extract_horse_number(tds)
            if num is None:
                continue

            for td in tds:
                cls = td.get("class", [])
                if "TrainingReview_Cell" in cls:
                    comment = td.get_text(strip=True)
                    if comment and num in result:
                        result[num]["comment"] = comment
                    elif comment:
                        result[num] = {"critic": "", "rank": "", "comment": comment}

    return result if result else None


def _extract_horse_number(tds) -> int | None:
    """Extract horse number from a row's td list."""
    for td in tds:
        cls = td.get("class", [])
        if any("Umaban" in c for c in cls):
            text = td.get_text(strip=True)
            if text.isdigit():
                return int(text)
    return None
