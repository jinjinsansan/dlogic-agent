"""Scrape real-time odds from netkeiba.com.

Uses Lightpanda (fast headless browser) with Playwright fallback.
"""

import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from scrapers.base import fetch_with_retry
from config import NETKEIBA_JRA_BASE, NETKEIBA_NAR_BASE

logger = logging.getLogger(__name__)

LIGHTPANDA_BIN = shutil.which("lightpanda") or "/usr/local/bin/lightpanda"
LIGHTPANDA_TIMEOUT = 20  # seconds per page
LIGHTPANDA_WORKERS = 6


# ---------------------------------------------------------------------------
# Lightpanda-based JRA odds (fast, subprocess)
# ---------------------------------------------------------------------------

def _parse_odds_from_html(html: str) -> dict[int, float]:
    """Extract odds from HTML containing span[id^=odds-1_] elements."""
    odds_map = {}
    for m in re.finditer(r'odds-1_(\d+)"[^>]*>([\d.]+)', html):
        try:
            odds_map[int(m.group(1))] = float(m.group(2))
        except ValueError:
            pass
    return odds_map


def _fetch_jra_odds_lightpanda(race_id: str) -> dict[int, float] | None:
    """Fetch a single JRA race's odds using Lightpanda."""
    url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"
    try:
        result = subprocess.run(
            [LIGHTPANDA_BIN, "fetch", "--dump", "html",
             "--http_timeout", str(LIGHTPANDA_TIMEOUT * 1000), url],
            capture_output=True, text=True,
            timeout=LIGHTPANDA_TIMEOUT + 10,
        )
        odds = _parse_odds_from_html(result.stdout)
        return odds if odds else None
    except Exception:
        logger.debug(f"Lightpanda fetch failed: {race_id}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Playwright fallback
# ---------------------------------------------------------------------------

def _fetch_jra_odds_playwright(race_id: str) -> dict[int, float] | None:
    """Fetch JRA odds using headless Chromium (Playwright). Single race."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            try:
                page.wait_for_function(
                    """() => {
                        const spans = document.querySelectorAll("span[id^=odds-1_]");
                        return spans.length > 0 && spans[0].textContent.trim() !== "---.-";
                    }""",
                    timeout=10000,
                )
            except Exception:
                browser.close()
                return None

            odds_map = {}
            for span in page.query_selector_all("span[id^=odds-1_]"):
                span_id = span.get_attribute("id") or ""
                text = span.inner_text().strip()
                parts = span_id.split("_")
                if len(parts) < 2:
                    continue
                try:
                    horse_num = int(parts[1])
                except ValueError:
                    continue
                if text and text != "---.-":
                    try:
                        odds_map[horse_num] = float(text)
                    except ValueError:
                        pass

            browser.close()
            return odds_map if odds_map else None
    except Exception:
        logger.debug(f"Playwright JRA odds failed for {race_id}", exc_info=True)
        return None


def _fetch_jra_odds_playwright_batch(race_ids: list[str]) -> dict[str, dict[int, float]]:
    """Fetch odds for JRA races using Playwright (one browser session)."""
    if not race_ids:
        return {}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}

    results = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            for race_id in race_ids:
                url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_function(
                        """() => {
                            const spans = document.querySelectorAll("span[id^=odds-1_]");
                            return spans.length > 0 && spans[0].textContent.trim() !== "---.-";
                        }""",
                        timeout=10000,
                    )

                    odds_map = {}
                    for span in page.query_selector_all("span[id^=odds-1_]"):
                        span_id = span.get_attribute("id") or ""
                        text = span.inner_text().strip()
                        parts = span_id.split("_")
                        if len(parts) < 2:
                            continue
                        try:
                            horse_num = int(parts[1])
                        except ValueError:
                            continue
                        if text and text != "---.-":
                            try:
                                odds_map[horse_num] = float(text)
                            except ValueError:
                                pass

                    if odds_map:
                        results[race_id] = odds_map
                except Exception:
                    logger.debug(f"Playwright batch failed: {race_id}", exc_info=True)

            browser.close()
    except Exception:
        logger.exception("Playwright batch session failed")

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_realtime_odds(race_id: str, race_type: str = "jra") -> dict | None:
    """Fetch current win odds for a race.

    For JRA: uses Lightpanda (fast) with Playwright fallback.
    For NAR: scrapes from shutuba.html (odds in static HTML).

    Returns:
        Dict with horse_number (int) -> odds (float) mapping, or None.
    """
    if race_type != "nar":
        # JRA: try Lightpanda first, then Playwright
        odds = _fetch_jra_odds_lightpanda(race_id)
        if odds:
            logger.info(f"JRA realtime odds via Lightpanda: {race_id} -> {len(odds)} horses")
            return odds

        # Fallback to Playwright
        odds = _fetch_jra_odds_playwright(race_id)
        if odds:
            logger.info(f"JRA realtime odds via Playwright: {race_id} -> {len(odds)} horses")
        return odds

    # NAR: HTML scraping (odds are in static HTML)
    url = f"{NETKEIBA_NAR_BASE}/race/shutuba.html?race_id={race_id}"
    soup = fetch_with_retry(url, encoding="euc-jp")
    if not soup:
        return None

    odds_map = {}

    for tr in soup.select("tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue

        num_text = tds[1].get_text(strip=True)
        if not num_text.isdigit():
            continue
        horse_num = int(num_text)

        odds_val = None

        # NAR pattern: span.Odds_Ninki
        odds_span = tr.select_one("span.Odds_Ninki")
        if odds_span:
            try:
                odds_val = float(odds_span.get_text(strip=True))
            except ValueError:
                pass

        # Fallback: td.Popular containing numeric odds
        if odds_val is None:
            pop_td = tr.select_one("td.Txt_R.Popular")
            if pop_td:
                pop_text = pop_td.get_text(strip=True)
                m = re.search(r"(\d+\.?\d*)", pop_text)
                if m:
                    try:
                        odds_val = float(m.group(1))
                    except ValueError:
                        pass

        if odds_val is not None:
            odds_map[horse_num] = odds_val

    return odds_map if odds_map else None


def fetch_jra_odds_batch(race_ids: list[str]) -> dict[str, dict]:
    """Fetch odds for multiple JRA races.

    Strategy: Lightpanda parallel first, Playwright fallback for failures.
    Used by prefetch to efficiently get odds for all races at once.
    """
    if not race_ids:
        return {}

    # --- Phase 1: Lightpanda parallel fetch ---
    results = {}
    failed_ids = []

    with ThreadPoolExecutor(max_workers=LIGHTPANDA_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_jra_odds_lightpanda, rid): rid
            for rid in race_ids
        }
        for future in as_completed(futures):
            rid = futures[future]
            try:
                odds = future.result()
                if odds:
                    results[rid] = odds
                else:
                    failed_ids.append(rid)
            except Exception:
                failed_ids.append(rid)

    logger.info(
        f"Lightpanda batch: {len(results)}/{len(race_ids)} OK, "
        f"{len(failed_ids)} failed"
    )

    # --- Phase 2: Playwright fallback for failures ---
    if failed_ids:
        logger.info(f"Playwright fallback for {len(failed_ids)} races")
        fallback = _fetch_jra_odds_playwright_batch(failed_ids)
        results.update(fallback)
        logger.info(
            f"Playwright fallback: {len(fallback)}/{len(failed_ids)} recovered"
        )

    return results
