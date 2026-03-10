"""Search for a horse on netkeiba.com and return past race results."""

import re
import urllib.parse
from scrapers.base import fetch_with_retry


def search_horse(horse_name: str, max_results: int = 5) -> dict | None:
    """Search for a horse by name and return past race results."""
    # Use horse_list search (works without JS)
    encoded = urllib.parse.quote(horse_name.encode("euc-jp"))
    search_url = f"https://db.netkeiba.com/?pid=horse_list&word={encoded}&match=partial"

    soup = fetch_with_retry(search_url, encoding="euc-jp")
    if not soup:
        return None

    # Find horse ID from search results
    horse_id = None
    for a_tag in soup.select("a[href*='/horse/']"):
        href = a_tag.get("href", "")
        match = re.search(r"/horse/(\d{10})", href)
        if match:
            horse_id = match.group(1)
            break

    if not horse_id:
        return None

    # Fetch the result page (has full race history table)
    result_url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    result_soup = fetch_with_retry(result_url, encoding="euc-jp")
    if not result_soup:
        return None

    # Get horse name from main page
    name_el = result_soup.select_one("div.horse_title h1, h1")
    actual_name = name_el.get_text(strip=True) if name_el else horse_name

    return _parse_result_table(result_soup, actual_name, max_results)


def _parse_result_table(soup, horse_name: str, max_results: int) -> dict:
    """Parse the db_h_race_results table.

    Column layout (29 cols):
    [0] date, [1] venue, [2] weather, [3] race_number, [4] race_name,
    [5] ?, [6] headcount, [7] post, [8] horse_number, [9] odds,
    [10] popularity, [11] position, [12] jockey, [13] weight,
    [14] distance, [15] ?, [16] track_condition, [17] ?,
    [18] time, [19] margin
    """
    table = soup.select_one("table.db_h_race_results")
    if not table:
        return {"horse_name": horse_name, "past_races": []}

    races = []
    rows = table.select("tr")

    for row in rows[1:]:  # Skip header
        tds = row.find_all("td")
        if len(tds) < 19:
            continue

        try:
            date = tds[0].get_text(strip=True)
            if not re.match(r"\d{4}", date):
                continue

            races.append({
                "date": date,
                "venue": tds[1].get_text(strip=True),
                "race_name": tds[4].get_text(strip=True),
                "headcount": tds[6].get_text(strip=True),
                "position": tds[11].get_text(strip=True),
                "jockey": tds[12].get_text(strip=True),
                "weight": tds[13].get_text(strip=True),
                "distance": tds[14].get_text(strip=True),
                "track_condition": tds[16].get_text(strip=True),
                "time": tds[18].get_text(strip=True),
                "margin": tds[19].get_text(strip=True) if len(tds) > 19 else "",
            })

            if len(races) >= max_results:
                break
        except (IndexError, AttributeError):
            continue

    return {
        "horse_name": horse_name,
        "past_races": races,
    }
