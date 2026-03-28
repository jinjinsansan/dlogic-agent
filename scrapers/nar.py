"""NAR (local) race scraper - library form adapted from fetch_nar_entries.py."""

import logging
import re
from dataclasses import dataclass, field
from scrapers.base import fetch_with_retry
from scrapers.jra import RaceSummary, HorseEntry, RaceDetail
from scrapers.validators import validate_entry, validate_html_has_race_data, validate_race_metadata
from config import NETKEIBA_NAR_BASE

logger = logging.getLogger(__name__)

# All supported NAR venues (single source of truth)
NAR_VENUES = [
    "大井", "川崎", "船橋", "浦和", "園田", "姫路", "名古屋", "笠松",
    "高知", "佐賀", "水沢", "盛岡", "門別", "帯広", "金沢",
]


def fetch_race_list(date_str: str, venue_filter: str = "") -> list[RaceSummary]:
    """Fetch NAR race list for a given date (YYYYMMDD). Optionally filter by venue name."""
    races = []
    url = f"{NETKEIBA_NAR_BASE}/top/race_list_sub.html?kaisai_date={date_str}"
    soup = fetch_with_retry(url, encoding="utf-8")
    if not soup:
        return races

    current_venue = ""
    for dl in soup.select("dl.RaceList_DataList"):
        # Venue name from header
        header = dl.select_one("p.RaceList_DataHeader, dt")
        if header:
            header_text = header.get_text(strip=True)
            for v in NAR_VENUES:
                if v in header_text:
                    current_venue = v
                    break

        if venue_filter and venue_filter not in current_venue:
            continue

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

            distance = ""
            race_data = li.select_one(".RaceList_ItemLong")
            if race_data:
                for span in race_data.select("span"):
                    text = span.get_text(strip=True)
                    if "m" in text:
                        distance = text
                        break
                # Also check CSS class for track type
                for cls_name in ["Dart", "Shiba"]:
                    if race_data.select_one(f".{cls_name}"):
                        if "ダ" not in distance and cls_name == "Dart":
                            distance = "ダ" + distance
                        elif "芝" not in distance and cls_name == "Shiba":
                            distance = "芝" + distance

            headcount = 0
            headcount_el = li.select_one(".RaceList_ItemLong span")
            if headcount_el:
                hc_text = headcount_el.get_text(strip=True)
                if "頭" in hc_text:
                    hc_num = hc_text.replace("頭", "").strip()
                    if hc_num.isdigit():
                        headcount = int(hc_num)

            start_time = ""
            time_el = li.select_one(".RaceList_ItemTime")
            if time_el:
                start_time = time_el.get_text(strip=True)

            races.append(RaceSummary(
                race_id=race_id,
                race_number=race_number,
                race_name=race_name,
                venue=current_venue,
                distance=distance,
                headcount=headcount,
                start_time=start_time,
            ))

    return races


def fetch_race_entries(race_id: str) -> RaceDetail | None:
    """Fetch detailed entries for a specific NAR race.

    Returns None if page can't be fetched or data is invalid.
    """
    url = f"{NETKEIBA_NAR_BASE}/race/shutuba.html?race_id={race_id}"
    soup = fetch_with_retry(url, encoding="euc-jp")
    if not soup:
        return None

    # Validate HTML contains race data
    html_ok, html_err = validate_html_has_race_data(soup, race_id)
    if not html_ok:
        logger.warning(f"NAR HTML validation failed: {html_err}")
        return None

    race_name = ""
    race_name_el = soup.select_one(".RaceName")
    if race_name_el:
        race_name = race_name_el.get_text(strip=True)

    venue = ""
    distance = ""
    # Track condition — use "−" (dash) if not found, NOT "良"
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
            for v in NAR_VENUES:
                if v in text:
                    venue = v
                    break

    race_number = 0
    if len(race_id) >= 12:
        try:
            race_number = int(race_id[10:12])
        except ValueError:
            pass

    # Log metadata warnings
    meta_warnings = validate_race_metadata(race_name, venue, distance, race_id)
    for w in meta_warnings:
        logger.warning(f"NAR metadata: {w}")

    summary = RaceSummary(
        race_id=race_id,
        race_number=race_number,
        race_name=race_name,
        venue=venue,
        distance=distance,
        headcount=0,
    )

    entries = []
    skipped = 0
    for tr in soup.select("table.RaceTable01 tr.HorseList, tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 8:
            continue

        try:
            post = int(tds[0].get_text(strip=True)) if tds[0].get_text(strip=True).isdigit() else 0
            horse_number = int(tds[1].get_text(strip=True)) if tds[1].get_text(strip=True).isdigit() else 0

            # Fallback: netkeiba renders waku/umaban via JS — extract from tr id="tr_N"
            if horse_number <= 0:
                tr_id = tr.get("id", "")
                if tr_id.startswith("tr_"):
                    num_str = tr_id[3:]
                    if num_str.isdigit():
                        horse_number = int(num_str)

            horse_name_el = tds[3].select_one("a") if len(tds) > 3 else None
            horse_name = horse_name_el.get_text(strip=True) if horse_name_el else tds[3].get_text(strip=True)

            sex_age = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            weight_text = tds[5].get_text(strip=True) if len(tds) > 5 else "0"
            weight = int(float(weight_text)) if weight_text.replace(".", "").isdigit() else 0

            jockey_el = tds[6].select_one("a")
            jockey = jockey_el.get_text(strip=True) if jockey_el else tds[6].get_text(strip=True)

            trainer_el = tds[7].select_one("a")
            trainer = trainer_el.get_text(strip=True) if trainer_el else tds[7].get_text(strip=True)

            # Validate individual entry
            entry_warnings = validate_entry(horse_name, horse_number, jockey, post, len(entries))
            if entry_warnings:
                if not horse_name.strip() or horse_number <= 0:
                    for w in entry_warnings:
                        logger.warning(f"NAR {race_id} skipped: {w}")
                    skipped += 1
                    continue
                for w in entry_warnings:
                    logger.warning(f"NAR {race_id}: {w}")

            entries.append(HorseEntry(
                horse_number=horse_number,
                horse_name=horse_name,
                jockey=jockey,
                trainer=trainer,
                post=post,
                sex_age=sex_age,
                weight=weight,
            ))
        except (ValueError, IndexError) as e:
            logger.warning(f"NAR {race_id}: entry parse error: {e}")
            skipped += 1
            continue

    if skipped > 0:
        logger.warning(f"NAR {race_id}: {skipped}頭スキップ, {len(entries)}頭有効")

    # Final validation: must have at least 2 horses
    if len(entries) < 2:
        logger.error(f"NAR {race_id}: 出走馬が{len(entries)}頭のみ — データ不正の可能性")
        return None

    summary.headcount = len(entries)

    return RaceDetail(summary=summary, entries=entries, track_condition=track_condition)
