"""Scrape real-time odds from netkeiba.com."""

import re
from scrapers.base import fetch_with_retry
from config import NETKEIBA_JRA_BASE, NETKEIBA_NAR_BASE


def fetch_realtime_odds(race_id: str, race_type: str = "jra") -> dict | None:
    """Fetch current win odds for a race from the entry page (shutuba.html).

    The dedicated odds page uses JavaScript rendering, so we scrape
    odds from the entry page which includes them in static HTML for NAR
    and sometimes for JRA.

    Returns:
        Dict with horse_number (int) -> odds (float) mapping, or None.
    """
    if race_type == "nar":
        url = f"{NETKEIBA_NAR_BASE}/race/shutuba.html?race_id={race_id}"
    else:
        url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"

    soup = fetch_with_retry(url, encoding="euc-jp")
    if not soup:
        return None

    odds_map = {}

    for tr in soup.select("tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue

        # Horse number is in td[1]
        num_text = tds[1].get_text(strip=True)
        if not num_text.isdigit():
            continue
        horse_num = int(num_text)

        # Try to find odds - look for Odds_Ninki span or Popular td
        odds_val = None

        # NAR pattern: span.Odds_Ninki
        odds_span = tr.select_one("span.Odds_Ninki")
        if odds_span:
            try:
                odds_val = float(odds_span.get_text(strip=True))
            except ValueError:
                pass

        # Fallback: td.Popular with text that looks like odds
        if odds_val is None:
            pop_td = tr.select_one("td.Popular")
            if pop_td:
                pop_text = pop_td.get_text(strip=True)
                m = re.search(r"(\d+\.?\d*)", pop_text)
                if m:
                    try:
                        odds_val = float(m.group(1))
                    except ValueError:
                        pass

        # Fallback: scan all tds for odds-like value
        if odds_val is None:
            for td in tds:
                text = td.get_text(strip=True)
                if re.match(r"^\d+\.\d+$", text):
                    try:
                        val = float(text)
                        if 1.0 < val < 999.0:
                            odds_val = val
                            break
                    except ValueError:
                        pass

        if odds_val is not None:
            odds_map[horse_num] = odds_val

    return odds_map if odds_map else None
