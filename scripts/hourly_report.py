#!/usr/bin/env python3
"""Hourly usage report — sends stats to admin Telegram.

Parses journalctl logs from the last hour and sends a summary.
Run via cron: 0 * * * *

Metrics:
- Unique users (LINE + Web + MYBOT)
- Message counts by channel
- Claude API calls & cache hits
- Popular tools used
- New user registrations
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')
sys.path.insert(0, PROJECT_DIR)

# Load .env.local
env_path = os.path.join(PROJECT_DIR, '.env.local')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_TELEGRAM_CHAT_ID", "197618639")

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _get_vpn_status() -> dict:
    status = {
        "wg_connected": False,
        "handshake_age": None,
        "netkeiba_code": "-",
    }

    try:
        result = subprocess.run(
            ["wg", "show", "wg0", "latest-handshakes"],
            capture_output=True, text=True, timeout=5,
        )
        line = result.stdout.strip().split()
        if len(line) >= 2:
            ts = int(line[-1])
            if ts > 0:
                age = int(time.time() - ts)
                status["handshake_age"] = age
                status["wg_connected"] = age < 180
    except Exception:
        pass

    try:
        resp = subprocess.run(
            [
                "curl", "-4", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                "--connect-timeout", "6", "--max-time", "10",
                "https://race.netkeiba.com/race/shutuba.html?race_id=202606020801",
            ],
            capture_output=True, text=True, timeout=12,
        )
        status["netkeiba_code"] = resp.stdout.strip() or "-"
    except Exception:
        pass

    return status


def _get_logs(service: str, since_minutes: int = 60) -> str:
    """Get journalctl logs for the past N minutes."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", service, f"--since={since_minutes} min ago", "--no-pager"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout
    except Exception as e:
        logger.error(f"Failed to get logs: {e}")
        return ""


def _parse_linebot_logs(logs: str) -> dict:
    """Parse dlogic-linebot logs into metrics."""
    metrics = {
        "line_messages": 0,
        "web_chat_requests": 0,
        "mybot_web_requests": 0,
        "mybot_line_webhooks": 0,
        "claude_api_calls": 0,
        "cache_hits": 0,
        "template_routes": 0,
        "memory_extractions": 0,
        "tools_used": Counter(),
        "line_users": set(),
        "web_users": set(),
        "new_follows": 0,
        "errors": 0,
    }

    for line in logs.split('\n'):
        # LINE messages: [MSG] display_name (Uxxxxxx): text
        if '[MSG]' in line:
            metrics["line_messages"] += 1
            m = re.search(r'\(U([a-f0-9]+)\)', line)
            if m:
                metrics["line_users"].add(m.group(1)[:10])

        # Web chat
        elif 'POST /api/chat/' in line and '/sessions' not in line:
            metrics["web_chat_requests"] += 1

        # MYBOT web
        elif 'POST /api/mybot/chat' in line:
            metrics["mybot_web_requests"] += 1

        # MYBOT LINE webhooks
        elif 'POST /mybot/webhook/' in line:
            metrics["mybot_line_webhooks"] += 1

        # Claude API calls
        elif 'POST https://api.anthropic.com/v1/messages' in line:
            metrics["claude_api_calls"] += 1

        # Cache hits
        elif 'ResponseCache HIT' in line or 'cache hit' in line.lower():
            metrics["cache_hits"] += 1

        # Template routes (Claude skipped)
        elif 'Template route handled' in line:
            metrics["template_routes"] += 1

        # Tool executions
        elif 'Executing tool:' in line:
            m = re.search(r'Executing tool: (\w+)', line)
            if m:
                metrics["tools_used"][m.group(1)] += 1
        elif 'MYBOT executing tool:' in line:
            m = re.search(r'MYBOT executing tool: (\w+)', line)
            if m:
                metrics["tools_used"][m.group(1)] += 1

        # Memory extractions
        elif 'New memories:' in line:
            metrics["memory_extractions"] += 1

        # New follows
        elif 'New authenticated web session' in line or 'Rich menu linked' in line:
            pass  # Not reliable for counting
        elif 'POST /callback' in line:
            pass  # LINE webhook (includes follow events)

        # Errors
        elif 'ERROR' in line or 'Exception' in line or 'Traceback' in line:
            metrics["errors"] += 1

    return metrics


def _format_report(metrics: dict) -> str:
    """Format metrics into a Telegram message."""
    now = datetime.now(JST)
    hour_str = now.strftime("%H:%M")
    date_str = now.strftime("%m/%d")

    vpn_status = _get_vpn_status()

    total_requests = (
        metrics["line_messages"]
        + metrics["web_chat_requests"]
        + metrics["mybot_web_requests"]
        + metrics["mybot_line_webhooks"]
    )

    # Cache efficiency
    total_processed = metrics["claude_api_calls"] + metrics["cache_hits"] + metrics["template_routes"]
    if total_processed > 0:
        cache_rate = (metrics["cache_hits"] + metrics["template_routes"]) / total_processed * 100
    else:
        cache_rate = 0

    # Cost estimate (Haiku 4.5: ~$0.013/call avg)
    est_cost = metrics["claude_api_calls"] * 0.013

    lines = [
        f"📊 Dlogic 利用レポート ({date_str} {hour_str})",
        f"━━━━━━━━━━━━━━",
        "",
        f"👥 ユニークユーザー",
        f"  LINE: {len(metrics['line_users'])}人",
        f"  Web: (セッション数で集計)",
        "",
        f"💬 リクエスト数 (1h): {total_requests}",
        f"  LINE Bot: {metrics['line_messages']}",
        f"  Webチャット: {metrics['web_chat_requests']}",
        f"  MYBOT Web: {metrics['mybot_web_requests']}",
        f"  MYBOT LINE: {metrics['mybot_line_webhooks']}",
        "",
        f"🤖 Claude API",
        f"  呼び出し: {metrics['claude_api_calls']}回",
        f"  キャッシュHIT: {metrics['cache_hits']}回",
        f"  テンプレート: {metrics['template_routes']}回",
        f"  節約率: {cache_rate:.0f}%",
        f"  推定コスト: ${est_cost:.2f}",
        "",
    ]

    # Top tools
    if metrics["tools_used"]:
        lines.append("🔧 使用ツール TOP5")
        for tool, count in metrics["tools_used"].most_common(5):
            lines.append(f"  {tool}: {count}回")
        lines.append("")

    if metrics["memory_extractions"] > 0:
        lines.append(f"🧠 メモリ抽出: {metrics['memory_extractions']}回")

    if metrics["errors"] > 0:
        lines.append(f"⚠️ エラー: {metrics['errors']}件")

    lines.append("")
    lines.append("🛡️ VPN")
    if vpn_status["wg_connected"]:
        hs = vpn_status["handshake_age"]
        hs_str = f"{hs}s" if hs is not None else "-"
        lines.append(f"  WireGuard: OK (handshake {hs_str})")
    else:
        lines.append("  WireGuard: NG")
    lines.append(f"  netkeiba: HTTP {vpn_status['netkeiba_code']}")

    # Quiet hour indicator
    if total_requests == 0:
        lines.append("😴 この1時間はリクエストなし")

    return "\n".join(lines)


def _send_telegram(text: str):
    """Send message to admin Telegram."""
    import requests
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN or ADMIN_CHAT_ID not set")
        return

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ADMIN_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": True,  # Silent notification
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Report sent to Telegram")
        else:
            logger.error(f"Telegram API error: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Failed to send Telegram: {e}")


def main():
    logs = _get_logs("dlogic-linebot", since_minutes=60)
    if not logs:
        logger.info("No logs found, skipping report")
        return

    metrics = _parse_linebot_logs(logs)
    report = _format_report(metrics)
    logger.info(f"Report:\n{report}")
    _send_telegram(report)


if __name__ == "__main__":
    main()
