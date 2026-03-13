#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レスポンスキャッシュウォーミング
プリフェッチ済みレースに対して、Claude APIで予想・分析を事前生成しキャッシュに保存

Usage:
    python scripts/warm_cache.py 20260311          # 指定日の全レースをウォーム
    python scripts/warm_cache.py 20260311 --dry-run # 対象レース一覧のみ表示
"""

import json
import logging
import os
import sys
import time

# プロジェクトルートをパスに追加
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')
sys.path.insert(0, PROJECT_DIR)

# .env.local を読み込み
env_path = os.path.join(PROJECT_DIR, '.env.local')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

from agent.engine import call_claude, build_system_prompt, extract_text, get_tool_blocks, format_tools_used_footer
from agent.response_cache import save as save_cached_response, get as get_cached_response, clear_old
from tools.executor import execute_tool

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

PREFETCH_DIR = os.path.join(PROJECT_DIR, 'data', 'prefetch')

# Query types to warm (prediction is most important, others are button follow-ups)
WARM_QUERIES = [
    ("prediction", "このレースの予想をしてください。race_id: {race_id}"),
    ("race-flow", "このレースの展開予想をしてください。race_id: {race_id}"),
    ("jockey", "このレースの騎手分析をしてください。race_id: {race_id}"),
    ("bloodline", "このレースの血統分析をしてください。race_id: {race_id}"),
    ("recent-runs", "このレースの出走馬の直近成績を教えてください。race_id: {race_id}"),
    ("odds-probability", "このレースの予測勝率を見せてください。race_id: {race_id}"),
]

MAX_TOOL_TURNS = 6


def load_race_ids(date_str: str) -> list[dict]:
    """Load race IDs from prefetch JSON."""
    path = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
    if not os.path.exists(path):
        logger.error(f"プリフェッチファイルなし: {path}")
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('races', [])


def warm_single(race_id: str, query_type: str, user_msg: str) -> bool:
    """Warm cache for a single race+query_type by running Claude agentic loop."""
    # Skip if already cached
    if get_cached_response(race_id, query_type):
        logger.info(f"  SKIP (cached): {race_id}:{query_type}")
        return True

    system = build_system_prompt()
    history = [{"role": "user", "content": user_msg}]
    tools_used = []

    try:
        for turn in range(MAX_TOOL_TURNS):
            response = call_claude(history, system)

            if response.stop_reason == "end_turn":
                history.append({"role": "assistant", "content": response.content})
                break

            tool_blocks = get_tool_blocks(response)
            if not tool_blocks:
                history.append({"role": "assistant", "content": response.content})
                break

            history.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tb in tool_blocks:
                # warm_cacheはユーザーリクエストではないのでinquiry送信をスキップ
                if tb.name == "send_inquiry":
                    result = json.dumps({"status": "skipped", "message": "warm_cacheではスキップ"}, ensure_ascii=False)
                else:
                    result = execute_tool(tb.name, tb.input if isinstance(tb.input, dict) else {})
                tools_used.append(tb.name)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": result,
                })
            history.append({"role": "user", "content": tool_results})

        # Extract final text
        response_text = extract_text(response) if response else ""
        if not response_text:
            logger.warning(f"  FAIL (empty): {race_id}:{query_type}")
            return False

        footer = format_tools_used_footer(tools_used)
        save_cached_response(race_id, query_type, response_text, footer, tools_used)
        logger.info(f"  OK: {race_id}:{query_type} ({len(response_text)}chars)")
        return True

    except Exception as e:
        logger.error(f"  ERROR: {race_id}:{query_type} - {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/warm_cache.py <YYYYMMDD> [--dry-run]")
        sys.exit(1)

    date_str = sys.argv[1]
    dry_run = '--dry-run' in sys.argv

    # Clean old cache entries first
    clear_old(max_age_hours=36)

    races = load_race_ids(date_str)
    if not races:
        logger.info(f"対象レースなし: {date_str}")
        return 0

    logger.info(f"対象日: {date_str}, レース数: {len(races)}")

    if dry_run:
        for r in races:
            print(f"  {r.get('race_id')} - {r.get('venue','')} {r.get('race_name','')}")
        return 0

    total = 0
    success = 0
    for race in races:
        race_id = race.get('race_id', '')
        venue = race.get('venue', '')
        race_name = race.get('race_name', '')
        logger.info(f"\n[{venue} {race_name}] {race_id}")

        for query_type, msg_template in WARM_QUERIES:
            total += 1
            user_msg = msg_template.format(race_id=race_id)
            if warm_single(race_id, query_type, user_msg):
                success += 1
            # Rate limit: avoid hammering Claude API
            time.sleep(1)

    logger.info(f"\n{'='*50}")
    logger.info(f"ウォームアップ完了: {success}/{total} 成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
