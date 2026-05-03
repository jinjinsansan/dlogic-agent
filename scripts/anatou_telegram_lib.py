"""穴党AI参謀チャンネル共通ライブラリ.

別Telegram Botを使うため、既存のADMIN系envとは独立した
ANATOU_* 環境変数を読む。
"""
import logging
import os
import shlex
import subprocess
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


def _split_for_telegram(text: str, limit: int = 3300) -> list[str]:
    """Split text into chunks well under Telegram's 4096-char limit.

    Splits on blank-line boundaries first, then single newlines, then hard cut.
    Limit is conservative (3300) to leave room for HTML entity expansion
    (& → &amp; etc.) and the (n/m) suffix added by send_telegram_long.
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
    最終 send 直前に文字数を再検証し、もし 4000 を超えていたら hard cut でさらに分割する
    (HTML 実体展開等で想定外に膨らんだケースの安全網)。
    """
    chunks = _split_for_telegram(text)
    # 安全網: 各チャンクが 4000 を超えていたら hard cut で再分割
    safe_chunks: list[str] = []
    HARD_LIMIT = 4000
    for chunk in chunks:
        while len(chunk) > HARD_LIMIT:
            safe_chunks.append(chunk[:HARD_LIMIT])
            chunk = chunk[HARD_LIMIT:]
        safe_chunks.append(chunk)
    n = len(safe_chunks)
    for i, chunk in enumerate(safe_chunks, 1):
        suffix = f"\n\n<i>（{i}/{n}）</i>" if n > 1 else ""
        if not send_telegram(chunk + suffix, disable_preview=disable_preview):
            logger.error(f"send_telegram_long: failed at chunk {i}/{n} (chunk_len={len(chunk)})")
            return False
        if i < n and sleep_between > 0:
            time.sleep(sleep_between)
    return True


def forward_to_jinsanclaedbot(text: str) -> bool:
    """OpenClaw VPS の @jinsanclaedbot に半自動購入確認 prompt 付きで予想を転送.

    SSH 経由で hermes VPS の openclaw agent CLI を呼び、main agent (Sonnet 4-6)
    に inject する。クローが指示通り Telegram で仁さんへ転送 → 仁さんが OK 返信で
    SPAT4/即PAT 購入開始（AGENTS.md 馬券購入ガード適用）。

    既存 ANATOU 配信に影響しないよう、失敗しても例外は出さず False を返す。
    """
    try:
        host = os.environ.get('OPENCLAW_SSH_HOST', 'hermes@210.131.222.240')
        chat_id = os.environ.get('OPENCLAW_TG_CHAT_ID', '197618639')
        agent = os.environ.get('OPENCLAW_AGENT', 'main')

        inject_message = (
            "あなたは何もせず、以下のテキストを応答本文としてそのまま"
            "ユーザーに返信してください（前置きや説明は一切不要）：\n\n"
            "【競馬GANTZ 自動取得】\n"
            f"{text}\n\n"
            "購入準備できました。OK と返信で SPAT4/即PAT 購入を開始します。"
        )

        remote_cmd = (
            f"~/.npm-global/bin/openclaw agent "
            f"--agent {shlex.quote(agent)} "
            f"--message {shlex.quote(inject_message)} "
            f"--deliver "
            f"--reply-channel telegram "
            f"--reply-to {shlex.quote(chat_id)}"
        )

        cmd = [
            'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            host, remote_cmd,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            logger.info(f"forward to jinsanclaedbot ok (text_len={len(text)})")
            return True
        logger.warning(
            f"forward to jinsanclaedbot failed: rc={result.returncode} "
            f"stderr={result.stderr[:300]}"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("forward to jinsanclaedbot timeout")
        return False
    except Exception as e:
        logger.warning(f"forward to jinsanclaedbot exception: {e}")
        return False


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
