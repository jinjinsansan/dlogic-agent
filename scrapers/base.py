"""Common scraper utilities."""

import time
import requests
from bs4 import BeautifulSoup
from config import REQUEST_TIMEOUT, MAX_RETRIES


def fetch_with_retry(url: str, encoding: str = "euc-jp", timeout: int = REQUEST_TIMEOUT) -> BeautifulSoup | None:
    """Fetch a URL with retry logic, return parsed BeautifulSoup."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp.encoding = encoding
            return BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"Fetch failed after {MAX_RETRIES} attempts: {url} - {e}")
                return None
