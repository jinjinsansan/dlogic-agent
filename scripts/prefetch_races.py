#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レースデータ前日プリフェッチスクリプト
netkeiba.comから出馬表を取得し、botが即座に使えるJSONを生成

Usage:
    python scripts/prefetch_races.py                    # 明日のNAR
    python scripts/prefetch_races.py 20260311           # 指定日のNAR
    python scripts/prefetch_races.py 20260311 --jra     # 指定日のJRA
    python scripts/prefetch_races.py 20260311 --all     # 指定日のJRA+NAR
"""

import json
import logging
import os
import sys
import time
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# =============================================================================
# 設定
# =============================================================================

NETKEIBA_JRA_BASE = "https://race.netkeiba.com"
NETKEIBA_NAR_BASE = "https://nar.netkeiba.com"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# 出力ディレクトリ
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'prefetch')
os.makedirs(OUTPUT_DIR, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# =============================================================================
# HTTP
# =============================================================================

def fetch_soup(url, encoding="euc-jp"):
    """URLを取得してBeautifulSoupを返す"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
                "User-Agent": USER_AGENT
            })
            # Check HTTP status
            if resp.status_code == 404:
                print(f"  WARN: HTTP 404 - {url}")
                return None
            if resp.status_code >= 400:
                print(f"  WARN: HTTP {resp.status_code} - {url}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            resp.encoding = encoding
            html_text = resp.text
            if not html_text or len(html_text.strip()) < 100:
                print(f"  WARN: Empty response - {url}")
                return None
            return BeautifulSoup(html_text, "lxml")
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  FAIL: {url} - {e}")
                return None
    return None


# =============================================================================
# NAR スクレイピング
# =============================================================================

def fetch_nar_race_list(date_str):
    """NAR全レース一覧を取得"""
    url = f"{NETKEIBA_NAR_BASE}/top/race_list_sub.html?kaisai_date={date_str}"
    soup = fetch_soup(url, encoding="utf-8")
    if not soup:
        return []

    races = []
    current_venue = ""

    for dl in soup.select("dl.RaceList_DataList"):
        header = dl.select_one("p.RaceList_DataHeader, dt")
        if header:
            header_text = header.get_text(strip=True)
            for v in ["大井", "川崎", "船橋", "浦和", "園田", "姫路", "名古屋", "笠松",
                       "高知", "佐賀", "水沢", "盛岡", "門別", "帯広", "金沢"]:
                if v in header_text:
                    current_venue = v
                    break

        for li in dl.select("li"):
            a_tag = li.select_one("a")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if "race_id=" not in href:
                continue

            race_id = href.split("race_id=")[-1].split("&")[0]

            race_num_el = li.select_one(".Race_Num")
            race_number = 0
            if race_num_el:
                num_text = race_num_el.get_text(strip=True).replace("R", "")
                if num_text.isdigit():
                    race_number = int(num_text)

            race_name_el = li.select_one(".ItemTitle")
            race_name = race_name_el.get_text(strip=True) if race_name_el else f"{race_number}R"

            # 発走時刻
            start_time = ""
            time_el = li.select_one(".RaceList_ItemTime")
            if time_el:
                start_time = time_el.get_text(strip=True)

            distance = ""
            race_data = li.select_one(".RaceList_ItemLong")
            if race_data:
                for span in race_data.select("span"):
                    text = span.get_text(strip=True)
                    if "m" in text:
                        distance = text
                        break
                for cls_name in ["Dart", "Shiba"]:
                    if race_data.select_one(f".{cls_name}"):
                        if "ダ" not in distance and cls_name == "Dart":
                            distance = "ダ" + distance
                        elif "芝" not in distance and cls_name == "Shiba":
                            distance = "芝" + distance

            races.append({
                "race_id": race_id,
                "race_number": race_number,
                "race_name": race_name,
                "venue": current_venue,
                "distance": distance,
                "start_time": start_time,
                "is_nar": True,
            })

    return races


def fetch_nar_entries(race_id):
    """NAR個別レースの出馬表を取得"""
    url = f"{NETKEIBA_NAR_BASE}/race/shutuba.html?race_id={race_id}"
    soup = fetch_soup(url, encoding="euc-jp")
    if not soup:
        return None

    # Validate HTML has race data
    race_table = soup.select_one("table.RaceTable01, table.Shutuba_Table")
    horse_rows = soup.select("tr.HorseList")
    if not race_table and not horse_rows:
        print(f"  WARN: {race_id} - 出馬表テーブルなし（HTML構造変更？）")
        return None

    race_name = ""
    race_name_el = soup.select_one(".RaceName")
    if race_name_el:
        race_name = race_name_el.get_text(strip=True)

    venue = ""
    distance = ""
    track_condition = "−"

    race_data1 = soup.select_one(".RaceData01")
    if race_data1:
        text = race_data1.get_text(strip=True)
        m = re.search(r'([芝ダ障]\d+m)', text)
        if m:
            distance = m.group(1)
        item04 = race_data1.select_one(".Item04")
        if item04:
            cond_text = item04.get_text(strip=True)
            for cond in ["不良", "重", "稍重", "良"]:
                if cond in cond_text:
                    track_condition = cond
                    break

    race_data2 = soup.select_one(".RaceData02")
    if race_data2:
        for span in race_data2.select("span"):
            text = span.get_text(strip=True)
            for v in ["大井", "川崎", "船橋", "浦和", "園田", "姫路", "名古屋", "笠松",
                       "高知", "佐賀", "水沢", "盛岡", "門別", "帯広", "金沢"]:
                if v in text:
                    venue = v
                    break

    race_number = 0
    if len(race_id) >= 12:
        try:
            race_number = int(race_id[10:12])
        except ValueError:
            pass

    entries = {
        "horses": [], "horse_numbers": [], "posts": [],
        "jockeys": [], "trainers": [], "sex_ages": [], "weights": [],
        "odds": [], "popularities": [],
    }

    for tr in soup.select("table.RaceTable01 tr.HorseList, tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 8:
            continue
        try:
            post = int(tds[0].get_text(strip=True)) if tds[0].get_text(strip=True).isdigit() else 0
            horse_number = int(tds[1].get_text(strip=True)) if tds[1].get_text(strip=True).isdigit() else 0

            horse_name_el = tds[3].select_one("a") if len(tds) > 3 else None
            horse_name = horse_name_el.get_text(strip=True) if horse_name_el else tds[3].get_text(strip=True)

            sex_age = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            weight_text = tds[5].get_text(strip=True) if len(tds) > 5 else "0"
            weight = float(weight_text) if weight_text.replace(".", "").isdigit() else 0.0

            jockey_el = tds[6].select_one("a")
            jockey = jockey_el.get_text(strip=True) if jockey_el else tds[6].get_text(strip=True)

            trainer_el = tds[7].select_one("a")
            trainer = trainer_el.get_text(strip=True) if trainer_el else tds[7].get_text(strip=True)

            # オッズ（あれば）
            odds = 0.0
            popularity = 0
            if len(tds) > 9:
                odds_text = tds[9].get_text(strip=True)
                if odds_text.replace(".", "").isdigit():
                    odds = float(odds_text)
            if len(tds) > 10:
                pop_text = tds[10].get_text(strip=True)
                if pop_text.isdigit():
                    popularity = int(pop_text)

            entries["horses"].append(horse_name)
            entries["horse_numbers"].append(horse_number)
            entries["posts"].append(post)
            entries["jockeys"].append(jockey)
            entries["trainers"].append(trainer)
            entries["sex_ages"].append(sex_age)
            entries["weights"].append(weight)
            entries["odds"].append(odds)
            entries["popularities"].append(popularity)

        except (ValueError, IndexError):
            continue

    # Validate: all arrays must be same length
    num_horses = len(entries["horses"])
    if num_horses == 0:
        return None

    array_keys = ["horse_numbers", "jockeys", "posts", "trainers", "sex_ages", "weights"]
    for key in array_keys:
        if len(entries[key]) != num_horses:
            print(f"  WARN: {race_id} {key} length mismatch (horses={num_horses}, {key}={len(entries[key])})")
            return None

    # Validate: no empty horse names
    empty_names = sum(1 for h in entries["horses"] if not h or not str(h).strip())
    if empty_names > num_horses * 0.3:
        print(f"  WARN: {race_id} too many empty horse names ({empty_names}/{num_horses})")
        return None

    return {
        "race_id_netkeiba": race_id,
        "race_name": race_name,
        "venue": venue,
        "race_number": race_number,
        "distance": distance,
        "track_condition": track_condition,
        **entries,
    }


# =============================================================================
# JRA スクレイピング
# =============================================================================

def fetch_jra_race_list(date_str):
    """JRA全レース一覧を取得"""
    url = f"{NETKEIBA_JRA_BASE}/top/race_list_sub.html?kaisai_date={date_str}"
    soup = fetch_soup(url, encoding="utf-8")
    if not soup:
        return []

    races = []
    current_venue = ""

    for dl in soup.select("dl.RaceList_DataList"):
        header = dl.select_one("p.RaceList_DataHeader, dt")
        if header:
            header_text = header.get_text(strip=True)
            for v in ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]:
                if v in header_text:
                    current_venue = v
                    break

        for li in dl.select("li"):
            a_tag = li.select_one("a")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if "race_id=" not in href:
                continue

            race_id = href.split("race_id=")[-1].split("&")[0]

            race_num_el = li.select_one(".Race_Num")
            race_number = 0
            if race_num_el:
                num_text = race_num_el.get_text(strip=True).replace("R", "")
                if num_text.isdigit():
                    race_number = int(num_text)

            race_name_el = li.select_one(".ItemTitle")
            race_name = race_name_el.get_text(strip=True) if race_name_el else f"{race_number}R"

            # 発走時刻
            start_time = ""
            time_el = li.select_one(".RaceList_ItemTime")
            if time_el:
                start_time = time_el.get_text(strip=True)

            distance = ""
            race_data = li.select_one(".RaceList_ItemLong")
            if race_data:
                for span in race_data.select("span"):
                    text = span.get_text(strip=True)
                    if "m" in text:
                        distance = text
                        break

            races.append({
                "race_id": race_id,
                "race_number": race_number,
                "race_name": race_name,
                "venue": current_venue,
                "distance": distance,
                "start_time": start_time,
                "is_nar": False,
            })

    return races


def fetch_jra_entries(race_id):
    """JRA個別レースの出馬表を取得"""
    url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"
    soup = fetch_soup(url, encoding="euc-jp")
    if not soup:
        return None

    # Validate HTML has race data
    race_table = soup.select_one("table.RaceTable01, table.Shutuba_Table")
    horse_rows = soup.select("tr.HorseList")
    if not race_table and not horse_rows:
        print(f"  WARN: {race_id} - 出馬表テーブルなし（HTML構造変更？）")
        return None

    race_name = ""
    race_name_el = soup.select_one(".RaceName")
    if race_name_el:
        race_name = race_name_el.get_text(strip=True)

    venue = ""
    distance = ""
    track_condition = "−"

    race_data1 = soup.select_one(".RaceData01")
    if race_data1:
        text = race_data1.get_text(strip=True)
        m = re.search(r'([芝ダ障]\d+m)', text)
        if m:
            distance = m.group(1)

    race_data2 = soup.select_one(".RaceData02")
    if race_data2:
        for span in race_data2.select("span"):
            text = span.get_text(strip=True)
            for v in ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]:
                if v in text:
                    venue = v
                    break

    race_number = 0
    if len(race_id) >= 12:
        try:
            race_number = int(race_id[10:12])
        except ValueError:
            pass

    entries = {
        "horses": [], "horse_numbers": [], "posts": [],
        "jockeys": [], "trainers": [], "sex_ages": [], "weights": [],
        "odds": [], "popularities": [],
    }

    for tr in soup.select("table.Shutuba_Table tr.HorseList, table.RaceTable01 tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 8:
            continue
        try:
            post = int(tds[0].get_text(strip=True)) if tds[0].get_text(strip=True).isdigit() else 0
            horse_number = int(tds[1].get_text(strip=True)) if tds[1].get_text(strip=True).isdigit() else 0

            horse_name_el = tds[3].select_one("a")
            horse_name = horse_name_el.get_text(strip=True) if horse_name_el else tds[3].get_text(strip=True)

            sex_age = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            weight_text = tds[5].get_text(strip=True) if len(tds) > 5 else "0"
            weight = float(weight_text) if weight_text.replace(".", "").isdigit() else 0.0

            jockey_el = tds[6].select_one("a")
            jockey = jockey_el.get_text(strip=True) if jockey_el else tds[6].get_text(strip=True)

            trainer_el = tds[7].select_one("a")
            trainer = trainer_el.get_text(strip=True) if trainer_el else tds[7].get_text(strip=True)

            odds = 0.0
            popularity = 0
            if len(tds) > 9:
                odds_text = tds[9].get_text(strip=True)
                if odds_text.replace(".", "").isdigit():
                    odds = float(odds_text)
            if len(tds) > 10:
                pop_text = tds[10].get_text(strip=True)
                if pop_text.isdigit():
                    popularity = int(pop_text)

            entries["horses"].append(horse_name)
            entries["horse_numbers"].append(horse_number)
            entries["posts"].append(post)
            entries["jockeys"].append(jockey)
            entries["trainers"].append(trainer)
            entries["sex_ages"].append(sex_age)
            entries["weights"].append(weight)
            entries["odds"].append(odds)
            entries["popularities"].append(popularity)

        except (ValueError, IndexError):
            continue

    # Validate: all arrays must be same length
    num_horses = len(entries["horses"])
    if num_horses == 0:
        return None

    array_keys = ["horse_numbers", "jockeys", "posts", "trainers", "sex_ages", "weights"]
    for key in array_keys:
        if len(entries[key]) != num_horses:
            print(f"  WARN: {race_id} {key} length mismatch (horses={num_horses}, {key}={len(entries[key])})")
            return None

    # Validate: no empty horse names
    empty_names = sum(1 for h in entries["horses"] if not h or not str(h).strip())
    if empty_names > num_horses * 0.3:
        print(f"  WARN: {race_id} too many empty horse names ({empty_names}/{num_horses})")
        return None

    return {
        "race_id_netkeiba": race_id,
        "race_name": race_name,
        "venue": venue,
        "race_number": race_number,
        "distance": distance,
        "track_condition": track_condition,
        **entries,
    }


# =============================================================================
# メイン
# =============================================================================

def prefetch_date(date_str, do_nar=True, do_jra=False):
    """指定日の全レースデータをプリフェッチしてJSON保存"""
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    print(f"\n{'='*60}")
    print(f"プリフェッチ: {formatted_date}")
    print(f"{'='*60}")

    all_races = []

    # NAR
    if do_nar:
        print(f"\n[NAR] レース一覧取得中...")
        nar_races = fetch_nar_race_list(date_str)
        print(f"  {len(nar_races)}レース発見")

        for i, race in enumerate(nar_races):
            print(f"  [{i+1}/{len(nar_races)}] {race['venue']} {race['race_number']}R {race['race_name']}...", end=" ", flush=True)
            detail = fetch_nar_entries(race['race_id'])
            if detail and detail.get('horses'):
                race_data = {
                    "race_id": f"{date_str}-{detail['venue']}-{detail['race_number']}",
                    "race_date": formatted_date,
                    "is_local": True,
                    "start_time": race.get("start_time", ""),
                    **detail,
                    "created_at": datetime.now().isoformat(),
                }
                all_races.append(race_data)
                print(f"{len(detail['horses'])}頭")
            else:
                print("SKIP (データなし)")
            time.sleep(0.5)  # サーバー負荷軽減

    # JRA
    if do_jra:
        print(f"\n[JRA] レース一覧取得中...")
        jra_races = fetch_jra_race_list(date_str)
        print(f"  {len(jra_races)}レース発見")

        for i, race in enumerate(jra_races):
            print(f"  [{i+1}/{len(jra_races)}] {race['venue']} {race['race_number']}R {race['race_name']}...", end=" ", flush=True)
            detail = fetch_jra_entries(race['race_id'])
            if detail and detail.get('horses'):
                race_data = {
                    "race_id": f"{date_str}-{detail['venue']}-{detail['race_number']}",
                    "race_date": formatted_date,
                    "is_local": False,
                    "start_time": race.get("start_time", ""),
                    **detail,
                    "created_at": datetime.now().isoformat(),
                }
                all_races.append(race_data)
                print(f"{len(detail['horses'])}頭")
            else:
                print("SKIP (データなし)")
            time.sleep(0.5)

    if not all_races:
        print(f"\nレースが見つかりません（{formatted_date}）")
        return None

    # JRA odds: Playwright batch fetch (JS rendering required)
    jra_races_needing_odds = [
        r for r in all_races
        if not r.get("is_local") and r.get("race_id_netkeiba")
        and (not r.get("odds") or all(o == 0.0 for o in r.get("odds", [])))
    ]
    if jra_races_needing_odds:
        print(f"\n[JRA] Playwrightでオッズ取得中... ({len(jra_races_needing_odds)}レース)")
        try:
            from scrapers.odds import fetch_jra_odds_batch
            netkeiba_ids = [r["race_id_netkeiba"] for r in jra_races_needing_odds]
            odds_results = fetch_jra_odds_batch(netkeiba_ids)
            updated = 0
            for race in jra_races_needing_odds:
                nid = race["race_id_netkeiba"]
                if nid in odds_results:
                    odds_map = odds_results[nid]
                    # Update odds array to match horse_numbers order
                    new_odds = []
                    for hn in race.get("horse_numbers", []):
                        new_odds.append(odds_map.get(hn, 0.0))
                    race["odds"] = new_odds
                    updated += 1
            print(f"  オッズ取得完了: {updated}/{len(jra_races_needing_odds)}レース")
        except Exception as e:
            print(f"  オッズ取得失敗: {e}")

    # 会場別にグループ化して統計
    venues = {}
    for race in all_races:
        v = race.get('venue', '不明')
        if v not in venues:
            venues[v] = 0
        venues[v] += 1

    # JSON保存
    output = {
        "metadata": {
            "date": date_str,
            "formatted_date": formatted_date,
            "created_at": datetime.now().isoformat(),
            "total_races": len(all_races),
            "venues": venues,
        },
        "races": all_races,
    }

    output_file = os.path.join(OUTPUT_DIR, f"races_{date_str}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(output_file) / 1024
    print(f"\n保存: {output_file} ({file_size:.1f}KB)")
    print(f"レース数: {len(all_races)}")
    print(f"会場: {venues}")

    return output_file


def main():
    args = sys.argv[1:]

    # 日付指定（なければ明日）
    date_str = None
    do_jra = False
    do_nar = True

    for arg in args:
        if arg == '--jra':
            do_jra = True
            do_nar = False
        elif arg == '--all':
            do_jra = True
            do_nar = True
        elif arg.isdigit() and len(arg) == 8:
            date_str = arg

    if not date_str:
        tomorrow = datetime.now() + timedelta(days=1)
        date_str = tomorrow.strftime('%Y%m%d')

    print("レースデータ プリフェッチ")
    print(f"対象: {'NAR' if do_nar else ''}{'+' if do_nar and do_jra else ''}{'JRA' if do_jra else ''}")

    prefetch_date(date_str, do_nar=do_nar, do_jra=do_jra)


if __name__ == "__main__":
    main()
