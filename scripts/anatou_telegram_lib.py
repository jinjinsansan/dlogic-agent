"""穴党AI参謀チャンネル共通ライブラリ.

別Telegram Botを使うため、既存のADMIN系envとは独立した
ANATOU_* 環境変数を読む。
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

JST = timezone(timedelta(hours=9))
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    """Read .env.local for tokens."""
    env_path = os.path.join(PROJECT_DIR, '.env.local')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env()

ANATOU_BOT_TOKEN = os.environ.get('ANATOU_TELEGRAM_BOT_TOKEN', '')
ANATOU_CHAT_ID = os.environ.get('ANATOU_TELEGRAM_CHAT_ID', '')
API_BASE = os.environ.get('GOLDEN_API_BASE', 'http://127.0.0.1:5000')

logger = logging.getLogger(__name__)


def fetch_pattern(date_str: str) -> dict | None:
    """Call the local golden-pattern API for the given YYYYMMDD."""
    url = f"{API_BASE}/api/data/golden-pattern/today"
    try:
        resp = requests.get(url, params={"date": date_str, "race_type": "both"}, timeout=300)
    except Exception as e:
        logger.error(f"API fetch failed: {e}")
        return None
    if resp.status_code != 200:
        logger.error(f"API non-200 ({resp.status_code}): {resp.text[:200]}")
        return None
    return resp.json()


def send_telegram(text: str, disable_preview: bool = True) -> bool:
    """Send HTML message to the 穴党AI参謀 channel."""
    if not ANATOU_BOT_TOKEN or not ANATOU_CHAT_ID:
        logger.error("ANATOU_TELEGRAM_BOT_TOKEN or ANATOU_TELEGRAM_CHAT_ID not set")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{ANATOU_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ANATOU_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error(f"Telegram error: {resp.status_code} {resp.text[:300]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def _split_for_telegram(text: str, limit: int = 3800) -> list[str]:
    """Split text into chunks under Telegram's 4096-char limit.

    Splits on blank-line boundaries first, then single newlines, then hard cut.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        candidate = (cur + "\n\n" + block) if cur else block
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        # Block alone exceeds limit → split by lines
        if len(block) > limit:
            line_buf = ""
            for line in block.split("\n"):
                cand2 = (line_buf + "\n" + line) if line_buf else line
                if len(cand2) <= limit:
                    line_buf = cand2
                else:
                    if line_buf:
                        chunks.append(line_buf)
                    # Single line still too long → hard cut
                    while len(line) > limit:
                        chunks.append(line[:limit])
                        line = line[limit:]
                    line_buf = line
            cur = line_buf
        else:
            cur = block
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram_long(text: str, disable_preview: bool = True, sleep_between: float = 1.0) -> bool:
    """Send a possibly long HTML message, split across multiple Telegram messages.

    Adds (n/m) suffix when split. Returns False on first send failure.
    """
    chunks = _split_for_telegram(text)
    n = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        suffix = f"\n\n<i>（{i}/{n}）</i>" if n > 1 else ""
        if not send_telegram(chunk + suffix, disable_preview=disable_preview):
            logger.error(f"send_telegram_long: failed at chunk {i}/{n}")
            return False
        if i < n and sleep_between > 0:
            time.sleep(sleep_between)
    return True


def date_yyyymmdd_today() -> str:
    return datetime.now(JST).strftime("%Y%m%d")


def date_yyyymmdd_yesterday() -> str:
    return (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")


def date_display(yyyymmdd: str) -> str:
    """20260424 → '4/24(水)'"""
    if len(yyyymmdd) != 8:
        return yyyymmdd
    try:
        d = datetime.strptime(yyyymmdd, "%Y%m%d")
        wd = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
        return f"{d.month}/{d.day}({wd})"
    except Exception:
        return yyyymmdd


def setup_logging():
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        level=logging.INFO,
    )
    return logging.getLogger(os.path.basename(__file__))
