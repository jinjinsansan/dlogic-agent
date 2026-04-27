#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日次レースデータ自動プリフェッチ
毎日18:00にWindows Task Schedulerから実行

処理:
1. 翌日のNAR全レース出馬表を取得
2. 翌日のJRA全レース出馬表を取得（土日のみ）
3. VPSに転送
4. ログ出力 + Telegram通知
"""

import subprocess
import sys
import os
import json
import logging
import re
from datetime import datetime, timedelta

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')
PREFETCH_DIR = os.path.join(PROJECT_DIR, 'data', 'prefetch')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(PREFETCH_DIR, exist_ok=True)

# VPS設定
VPS_HOST = "220.158.24.157"
VPS_USER = "root"
VPS_PREFETCH_DIR = "/opt/dlogic/linebot/data/prefetch"

# R2 CDN設定（ビューア用）
R2_ENDPOINT = 'https://954dcc10adf822b50ccceedef0aa97e6.r2.cloudflarestorage.com'
R2_ACCESS_KEY = '9e66f7edadb758346ff3a3c65464ef13'
R2_SECRET_KEY = 'bc8863b26285fa64fbf9b58621550f0519ae233c5eb4b21bba9427a422306ec6'
R2_BUCKET = 'dlogic-knowledge-files'

# Telegram通知（オプション）
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')


def setup_logging():
    today = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(LOG_DIR, f'daily_prefetch_{today}.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )
    return logging.getLogger(__name__)


def send_telegram(message, logger):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Telegram通知失敗: {e}")


def run_prefetch(date_str, flags, logger):
    """prefetch_races.pyを実行"""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, 'prefetch_races.py'), date_str] + flags
    logger.info(f"実行: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, cwd=SCRIPTS_DIR,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=600,
        )
        # 結果のサマリーをログ
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and ('保存' in line or 'レース数' in line or '会場' in line or 'FAIL' in line):
                logger.info(f"  {line}")

        output_file = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
        if os.path.exists(output_file):
            size_kb = os.path.getsize(output_file) / 1024
            logger.info(f"  出力: races_{date_str}.json ({size_kb:.1f}KB)")
            return output_file
        else:
            logger.warning(f"  出力ファイルなし（レース未掲載の可能性）")
            return None

    except subprocess.TimeoutExpired:
        logger.error("  タイムアウト（10分）")
        return None
    except Exception as e:
        logger.error(f"  エラー: {e}")
        return None


def enrich_banei_odds(filepath, date_str, logger):
    """帯広(ばんえい)の odds + start_time を keiba.go.jp から取得して prefetch に埋める.

    netkeibaが対応しないため、別途スクレイプして上書き保存する.
    """
    try:
        sys.path.insert(0, os.path.join(PROJECT_DIR, 'scrapers'))
        from banei_odds import fill_banei_odds_in_prefetch
    except ImportError as e:
        logger.warning(f"  banei_odds 読込失敗: {e}")
        return False
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            prefetch = json.load(f)
        updated = fill_banei_odds_in_prefetch(prefetch, date_str)
        if updated > 0:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(prefetch, f, ensure_ascii=False, indent=2)
            logger.info(f"  帯広odds+start_time: {updated}レース更新")
        else:
            logger.info(f"  帯広: 更新不要 (帯広開催なし or 既に埋まっている)")
        return True
    except Exception as e:
        logger.warning(f"  帯広odds失敗: {e}")
        return False


def upload_to_r2(filepath, logger):
    """プリフェッチJSONをR2 CDNにアップロード（ビューア用）"""
    filename = os.path.basename(filepath)
    r2_key = f"prefetch/{filename}"
    try:
        import boto3
        from botocore.config import Config
        s3 = boto3.client('s3',
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )
        s3.upload_file(filepath, R2_BUCKET, r2_key,
                       ExtraArgs={'ContentType': 'application/json'})
        logger.info(f"  R2アップロード: {r2_key}")
        return True
    except Exception as e:
        logger.warning(f"  R2アップロード失敗: {e}")
        return False


def upload_to_vps(filepath, logger):
    """SCPでVPSに転送"""
    filename = os.path.basename(filepath)
    try:
        # ディレクトリ確認
        subprocess.run(
            ["ssh", f"{VPS_USER}@{VPS_HOST}", f"mkdir -p {VPS_PREFETCH_DIR}"],
            timeout=15, capture_output=True
        )
        # ファイル転送
        result = subprocess.run(
            ["scp", filepath, f"{VPS_USER}@{VPS_HOST}:{VPS_PREFETCH_DIR}/{filename}"],
            timeout=30, capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"  VPS転送成功: {filename}")
            return True
        else:
            logger.error(f"  VPS転送失敗: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"  VPS転送エラー: {e}")
        return False


def find_graded_races(date_str, logger=None):
    """プリフェッチデータから重賞レース名を抽出（JRA重賞 + 地方交流重賞）"""
    output_file = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
    if not os.path.exists(output_file):
        return []
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []

    graded = []
    for race in data.get('races', []):
        name = race.get('race_name', '')
        # JRA重賞: GI/GII/GIII or (G1)/(G2)/(G3)
        # 地方交流重賞: Jpn1/Jpn2/Jpn3
        is_graded = bool(re.search(r'(G[I1]{1,3}|GII|GIII|G2|G3|Jpn[123])', name))
        if is_graded:
            # グレード表記を除去してレース名だけ取り出す
            clean_name = re.sub(r'\s*(G[I1]{1,3}|GII|GIII|G[123]|Jpn[123])\s*$', '', name).strip()
            if clean_name:
                graded.append(clean_name)
                if logger:
                    logger.info(f"  重賞検出: {name} → {clean_name}")
    return graded


def run_internet_predictions(race_names, date_str, logger):
    """VPS上でネット予想収集スクリプトを実行"""
    results = []
    for race_name in race_names:
        logger.info(f"  ネット予想収集: {race_name}")
        try:
            result = subprocess.run(
                ["ssh", f"{VPS_USER}@{VPS_HOST}",
                 f"cd /opt/dlogic/linebot && /opt/dlogic/linebot/venv/bin/python "
                 f"scripts/fetch_internet_predictions.py '{race_name}' --date {date_str}"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=180,
            )
            if result.returncode == 0:
                logger.info(f"    {race_name}: OK")
                results.append(f"ネット予想({race_name}): OK")
            else:
                logger.error(f"    {race_name}: エラー - {result.stderr[:200]}")
                results.append(f"ネット予想({race_name}): エラー")
        except subprocess.TimeoutExpired:
            logger.error(f"    {race_name}: タイムアウト")
            results.append(f"ネット予想({race_name}): タイムアウト")
        except Exception as e:
            logger.error(f"    {race_name}: {e}")
            results.append(f"ネット予想({race_name}): {e}")
    return results


def cleanup_old_prefetch(keep_days=7, logger=None):
    """古いプリフェッチファイルを削除（ローカル + VPS）"""
    cutoff = datetime.now() - timedelta(days=keep_days)
    cutoff_str = cutoff.strftime('%Y%m%d')

    # ローカル
    for f in os.listdir(PREFETCH_DIR):
        if f.endswith('.json') and (f.startswith('races_') or f.startswith('internet_predictions_')):
            # 日付部分を抽出 (末尾の YYYYMMDD.json)
            date_match = re.search(r'(\d{8})\.json$', f)
            if date_match and date_match.group(1) < cutoff_str:
                os.remove(os.path.join(PREFETCH_DIR, f))
                if logger:
                    logger.info(f"  ローカル削除: {f}")

    # VPS
    try:
        subprocess.run(
            ["ssh", f"{VPS_USER}@{VPS_HOST}",
             f"find {VPS_PREFETCH_DIR} -name '*.json' -mtime +{keep_days} -delete"],
            timeout=15, capture_output=True
        )
    except Exception:
        pass


def main():
    logger = setup_logging()
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime('%Y%m%d')
    weekday = tomorrow.weekday()  # 0=Mon, 5=Sat, 6=Sun

    logger.info("=" * 60)
    logger.info("日次レースデータ プリフェッチ")
    logger.info("=" * 60)
    logger.info(f"対象日: {tomorrow.strftime('%Y-%m-%d')} ({['月','火','水','木','金','土','日'][weekday]})")

    results = []
    files_to_upload = []

    # NAR: 毎日開催あり
    logger.info("\n[NAR]")
    nar_file = run_prefetch(date_str, [], logger)
    if nar_file:
        files_to_upload.append(nar_file)
        results.append("NAR: OK")
    else:
        results.append("NAR: レースなし")

    # JRA: 土日（金曜夕方に土曜分、土曜夕方に日曜分）
    # weekday: 5=Sat, 6=Sun → 金(4)に土(5)取得、土(5)に日(6)取得
    if weekday in (5, 6):  # 翌日が土or日
        logger.info("\n[JRA]")
        jra_file = run_prefetch(date_str, ['--jra'], logger)
        if jra_file:
            # JRAは別ファイルではなく同じファイルに--allで取り直す
            # 実際には--allでNAR+JRA両方取得し直す
            logger.info("  JRA+NARを統合取得...")
            all_file = run_prefetch(date_str, ['--all'], logger)
            if all_file:
                files_to_upload = [all_file]
                results.append("JRA: OK")
        else:
            results.append("JRA: レースなし")

    # 明後日分も試行（まだ未掲載の可能性あるが）
    day_after = datetime.now() + timedelta(days=2)
    day_after_str = day_after.strftime('%Y%m%d')
    logger.info(f"\n[明後日 {day_after.strftime('%m/%d')} 先行取得]")
    extra_file = run_prefetch(day_after_str, [], logger)
    if extra_file:
        files_to_upload.append(extra_file)
        results.append(f"明後日NAR: OK")
    else:
        results.append(f"明後日NAR: 未掲載")

    # 帯広(ばんえい)の odds + start_time を keiba.go.jp から取得して埋める
    # netkeibaが帯広に未対応のため、prefetch直後に enrichment が必要
    logger.info("\n[帯広odds enrich]")
    for f in files_to_upload:
        # ファイル名から日付抽出 (races_YYYYMMDD.json)
        m = re.search(r'races_(\d{8})\.json$', f)
        if m:
            enrich_banei_odds(f, m.group(1), logger)

    # R2アップロード（ビューア用）
    logger.info("\n[R2 CDN]")
    for f in files_to_upload:
        upload_to_r2(f, logger)

    # VPS転送
    logger.info("\n[VPS転送]")
    upload_ok = 0
    for f in files_to_upload:
        if upload_to_vps(f, logger):
            upload_ok += 1

    # VPSのLINE botを再起動（prefetchファイル反映）
    if upload_ok > 0:
        try:
            subprocess.run(
                ["ssh", f"{VPS_USER}@{VPS_HOST}", "systemctl restart dlogic-linebot"],
                timeout=15, capture_output=True
            )
            logger.info("  LINE bot再起動完了")
        except Exception:
            pass

    # ネット予想収集（重賞レースのYouTube + netkeiba予想を集計）
    logger.info("\n[ネット予想収集]")
    graded_races = find_graded_races(date_str, logger)
    if graded_races:
        inet_results = run_internet_predictions(graded_races, date_str, logger)
        results.extend(inet_results)
        # 収集後にLINE bot再起動（キャッシュ反映）
        if inet_results:
            try:
                subprocess.run(
                    ["ssh", f"{VPS_USER}@{VPS_HOST}", "systemctl restart dlogic-linebot"],
                    timeout=15, capture_output=True
                )
                logger.info("  LINE bot再起動完了（ネット予想反映）")
            except Exception:
                pass
    else:
        logger.info("  翌日の重賞レースなし → スキップ")

    # レスポンスキャッシュウォーミング（VPS上で実行）
    logger.info("\n[キャッシュウォーミング]")
    try:
        warm_result = subprocess.run(
            ["ssh", f"{VPS_USER}@{VPS_HOST}",
             f"cd /opt/dlogic/linebot && /opt/dlogic/linebot/venv/bin/python scripts/warm_cache.py {date_str}"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=1800,  # 30 minutes max
        )
        for line in warm_result.stdout.split('\n'):
            line = line.strip()
            if line and ('OK' in line or 'SKIP' in line or 'FAIL' in line or 'ERROR' in line or '完了' in line):
                logger.info(f"  {line}")
        if warm_result.returncode == 0:
            results.append("キャッシュウォーミング: OK")
        else:
            results.append("キャッシュウォーミング: エラー")
            logger.error(f"  stderr: {warm_result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        logger.error("  キャッシュウォーミング タイムアウト（30分）")
        results.append("キャッシュウォーミング: タイムアウト")
    except Exception as e:
        logger.error(f"  キャッシュウォーミング エラー: {e}")
        results.append(f"キャッシュウォーミング: {e}")

    # 古いファイル削除
    cleanup_old_prefetch(keep_days=7, logger=logger)

    # サマリー
    logger.info(f"\n{'='*60}")
    logger.info("結果:")
    for r in results:
        logger.info(f"  {r}")
    logger.info(f"VPS転送: {upload_ok}/{len(files_to_upload)}件")

    # Telegram通知
    msg = f"プリフェッチ {date_str}\n" + "\n".join(results)
    msg += f"\nVPS転送: {upload_ok}/{len(files_to_upload)}件"
    send_telegram(msg, logger)

    return 0


if __name__ == "__main__":
    sys.exit(main())
