"""Scrape race results (着順 + 払戻) from netkeiba."""

import logging
import re

from config import NETKEIBA_JRA_BASE, NETKEIBA_NAR_BASE
from scrapers.base import fetch_with_retry

logger = logging.getLogger(__name__)


def fetch_race_result(race_id: str, race_type: str = "jra") -> dict | None:
    """Fetch race result for a given race_id.

    Returns dict with:
        race_id: str
        finishing_order: list[dict]  — [{position, horse_number, horse_name}, ...]
        winner_number: int
        winner_name: str
        win_payout: int  — 単勝払戻金額 (円)
        status: "finished" | "cancelled"
    Or None if page not found / race not yet finished.
    """
    if race_type == "nar":
        url = f"{NETKEIBA_NAR_BASE}/race/result.html?race_id={race_id}"
    else:
        url = f"{NETKEIBA_JRA_BASE}/race/result.html?race_id={race_id}"

    soup = fetch_with_retry(url, encoding="euc-jp", timeout=15)
    if not soup:
        return None

    # --- Parse result table ---
    table = soup.select_one("table.RaceTable01")
    if not table:
        logger.warning(f"No RaceTable01 found for {race_id}")
        return None

    # Select data rows: skip header row (class="Header"), take rows with td.Result_Num
    rows = [tr for tr in table.select("tr") if tr.select("td.Result_Num")]
    if not rows:
        # Fallback: try legacy selector
        rows = table.select("tr.HorseList")
    if not rows:
        logger.info(f"No result rows for {race_id} — race may not be finished")
        return None

    finishing_order = []
    for tr in rows:
        tds = tr.select("td")
        if len(tds) < 4:
            continue

        pos_text = tds[0].get_text(strip=True)
        # Handle non-numeric positions: 中止, 除外, 取消 etc.
        try:
            position = int(pos_text)
        except ValueError:
            position = 0  # DNF / scratched

        try:
            horse_number = int(tds[2].get_text(strip=True))
        except ValueError:
            continue

        horse_name = tds[3].get_text(strip=True)

        finishing_order.append({
            "position": position,
            "horse_number": horse_number,
            "horse_name": horse_name,
        })

    if not finishing_order:
        return None

    # Sort by position (0 = DNF goes to end)
    finishing_order.sort(key=lambda x: (x["position"] == 0, x["position"]))

    # Winner
    winner = finishing_order[0]
    winner_number = winner["horse_number"]
    winner_name = winner["horse_name"]

    # --- Parse payout table (単勝) ---
    win_payout = 0
    pay_back = soup.select_one(".Result_Pay_Back")
    if pay_back:
        payout_tables = pay_back.select("table.Payout_Detail_Table")
        for pt in payout_tables:
            for tr in pt.select("tr"):
                th = tr.select_one("th")
                if th and "単勝" in th.get_text(strip=True):
                    payout_td = tr.select_one("td.Payout")
                    if payout_td:
                        payout_text = payout_td.get_text(strip=True)
                        # Extract first number: "250円" → 250, "1,250円" → 1250
                        m = re.search(r"([\d,]+)円", payout_text)
                        if m:
                            win_payout = int(m.group(1).replace(",", ""))
                    break

    # Build result_json with top 3 for reference
    result_json = {
        "top3": finishing_order[:3],
        "total_horses": len(finishing_order),
    }

    return {
        "race_id": race_id,
        "finishing_order": finishing_order,
        "winner_number": winner_number,
        "winner_name": winner_name,
        "win_payout": win_payout,
        "result_json": result_json,
        "status": "finished",
    }
