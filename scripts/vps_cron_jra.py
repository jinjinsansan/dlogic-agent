#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPS日次プリフェッチ: JRA（中央競馬）
毎日 10:30 JST に systemd timer から実行

JRAの出馬表は前日10:30頃に公開される。
翌日にJRA開催がなければ空振り（正常終了）。
※稀に月曜開催もあるため、曜日フィルタなしで毎日実行。
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')
PREFETCH_DIR = os.path.join(PROJECT_DIR, 'data', 'prefetch')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(PREFETCH_DIR, exist_ok=True)

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
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
PYTHON = sys.executable
JST = timezone(timedelta(hours=9))


def setup_logging():
    today = datetime.now(JST).strftime('%Y%m%d')
    log_file = os.path.join(LOG_DIR, f'cron_jra_{today}.log')
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


def run_prefetch_jra(date_str, logger):
    """JRAのみプリフェッチ"""
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, 'prefetch_races.py'), date_str, '--jra']
    logger.info(f"実行: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_DIR,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=600,
        )
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and ('保存' in line or 'レース数' in line or '会場' in line or 'FAIL' in line or '見つかりません' in line):
                logger.info(f"  {line}")

        output_file = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
        if not os.path.exists(output_file):
            logger.info("  JRAレースなし（非開催日）")
            return None, 0, []

        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        races = data.get('races', [])
        jra_races = [r for r in races if not r.get('is_local', True)]
        jra_count = len(jra_races)

        if jra_count == 0:
            logger.info("  JRAレースなし（非開催日）")
            return None, 0, []

        # 既存NARデータがあれば統合
        nar_races = [r for r in races if r.get('is_local', False)]
        if not nar_races:
            # NAR分が既に別途プリフェッチ済みかチェック
            existing = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
            if os.path.exists(existing):
                with open(existing, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                nar_races = [r for r in existing_data.get('races', []) if r.get('is_local', False)]

        # NAR+JRA統合で保存し直す
        if nar_races:
            logger.info(f"  NAR既存{len(nar_races)}R + JRA{jra_count}R を統合")
            merged = {
                "metadata": {
                    "date": date_str,
                    "total_races": len(nar_races) + jra_count,
                    "created_at": datetime.now(JST).isoformat(),
                },
                "races": nar_races + jra_races,
            }
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

        venues = list(set(r.get('venue', '') for r in jra_races))
        size_kb = os.path.getsize(output_file) / 1024
        logger.info(f"  出力: races_{date_str}.json ({size_kb:.1f}KB)")
        logger.info(f"  JRA: {jra_count}R ({', '.join(venues)})")

        return output_file, jra_count, venues

    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（10分）")
        return None, 0, []
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return None, 0, []


def run_warm_cache(date_str, logger):
    """warm_cache.py をサブプロセスで実行"""
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, 'warm_cache.py'), date_str]
    logger.info(f"ウォーム実行: {date_str}")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_DIR,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=3600,
        )
        ok = skip = fail = 0
        for line in result.stdout.split('\n'):
            line = line.strip()
            if 'OK:' in line:
                ok += 1
            elif 'SKIP' in line:
                skip += 1
            elif 'FAIL' in line or 'ERROR' in line:
                fail += 1
        logger.info(f"  結果: OK={ok}, SKIP={skip}, FAIL={fail}")
        return ok, skip, fail
    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（1時間）")
        return 0, 0, -1
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return 0, 0, -1


def main():
    logger = setup_logging()
    now = datetime.now(JST)
    tomorrow = now + timedelta(days=1)
    date_str = tomorrow.strftime('%Y%m%d')
    weekday_ja = ['月', '火', '水', '木', '金', '土', '日'][tomorrow.weekday()]

    logger.info("=" * 60)
    logger.info("JRA 日次プリフェッチ")
    logger.info("=" * 60)
    logger.info(f"対象日: {tomorrow.strftime('%Y-%m-%d')} ({weekday_ja})")

    # ── JRAプリフェッチ ──
    file_path, jra_count, venues = run_prefetch_jra(date_str, logger)

    if jra_count == 0:
        # JRA非開催日 → 通知不要（毎日空振りするので）
        logger.info("JRA非開催日、終了")
        return 0

    # ── キャッシュウォーミング（JRA + 既存NAR両方） ──
    logger.info("\n[キャッシュウォーミング]")
    ok, skip, fail = run_warm_cache(date_str, logger)

    # ── LINE bot 再起動 ──
    try:
        subprocess.run(["systemctl", "restart", "dlogic-linebot"], timeout=15, capture_output=True)
        logger.info("LINE bot 再起動完了")
    except Exception:
        pass

    # ── Telegram通知（JRA開催日のみ） ──
    msg = (
        f"🏆 <b>JRA日次プリフェッチ完了</b>\n"
        f"対象: {tomorrow.strftime('%m/%d')}({weekday_ja})\n"
        f"{'─' * 20}\n"
        f"会場: {', '.join(venues)}\n"
        f"レース: {jra_count}R\n"
        f"ウォーム: 新規{ok} / 既存{skip} / 失敗{fail}"
    )
    send_telegram(msg)
    logger.info(f"\n完了: {jra_count}R, ウォーム OK={ok} SKIP={skip} FAIL={fail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
