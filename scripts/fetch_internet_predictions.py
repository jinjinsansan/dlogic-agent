#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ネット予想収集スクリプト
重賞レースのYouTube予想動画・大手競馬サイト予想記事を収集し、
Claude APIで馬名+支持率を集計してキャッシュに保存する。

使い方:
  python scripts/fetch_internet_predictions.py 高松宮記念
  python scripts/fetch_internet_predictions.py 大阪杯 --date 20260405

出力:
  data/prefetch/internet_predictions_{race_name}_{date}.json
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')
sys.path.insert(0, PROJECT_DIR)

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

PREFETCH_DIR = os.path.join(PROJECT_DIR, 'data', 'prefetch')
os.makedirs(PREFETCH_DIR, exist_ok=True)

JINA_BASE = "https://r.jina.ai/"
JINA_TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def fetch_via_jina(url: str) -> str:
    """Jina Readerで指定URLのMarkdownコンテンツを取得"""
    try:
        resp = requests.get(
            f"{JINA_BASE}{url}",
            timeout=JINA_TIMEOUT,
            headers={"Accept": "text/markdown"}
        )
        if resp.status_code == 200:
            return resp.text
        logger.warning(f"Jina Reader returned {resp.status_code} for {url}")
        return ""
    except Exception as e:
        logger.error(f"Jina Reader error for {url}: {e}")
        return ""


def search_youtube_predictions(race_name: str, year: int) -> str:
    """YouTube検索結果ページをJina Reader経由で取得"""
    import urllib.parse
    query = urllib.parse.quote(f"{race_name} 予想 {year}")
    url = f"https://www.youtube.com/results?search_query={query}"
    logger.info(f"YouTube検索: {race_name} 予想 {year}")
    return fetch_via_jina(url)


def fetch_netkeiba_columns() -> str:
    """netkeibaコラムトップページを取得"""
    url = "https://news.netkeiba.com/?pid=column_top"
    logger.info("netkeiba コラムページ取得中...")
    return fetch_via_jina(url)


def fetch_netkeiba_article(article_url: str) -> str:
    """netkeiba個別記事を取得"""
    logger.info(f"記事取得: {article_url}")
    time.sleep(1)  # rate limit
    return fetch_via_jina(article_url)


def _parse_views(views_str: str) -> int:
    """再生数文字列を数値に変換 (例: '96K' -> 96000, '1.2M' -> 1200000)"""
    views_str = views_str.strip().replace(',', '')
    try:
        if views_str.endswith('K') or views_str.endswith('k'):
            return int(float(views_str[:-1]) * 1000)
        elif views_str.endswith('M') or views_str.endswith('m'):
            return int(float(views_str[:-1]) * 1000000)
        else:
            return int(float(views_str))
    except ValueError:
        return 0


def extract_youtube_video_info(search_result: str, race_name: str) -> list[dict]:
    """YouTube検索結果からレースに関連する予想動画情報を抽出"""
    videos = []
    lines = search_result.split('\n')
    current_title = None
    current_channel = None
    current_views = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # タイトル行の検出（###で始まるリンクテキスト）
        title_match = re.search(r'###\s*\[(.+?)\]', line)
        if title_match:
            # 前のエントリを保存
            if current_title and current_channel:
                _maybe_add_video(videos, current_title, current_channel, current_views or 0, race_name)
            current_title = title_match.group(1)
            current_channel = None
            current_views = None
            continue

        # チャンネル名の検出
        channel_match = re.search(r'\[([^\]]+?)\]\(https://www\.youtube\.com/(?:@|channel/)', line)
        if channel_match:
            current_channel = channel_match.group(1)
            continue

        # 再生数の検出: "96K 6h ago", "549K 1 day ago", "1.2M views" etc.
        views_match = re.search(r'\b([\d,.]+[KMk]?)\s+(?:\d+\s*(?:h|hour|day|week|month|year|min)|views|再生)', line)
        if views_match:
            current_views = _parse_views(views_match.group(1))
            continue

    # 最後のエントリ
    if current_title and current_channel:
        _maybe_add_video(videos, current_title, current_channel, current_views or 0, race_name)

    videos.sort(key=lambda x: x["views"], reverse=True)
    return videos[:15]


def _maybe_add_video(videos: list, title: str, channel: str, views: int, race_name: str):
    """予想動画かどうか判定してリストに追加"""
    if race_name not in title:
        return
    pred_words = ['予想', '予言', '本命', '穴馬', 'ジャッジ', '分析', '展望', 'Prediction', 'prediction', '注目馬']
    review_words = ['回顧', '結果報告', 'レース映像']
    is_prediction = any(w in title for w in pred_words)
    is_review = any(w in title for w in review_words)
    if is_prediction and not is_review:
        videos.append({"title": title, "channel": channel, "views": views})


def extract_netkeiba_prediction_articles(columns_html: str, race_name: str) -> list[dict]:
    """netkeibaコラムから指定レース名の予想記事URLを抽出"""
    articles = []
    lines = columns_html.split('\n')

    for line in lines:
        if race_name in line and '予想' in line:
            # URLの抽出
            url_match = re.search(r'\(https://news\.netkeiba\.com/\?pid=column_view&cid=(\d+)', line)
            if url_match:
                cid = url_match.group(1)
                url = f"https://news.netkeiba.com/?pid=column_view&cid={cid}"
                # タイトルの抽出
                title_match = re.search(r'###\s*(.+?)(?:\s+\d{4}年|\s+\*)', line)
                if not title_match:
                    title_match = re.search(r'\[(.+?)\]', line)
                title = title_match.group(1) if title_match else "予想記事"
                title = re.sub(r'\[|\]', '', title)
                articles.append({"title": title.strip(), "url": url, "cid": cid})

    return articles


def aggregate_with_claude(youtube_videos: list[dict], youtube_raw: str,
                          netkeiba_articles: list[dict], netkeiba_texts: list[str],
                          race_name: str) -> dict:
    """Claude APIで予想情報を集計し、ソース別の上位5頭を抽出"""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # YouTube部分のプロンプト
    yt_info = ""
    if youtube_videos:
        yt_info = f"## YouTube予想動画（{len(youtube_videos)}件）\n"
        for v in youtube_videos[:10]:
            yt_info += f"- {v['title']}（{v['channel']}、{v['views']:,}再生）\n"
        # 検索結果の生テキストも渡す（descriptionから馬名を拾える場合あり）
        yt_summary = youtube_raw[:8000] if youtube_raw else ""
        yt_info += f"\n### YouTube検索結果の詳細:\n{yt_summary}\n"

    # netkeiba部分のプロンプト
    nk_info = ""
    if netkeiba_texts:
        nk_info = f"## 大手競馬サイト予想記事（{len(netkeiba_texts)}件）\n"
        for i, (article, text) in enumerate(zip(netkeiba_articles, netkeiba_texts)):
            truncated = text[:3000]
            nk_info += f"\n### 記事{i+1}: {article['title']}\n{truncated}\n"

    prompt = f"""以下は{race_name}に関するネット上の予想情報です。

{yt_info}

{nk_info}

上記の情報を分析して、以下のJSON形式で回答してください。
各ソースで言及・推奨されている馬名を集計し、支持率（その馬を推している予想の割合）を算出してください。

重要ルール:
- 馬名はカタカナ表記で統一すること
- 支持率は概算でよい（予想数に対して何%が推しているか）
- 各カテゴリ上位5頭を返すこと
- "注目ポイント"は3つ以内で簡潔に
- JSONのみ返すこと、他のテキストは不要

```json
{{
  "race_name": "{race_name}",
  "youtube": {{
    "source_count": "分析した動画数",
    "horses": [
      {{"rank": 1, "mark": "◎", "name": "馬名", "support_rate": 68}},
      {{"rank": 2, "mark": "○", "name": "馬名", "support_rate": 52}},
      {{"rank": 3, "mark": "▲", "name": "馬名", "support_rate": 38}},
      {{"rank": 4, "mark": "△", "name": "馬名", "support_rate": 24}},
      {{"rank": 5, "mark": "×", "name": "馬名", "support_rate": 18}}
    ]
  }},
  "keiba_site": {{
    "source_count": "分析した記事数",
    "horses": [
      {{"rank": 1, "mark": "◎", "name": "馬名", "support_rate": 55}},
      {{"rank": 2, "mark": "○", "name": "馬名", "support_rate": 50}},
      {{"rank": 3, "mark": "▲", "name": "馬名", "support_rate": 40}},
      {{"rank": 4, "mark": "△", "name": "馬名", "support_rate": 28}},
      {{"rank": 5, "mark": "×", "name": "馬名", "support_rate": 20}}
    ]
  }},
  "highlights": [
    "注目ポイント1",
    "注目ポイント2",
    "注目ポイント3"
  ]
}}
```"""

    logger.info("Claude APIで予想集計中...")
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    result_text = response.content[0].text.strip()
    # JSON部分を抽出
    json_match = re.search(r'\{[\s\S]+\}', result_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.error(f"JSON parse error: {result_text[:500]}")
            return {}
    logger.error(f"No JSON found in response: {result_text[:500]}")
    return {}


def format_display_text(data: dict) -> str:
    """キャッシュデータから表示用テキストを生成"""
    race_name = data.get("race_name", "レース")
    lines = [f"🌐 ネットの予想【{race_name}】\n"]

    # YouTube
    yt = data.get("youtube", {})
    if yt.get("horses"):
        lines.append(f"📺 YouTube予想 集計結果（{yt.get('source_count', '?')}件の予想動画を集計）")
        for h in yt["horses"]:
            lines.append(f"{h['mark']} {h['name']}（支持率 {h['support_rate']}%）")
        lines.append("")

    # 大手競馬サイト
    ks = data.get("keiba_site", {})
    if ks.get("horses"):
        lines.append(f"🏇 大手競馬サイト予想 集計結果（{ks.get('source_count', '?')}件の予想記事を集計）")
        for h in ks["horses"]:
            lines.append(f"{h['mark']} {h['name']}（支持率 {h['support_rate']}%）")
        lines.append("")

    # 注目ポイント
    highlights = data.get("highlights", [])
    if highlights:
        lines.append("📝 注目ポイント")
        for hl in highlights:
            lines.append(f"・{hl}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ネット予想収集")
    parser.add_argument("race_name", help="レース名（例: 高松宮記念）")
    parser.add_argument("--date", default=None, help="日付 YYYYMMDD（省略時は今日）")
    parser.add_argument("--dry-run", action="store_true", help="収集のみ、Claude API呼び出しなし")
    args = parser.parse_args()

    race_name = args.race_name
    date_str = args.date or datetime.now().strftime('%Y%m%d')
    year = int(date_str[:4])

    logger.info(f"=== ネット予想収集: {race_name} ({date_str}) ===")

    # 1. YouTube予想動画を検索
    yt_raw = search_youtube_predictions(race_name, year)
    yt_videos = extract_youtube_video_info(yt_raw, race_name)
    logger.info(f"YouTube: {len(yt_videos)}件の予想動画を検出")
    for v in yt_videos[:5]:
        logger.info(f"  - {v['title']} ({v['views']:,}再生)")

    # 2. netkeiba予想コラムを取得
    nk_columns = fetch_netkeiba_columns()
    nk_articles = extract_netkeiba_prediction_articles(nk_columns, race_name)
    logger.info(f"netkeiba: {len(nk_articles)}件の予想記事を検出")

    # 各記事の本文を取得（最大5件）
    nk_texts = []
    for article in nk_articles[:5]:
        text = fetch_netkeiba_article(article["url"])
        if text:
            nk_texts.append(text)

    if args.dry_run:
        logger.info("Dry run: Claude API呼び出しをスキップ")
        logger.info(f"YouTube動画: {len(yt_videos)}件")
        logger.info(f"netkeiba記事: {len(nk_articles)}件（本文取得: {len(nk_texts)}件）")
        return

    # 3. Claude APIで集計
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    result = aggregate_with_claude(yt_videos, yt_raw, nk_articles, nk_texts, race_name)
    if not result:
        logger.error("Claude APIからの集計結果が空です")
        sys.exit(1)

    # メタデータ追加
    result["fetched_at"] = datetime.now().isoformat()
    result["date"] = date_str
    result["display_text"] = format_display_text(result)

    # 4. 保存
    safe_name = re.sub(r'[^\w]', '_', race_name)
    output_file = os.path.join(PREFETCH_DIR, f"internet_predictions_{safe_name}_{date_str}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"保存: {output_file}")

    # 表示テキストをプレビュー
    logger.info("\n--- 表示プレビュー ---")
    logger.info(result["display_text"])


if __name__ == "__main__":
    main()
