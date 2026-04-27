"""帯広(ばんえい) オッズスクレイパー — keiba.go.jp.

netkeibaが対応しない帯広(ばんえい)のオッズを keiba.go.jp から取得する。
prefetch JSON の odds=[0,...] を埋めるために使用。

エンドポイント:
  http://www2.keiba.go.jp/KeibaWeb/TodayRaceInfo/OddsTanFuku
    ?k_raceDate=YYYY/MM/DD&k_raceNo=N&k_babaCode=3   (3 = 帯広/ばんえい)
"""
from __future__ import annotations
import logging
import re
from typing import Optional

import urllib.request
from urllib.error import HTTPError, URLError

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
BANEI_BABA_CODE = "3"


def _fetch_html(url: str, timeout: int = 10, max_retries: int = 3) -> Optional[str]:
    import time as _time
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                # keiba.go.jp は EUC-JP の場合と UTF-8 の場合がある
                for enc in ("utf-8", "shift_jis", "euc-jp"):
                    try:
                        return data.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return data.decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError) as e:
            if attempt < max_retries:
                wait = 2 ** attempt  # 指数バックオフ: 2s, 4s
                logger.warning(f"banei fetch failed (attempt {attempt}/{max_retries}) {url}: {e} — retry in {wait}s")
                _time.sleep(wait)
            else:
                logger.warning(f"banei fetch failed (all {max_retries} attempts) {url}: {e}")
    return None


def fetch_banei_race_odds(date_yyyymmdd: str, race_no: int) -> dict[int, float]:
    """指定日 race_no の帯広レースの 馬番 -> 単勝オッズ map を返す.

    Returns: {umaban: tansho_odds} (空なら取得失敗 or レース無し)
    """
    if BeautifulSoup is None:
        logger.error("BeautifulSoup not installed")
        return {}

    date_path = f"{date_yyyymmdd[:4]}/{date_yyyymmdd[4:6]}/{date_yyyymmdd[6:8]}"
    url = (
        f"http://www2.keiba.go.jp/KeibaWeb/TodayRaceInfo/OddsTanFuku"
        f"?k_raceDate={date_path}&k_raceNo={race_no}&k_babaCode={BANEI_BABA_CODE}"
    )
    html = _fetch_html(url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="odd_popular_table_02")
    if not table:
        logger.info(f"banei race {date_yyyymmdd} R{race_no}: odds table not found")
        return {}

    odds_map: dict[int, float] = {}
    rows = table.find_all("tr")
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        # Column 0: 枠, 1: 馬番, 2: 馬名, 3: 単勝オッズ
        try:
            umaban = int(tds[1].get_text(strip=True))
        except (ValueError, IndexError):
            continue
        odds_text = tds[3].get_text(strip=True)
        # オッズが取り消し時は "—" や 空白の場合あり
        odds_text = odds_text.replace(",", "")
        m = re.match(r"^([\d.]+)$", odds_text)
        if m:
            try:
                odds_map[umaban] = float(m.group(1))
            except ValueError:
                pass

    return odds_map


def fetch_banei_start_times(date_yyyymmdd: str) -> dict[int, str]:
    """指定日の帯広全レースの 発走時刻 (race_no -> "HH:MM") を返す."""
    if BeautifulSoup is None:
        return {}
    date_path = f"{date_yyyymmdd[:4]}/{date_yyyymmdd[4:6]}/{date_yyyymmdd[6:8]}"
    url = (
        f"http://www2.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceList"
        f"?k_raceDate={date_path}&k_babaCode={BANEI_BABA_CODE}"
    )
    html = _fetch_html(url)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find("section", class_="raceTable")
    if not section:
        return {}
    times: dict[int, str] = {}
    for tr in section.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        # column 0 = R番号 (e.g., "1R"), column 1 = 発走時刻
        m = re.match(r"^(\d+)R$", cells[0].get_text(strip=True))
        if not m:
            continue
        race_no = int(m.group(1))
        time_match = re.match(r"^(\d{1,2}:\d{2})", cells[1].get_text(strip=True))
        if time_match:
            times[race_no] = time_match.group(1)
    return times


def fill_banei_odds_in_prefetch(prefetch: dict, date_yyyymmdd: str) -> int:
    """prefetch JSON 内の帯広レースの odds + start_time を埋める. 更新件数を返す.

    prefetch['races'] の各 race[venue=='帯広'] に対し:
    - odds が全0または欠落していたら fetch_banei_race_odds で取得して上書き
    - start_time が空ならば fetch_banei_start_times の値で埋める
    """
    if not prefetch or not prefetch.get("races"):
        return 0

    # まず全レース分の start_time を一括取得 (1リクエスト)
    start_times = fetch_banei_start_times(date_yyyymmdd)
    if start_times:
        logger.info(f"banei start_times fetched: {len(start_times)} races")

    updated = 0
    for race in prefetch["races"]:
        if race.get("venue") != "帯広":
            continue
        race_no = race.get("race_number")
        if not race_no:
            continue
        rn_int = int(race_no)
        race_updated = False

        # start_time
        if not race.get("start_time") and rn_int in start_times:
            race["start_time"] = start_times[rn_int]
            race_updated = True

        # odds
        horse_numbers = race.get("horse_numbers") or []
        existing_odds = race.get("odds") or []
        if not (existing_odds and any(o and o > 0 for o in existing_odds)):
            odds_map = fetch_banei_race_odds(date_yyyymmdd, rn_int)
            if odds_map:
                new_odds = [odds_map.get(int(hn), 0.0) for hn in horse_numbers]
                if any(o > 0 for o in new_odds):
                    race["odds"] = new_odds
                    race_updated = True

        if race_updated:
            updated += 1
            logger.info(f"banei R{race_no}: filled (start_time={race.get('start_time')}, "
                       f"odds_count={sum(1 for o in race.get('odds', []) if o > 0)})")

    return updated


if __name__ == "__main__":
    import argparse
    import json
    import os

    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="20260427", help="YYYYMMDD")
    p.add_argument("--race", type=int, help="single race number")
    p.add_argument("--prefetch-path", help="prefetch JSON path to fill")
    args = p.parse_args()

    if args.race:
        odds = fetch_banei_race_odds(args.date, args.race)
        print(f"R{args.race}: {odds}")
    elif args.prefetch_path:
        with open(args.prefetch_path, "r", encoding="utf-8") as f:
            prefetch = json.load(f)
        updated = fill_banei_odds_in_prefetch(prefetch, args.date)
        if updated > 0:
            with open(args.prefetch_path, "w", encoding="utf-8") as f:
                json.dump(prefetch, f, ensure_ascii=False, indent=2)
            print(f"Updated {updated} race(s) in {args.prefetch_path}")
        else:
            print("No updates needed or no banei odds available")
    else:
        # default: fetch race 1 & 2 as test
        for r in [1, 2]:
            odds = fetch_banei_race_odds(args.date, r)
            print(f"R{r}: {odds}")
