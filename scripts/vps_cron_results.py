#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPS日次結果取得: JRA/NAR全レース結果を取得し、予想の的中判定を行う
毎日 21:00 JST (JRA) / 22:00 JST (NAR) に systemd timer から実行

処理内容:
1. check_engine_results.py — エンジン的中率計算 + race_results保存 + 予想判定
2. fetch_results.py — 未判定の予想を追加で処理
"""

import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# .env.local を読み込み
env_path = os.path.join(PROJECT_DIR, '.env.local')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('ADMIN_TELEGRAM_CHAT_ID', os.environ.get('TELEGRAM_CHAT_ID', ''))
PYTHON = sys.executable
JST = timezone(timedelta(hours=9))


def setup_logging():
    today = datetime.now(JST).strftime('%Y%m%d')
    log_file = os.path.join(LOG_DIR, f'cron_results_{today}.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )
    return logging.getLogger(__name__)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception:
        pass


def run_check_engine_results(date_str, logger):
    """check_engine_results.py を実行 — エンジン的中率 + race_results保存 + 予想判定"""
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, 'check_engine_results.py'), date_str]
    logger.info(f"エンジン結果チェック: {date_str}")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_DIR,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=1800,
        )
        # Count results from output
        races_done = 0
        engine_saved = 0
        for line in result.stdout.split('\n'):
            if 'races,' in line and 'engine records' in line:
                logger.info(f"  {line.strip()}")
            elif '✅' in line or '🔶' in line or '❌' in line:
                engine_saved += 1
            elif 'Saved to race_results' in line:
                races_done += 1

        logger.info(f"  エンジン結果: {races_done} races saved, {engine_saved} engine records")
        return races_done, engine_saved, result.returncode
    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（30分）")
        return 0, 0, -1
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return 0, 0, -1


def run_fetch_results(date_str, logger):
    """fetch_results.py を実行 — 未判定の予想を追加処理"""
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, 'fetch_results.py'), '--date', formatted_date]
    logger.info(f"予想結果取得: {formatted_date}")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_DIR,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=1800,
        )
        fetched = 0
        judged = 0
        for line in result.stdout.split('\n'):
            if 'results fetched' in line:
                logger.info(f"  {line.strip()}")
            elif 'Resolved via' in line:
                fetched += 1
            elif 'Updated stats' in line:
                judged += 1

        logger.info(f"  追加処理: {fetched} resolved, {judged} stats updated")
        return fetched, judged, result.returncode
    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（30分）")
        return 0, 0, -1
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return 0, 0, -1


def run_golden_snapshot(date_str, logger):
    """golden-pattern スナップショット保存 — 後日レビュー用"""
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, 'snapshot_golden_pattern.py'), date_str]
    logger.info(f"goldenスナップショット保存: {date_str}")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_DIR,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=300,
        )
        for line in (result.stdout or '').strip().split('\n')[-3:]:
            if line:
                logger.info(f"  {line.strip()}")
        return result.returncode
    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（5分）")
        return -1
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return -1


def main():
    logger = setup_logging()
    now = datetime.now(JST)
    date_str = now.strftime('%Y%m%d')

    logger.info("=" * 60)
    logger.info("日次結果取得 + 的中判定")
    logger.info("=" * 60)
    logger.info(f"対象日: {now.strftime('%Y-%m-%d')}")

    # Step 1: エンジン結果チェック (prefetchベース — 全レース対象)
    logger.info("\n[Step 1] エンジン結果チェック")
    races_done, engine_saved, rc1 = run_check_engine_results(date_str, logger)

    # Step 2: 追加の予想結果取得 (ユーザー/MYBOT予想の未判定分)
    logger.info("\n[Step 2] 追加の予想結果取得")
    fetched, judged, rc2 = run_fetch_results(date_str, logger)

    # Step 3: goldenスナップショット (後日レビュー用)
    logger.info("\n[Step 3] goldenスナップショット")
    rc3 = run_golden_snapshot(date_str, logger)

    # Telegram通知
    status = "OK" if rc1 == 0 and rc2 == 0 else "NG"
    msg = (
        f"📊 <b>日次結果取得 {status}</b>\n"
        f"日付: {now.strftime('%m/%d')}\n"
        f"{'─' * 20}\n"
        f"エンジン: {races_done}R保存, {engine_saved}件記録\n"
        f"予想判定: +{fetched}件取得, {judged}人更新\n"
        f"goldenスナップショット: {'OK' if rc3 == 0 else 'NG'}"
    )
    send_telegram(msg)

    logger.info(f"\n完了: engine={races_done}R/{engine_saved}件, fetch=+{fetched}/{judged}人, snapshot={'OK' if rc3 == 0 else 'NG'}")
    return 0 if rc1 == 0 and rc2 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
