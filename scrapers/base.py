"""Common scraper utilities."""

import logging
import time
import requests
from bs4 import BeautifulSoup
from config import REQUEST_TIMEOUT, MAX_RETRIES

logger = logging.getLogger(__name__)


def fetch_with_retry(url: str, encoding: str = "euc-jp", timeout: int = REQUEST_TIMEOUT) -> BeautifulSoup | None:
    """Fetch a URL with retry logic, return parsed BeautifulSoup.

    Returns None on failure (network error, HTTP error, empty response).
    """
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })

            # Check HTTP status code
            if resp.status_code == 404:
                logger.warning(f"HTTP 404: {url}")
                return None  # Page doesn't exist — no retry
            if resp.status_code >= 400:
                logger.warning(f"HTTP {resp.status_code}: {url}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None

            resp.encoding = encoding
            html_text = resp.text

            # Check for empty or suspiciously short response
            if not html_text or len(html_text.strip()) < 100:
                logger.warning(f"Empty or too-short response ({len(html_text)} chars): {url}")
                return None

            return BeautifulSoup(html_text, "lxml")
        except requests.Timeout:
            logger.warning(f"Timeout (attempt {attempt + 1}/{MAX_RETRIES}): {url}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return None
        except Exception as e:
            logger.warning(f"Fetch error (attempt {attempt + 1}/{MAX_RETRIES}): {url} - {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return None
    return None
