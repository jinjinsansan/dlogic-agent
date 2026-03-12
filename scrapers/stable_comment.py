"""Scrape stable/trainer comments (厩舎コメント) from keibabook.co.jp.

Requires a paid keibabook webライト account (月額1,100円).
Login session is cached for reuse across requests.
"""

import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Session cache
_session: requests.Session | None = None
_session_ts: float = 0
_SESSION_TTL = 3600  # Re-login every 1 hour

# Credentials from env
_LOGIN_ID = os.getenv("KEIBABOOK_LOGIN_ID", "")
_PASSWORD = os.getenv("KEIBABOOK_PASSWORD", "")

_BASE_URL = "https://p.keibabook.co.jp"
_MOBILE_URL = "https://s.keibabook.co.jp"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Venue name → keibabook venue code mapping (NAR)
VENUE_CODE_MAP = {
    "大井": "10",
    "船橋": "12",
    "浦和": "18",
    "川崎": "19",
    "金沢": "20",
    "佐賀": "23",
    "高知": "26",
    "水沢": "29",
    "盛岡": "30",
    "名古屋": "34",
    "笠松": "35",
    "園田": "38",
    "姫路": "39",
    "門別": "42",
    "帯広": "58",
}

# Venue name → keibabook venue code mapping (JRA)
JRA_VENUE_CODE_MAP = {
    "中山": "06",
    "阪神": "09",
    "東京": "05",
    "京都": "08",
    "小倉": "10",
    "新潟": "04",
    "福島": "03",
    "札幌": "02",
    "函館": "01",
}


def _get_session() -> requests.Session | None:
    """Get or create an authenticated keibabook session."""
    global _session, _session_ts

    if not _LOGIN_ID or not _PASSWORD:
        logger.warning("KEIBABOOK_LOGIN_ID or KEIBABOOK_PASSWORD not set")
        return None

    # Reuse session if still fresh
    if _session and (time.time() - _session_ts) < _SESSION_TTL:
        return _session

    try:
        s = requests.Session()
        s.headers.update({"User-Agent": _USER_AGENT})

        # Get CSRF token
        r = s.get(f"{_BASE_URL}/login/login", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        token_el = soup.select_one("input[name=_token]")
        if not token_el:
            logger.error("keibabook: CSRF token not found on login page")
            return None

        # Login
        login_data = {
            "_token": token_el["value"],
            "referer": "",
            "service": "keibabook",
            "login_id": _LOGIN_ID,
            "pswd": _PASSWORD,
            "autologin": "1",
            "submitbutton": "ログインする",
        }
        r2 = s.post(f"{_BASE_URL}/login/login", data=login_data, timeout=15)
        r2.raise_for_status()

        _session = s
        _session_ts = time.time()
        logger.info("keibabook: login successful")
        return s

    except Exception:
        logger.exception("keibabook: login failed")
        return None


def fetch_stable_comments(keibabook_race_id: str, is_chihou: bool = True) -> dict | None:
    """Fetch stable/trainer comments for a race.

    Args:
        keibabook_race_id: Race ID in keibabook format (e.g. "2026031203110311")
        is_chihou: True for NAR (地方), False for JRA (中央)

    Returns:
        Dict mapping horse_number (int) -> {
            "horse_name": str,
            "mark": str,         # ◎○▲△× (keibabook reporter's mark)
            "status": str,       # e.g. "状態は維持", "良化中"
            "trainer": str,      # trainer name
            "comment": str,      # trainer's comment
        }
        or None if no data.
    """
    s = _get_session()
    if not s:
        return None

    section = "chihou" if is_chihou else "cyuou"
    # JRA uses /danwa/0/, chihou uses /danwa/1/
    danwa_num = "1" if is_chihou else "0"
    url = f"{_BASE_URL}/{section}/danwa/{danwa_num}/{keibabook_race_id}"

    try:
        r = s.get(url, timeout=15)
        r.raise_for_status()
    except Exception:
        logger.exception(f"keibabook: failed to fetch {url}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Check for "page not found" message
    body_text = soup.get_text()
    if "存在しません" in body_text:
        logger.info(f"keibabook: danwa not available for {keibabook_race_id}")
        return None

    result = {}
    for tr in soup.select("tr"):
        danwa_td = tr.select_one("td.danwa")
        if not danwa_td:
            continue

        # Get horse number from td.umaban
        umaban_td = tr.select_one("td.umaban")
        if not umaban_td:
            continue
        umaban_text = umaban_td.get_text(strip=True)
        if not umaban_text.isdigit():
            continue
        horse_number = int(umaban_text)

        # Get horse name from first td.left
        left_tds = tr.select("td.left")
        horse_name = left_tds[0].get_text(strip=True) if left_tds else ""

        # Parse danwa text
        danwa_text = danwa_td.get_text(strip=True)
        parsed = _parse_danwa(danwa_text)

        result[horse_number] = {
            "horse_name": horse_name,
            "mark": parsed["mark"],
            "status": parsed["status"],
            "trainer": parsed["trainer"],
            "comment": parsed["comment"],
        }

    return result if result else None


def _parse_danwa(text: str) -> dict:
    """Parse a danwa cell text into structured data.

    Input format: "○ジューンドラゴン(状態は維持)\n　鈴木啓師――コメント本文"
    """
    mark = ""
    status = ""
    trainer = ""
    comment = ""

    # Extract mark (first char if it's a special symbol)
    if text and text[0] in "◎○▲△×☆":
        mark = text[0]
        text = text[1:]

    # Extract status from parentheses
    m_status = re.search(r"[\(（](.+?)[\)）]", text)
    if m_status:
        status = m_status.group(1)

    # Extract trainer and comment after ――
    m_comment = re.search(r"[\s　]+(.+?)(?:――|ー{2}|──)(.+)", text, re.DOTALL)
    if m_comment:
        trainer = m_comment.group(1).strip()
        comment = m_comment.group(2).strip().replace("\n", " ").replace("\u3000", " ")

    return {"mark": mark, "status": status, "trainer": trainer, "comment": comment}


def fetch_race_id_map(date_str: str, venue: str, is_chihou: bool = True) -> dict[int, str]:
    """Scrape keibabook schedule page to get race_number → keibabook_race_id mapping.

    Args:
        date_str: Date in YYYYMMDD format (e.g. "20260312")
        venue: Venue name in Japanese (e.g. "大井", "中山")
        is_chihou: True for NAR (地方), False for JRA (中央)

    Returns:
        Dict mapping race_number (int) → keibabook_race_id (str)
        e.g. {1: "2026031203010311", 2: "2026031203020311", ...}
    """
    code_map = VENUE_CODE_MAP if is_chihou else JRA_VENUE_CODE_MAP
    venue_code = code_map.get(venue)
    if not venue_code:
        logger.warning(f"keibabook: unknown venue '{venue}'")
        return {}

    s = _get_session()
    if not s:
        return {}

    section = "chihou" if is_chihou else "cyuou"
    url = f"{_MOBILE_URL}/{section}/nittei/{date_str}{venue_code}"

    try:
        r = s.get(url, timeout=15)
        r.raise_for_status()
    except Exception:
        logger.exception(f"keibabook: failed to fetch schedule {url}")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    result = {}

    # Schedule page links: /chihou/syutuba/{race_id} or /cyuou/syutuba/{race_id}
    # Link text is "1R", "2R", etc.
    for a_tag in soup.select("a[href]"):
        href = a_tag.get("href", "")
        m = re.search(r"/(?:chihou|cyuou)/syutuba/(\d{10,16})", href)
        if not m:
            continue
        race_id = m.group(1)

        link_text = a_tag.get_text(strip=True)
        m_race = re.match(r"(\d+)R", link_text)
        if m_race:
            race_num = int(m_race.group(1))
            result[race_num] = race_id

    if result:
        logger.info(f"keibabook: found {len(result)} races for {venue} on {date_str}")
    else:
        logger.warning(f"keibabook: no races found at {url}")

    return result


def fetch_comments_for_race(
    date_str: str, venue: str, race_number: int, is_chihou: bool = True
) -> dict | None:
    """Convenience: resolve race ID from schedule then fetch comments.

    Args:
        date_str: Date in YYYYMMDD format
        venue: Venue name in Japanese
        race_number: Race number (1-12)
        is_chihou: True for NAR, False for JRA

    Returns:
        Same as fetch_stable_comments(), or None.
    """
    race_map = fetch_race_id_map(date_str, venue, is_chihou)
    kb_race_id = race_map.get(race_number)
    if not kb_race_id:
        logger.info(f"keibabook: no race_id for {venue} R{race_number} on {date_str}")
        return None

    return fetch_stable_comments(kb_race_id, is_chihou)
