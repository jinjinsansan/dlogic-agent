#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPS日次プリフェッチ: 地方競馬(NAR)
毎日 18:00 JST に systemd timer から実行

処理:
1. 翌日のNAR全レース出馬表を取得
2. キャッシュウォーミング（全分析）
3. Telegram通知
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
    log_file = os.path.join(LOG_DIR, f'cron_nar_{today}.log')
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


def run_prefetch(date_str, flags, logger):
    """prefetch_races.py を実行（既存JRAデータがあれば統合）"""
    output_file = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")

    # 既存JRAデータを退避（NARプリフェッチが上書きするため）
    existing_jra_races = []
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            existing_jra_races = [r for r in existing_data.get('races', []) if not r.get('is_local', True)]
            if existing_jra_races:
                logger.info(f"  既存JRAデータ: {len(existing_jra_races)}R（統合予定）")
        except Exception:
            pass

    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, 'prefetch_races.py'), date_str] + flags
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
            if line and ('保存' in line or 'レース数' in line or '会場' in line or 'FAIL' in line):
                logger.info(f"  {line}")

        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            nar_races = data.get('races', [])

            # 既存JRAデータを統合
            if existing_jra_races:
                all_races = nar_races + existing_jra_races
                merged = {
                    "metadata": {
                        "date": date_str,
                        "total_races": len(all_races),
                        "created_at": datetime.now(JST).isoformat(),
                    },
                    "races": all_races,
                }
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                logger.info(f"  統合: NAR {len(nar_races)}R + JRA {len(existing_jra_races)}R = {len(all_races)}R")
                race_count = len(all_races)
            else:
                race_count = len(nar_races)

            size_kb = os.path.getsize(output_file) / 1024
            logger.info(f"  出力: races_{date_str}.json ({size_kb:.1f}KB, {race_count}R)")
            return output_file, race_count
        else:
            # NARレースなし → 既存JRAデータを復元
            if existing_jra_races:
                restored = {
                    "metadata": {"date": date_str, "total_races": len(existing_jra_races),
                                 "created_at": datetime.now(JST).isoformat()},
                    "races": existing_jra_races,
                }
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(restored, f, ensure_ascii=False, indent=2)
                logger.info(f"  NARなし、JRA {len(existing_jra_races)}R を維持")
                return output_file, len(existing_jra_races)
            logger.info(f"  出力ファイルなし（レース未掲載の可能性）")
            return None, 0
    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（10分）")
        return None, 0
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return None, 0


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


def cleanup_old(keep_days=7, logger=None):
    """古いファイル削除"""
    cutoff = (datetime.now(JST) - timedelta(days=keep_days)).strftime('%Y%m%d')
    for f in os.listdir(PREFETCH_DIR):
        if f.startswith('races_') and f.endswith('.json'):
            date_part = f.replace('races_', '').replace('.json', '')
            if date_part < cutoff:
                os.remove(os.path.join(PREFETCH_DIR, f))
                if logger:
                    logger.info(f"  削除: {f}")


def main():
    logger = setup_logging()
    now = datetime.now(JST)
    tomorrow = now + timedelta(days=1)
    date_str = tomorrow.strftime('%Y%m%d')
    weekday_ja = ['月', '火', '水', '木', '金', '土', '日'][tomorrow.weekday()]

    logger.info("=" * 60)
    logger.info("NAR 日次プリフェッチ")
    logger.info("=" * 60)
    logger.info(f"対象日: {tomorrow.strftime('%Y-%m-%d')} ({weekday_ja})")

    # ── NARプリフェッチ ──
    file_path, race_count = run_prefetch(date_str, [], logger)

    if race_count == 0:
        msg = f"🏇 <b>NAR日次</b> {tomorrow.strftime('%m/%d')}({weekday_ja})\nレースなし"
        send_telegram(msg)
        logger.info("レースなし、終了")
        return 0

    # ── キャッシュウォーミング ──
    logger.info("\n[キャッシュウォーミング]")
    ok, skip, fail = run_warm_cache(date_str, logger)

    # ── クリーンアップ ──
    cleanup_old(keep_days=7, logger=logger)

    # ── LINE bot 再起動 ──
    try:
        subprocess.run(["systemctl", "restart", "dlogic-linebot"], timeout=15, capture_output=True)
        logger.info("LINE bot 再起動完了")
    except Exception:
        pass

    # ── Telegram通知 ──
    msg = (
        f"🏇 <b>NAR日次プリフェッチ完了</b>\n"
        f"対象: {tomorrow.strftime('%m/%d')}({weekday_ja})\n"
        f"{'─' * 20}\n"
        f"レース: {race_count}R\n"
        f"ウォーム: 新規{ok} / 既存{skip} / 失敗{fail}"
    )
    send_telegram(msg)
    logger.info(f"\n完了: {race_count}R, ウォーム OK={ok} SKIP={skip} FAIL={fail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
