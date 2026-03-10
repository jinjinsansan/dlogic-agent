"""JRA race scraper - library form adapted from fetch_jra_entries.py."""

from dataclasses import dataclass, field
from scrapers.base import fetch_with_retry
from config import NETKEIBA_JRA_BASE


@dataclass
class RaceSummary:
    race_id: str
    race_number: int
    race_name: str
    venue: str
    distance: str
    headcount: int
    start_time: str = ""


@dataclass
class HorseEntry:
    horse_number: int
    horse_name: str
    jockey: str
    trainer: str
    post: int
    sex_age: str = ""
    weight: int = 0


@dataclass
class RaceDetail:
    summary: RaceSummary
    entries: list[HorseEntry] = field(default_factory=list)
    track_condition: str = "良"


def fetch_race_list(date_str: str) -> list[RaceSummary]:
    """Fetch JRA race list for a given date (YYYYMMDD). Returns list of RaceSummary."""
    races = []

    # Step 1: Get available groups for this date
    url = f"{NETKEIBA_JRA_BASE}/top/race_list_get_date_list.html?kaisai_date={date_str}"
    soup = fetch_with_retry(url, encoding="utf-8")
    if not soup:
        return races

    # Extract group IDs
    groups = []
    for a_tag in soup.select("a"):
        href = a_tag.get("href", "")
        if "current_group=" in href:
            group_id = href.split("current_group=")[-1].split("&")[0]
            if group_id and group_id not in groups:
                groups.append(group_id)

    # Step 2: Fetch races for each group
    for group in groups:
        list_url = f"{NETKEIBA_JRA_BASE}/top/race_list_sub.html?kaisai_date={date_str}&current_group={group}"
        list_soup = fetch_with_retry(list_url, encoding="utf-8")
        if not list_soup:
            continue

        # Parse venue name from header
        venue_name = ""
        header = list_soup.select_one(".RaceList_DataHeader")
        if header:
            venue_text = header.get_text(strip=True)
            # Extract venue name (e.g., "1回中山1日目" -> "中山")
            for v in ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]:
                if v in venue_text:
                    venue_name = v
                    break

        # Parse race list
        for dl in list_soup.select("dl.RaceList_DataList"):
            for li in dl.select("li"):
                a_tag = li.select_one("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                if "race_id=" not in href:
                    continue

                race_id = href.split("race_id=")[-1].split("&")[0]

                # Race number
                race_num_el = li.select_one(".Race_Num")
                race_number = 0
                if race_num_el:
                    num_text = race_num_el.get_text(strip=True).replace("R", "")
                    if num_text.isdigit():
                        race_number = int(num_text)

                # Race name
                race_name_el = li.select_one(".ItemTitle")
                race_name = race_name_el.get_text(strip=True) if race_name_el else f"{race_number}R"

                # Distance & headcount
                distance = ""
                headcount = 0
                race_data = li.select_one(".RaceList_ItemLong")
                if race_data:
                    spans = race_data.select("span")
                    for span in spans:
                        text = span.get_text(strip=True)
                        if "m" in text and ("芝" in text or "ダ" in text or "障" in text):
                            distance = text
                        if "頭" in text:
                            headcount = int(text.replace("頭", "").strip()) if text.replace("頭", "").strip().isdigit() else 0

                # Start time
                start_time = ""
                time_el = li.select_one(".RaceList_ItemTime")
                if time_el:
                    start_time = time_el.get_text(strip=True)

                races.append(RaceSummary(
                    race_id=race_id,
                    race_number=race_number,
                    race_name=race_name,
                    venue=venue_name,
                    distance=distance,
                    headcount=headcount,
                    start_time=start_time,
                ))

    return races


def fetch_race_entries(race_id: str) -> RaceDetail | None:
    """Fetch detailed entries for a specific JRA race."""
    url = f"{NETKEIBA_JRA_BASE}/race/shutuba.html?race_id={race_id}"
    soup = fetch_with_retry(url, encoding="euc-jp")
    if not soup:
        return None

    # Parse race metadata
    race_name = ""
    race_name_el = soup.select_one(".RaceName")
    if race_name_el:
        race_name = race_name_el.get_text(strip=True)

    venue = ""
    distance = ""
    race_data = soup.select_one(".RaceData01")
    if race_data:
        text = race_data.get_text(strip=True)
        # Extract distance like "芝2000m" or "ダ1200m"
        import re
        m = re.search(r'([芝ダ障]\d+m)', text)
        if m:
            distance = m.group(1)

    race_data2 = soup.select_one(".RaceData02")
    if race_data2:
        spans = race_data2.select("span")
        for span in spans:
            text = span.get_text(strip=True)
            for v in ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]:
                if v in text:
                    venue = v
                    break

    # Extract race number from race_id
    race_number = 0
    if len(race_id) >= 12:
        try:
            race_number = int(race_id[10:12])
        except ValueError:
            pass

    summary = RaceSummary(
        race_id=race_id,
        race_number=race_number,
        race_name=race_name,
        venue=venue,
        distance=distance,
        headcount=0,
    )

    # Parse horse entries
    entries = []
    for tr in soup.select("tr.HorseList"):
        tds = tr.select("td")
        if len(tds) < 8:
            continue

        try:
            post = int(tds[0].get_text(strip=True)) if tds[0].get_text(strip=True).isdigit() else 0
            horse_number = int(tds[1].get_text(strip=True)) if tds[1].get_text(strip=True).isdigit() else 0

            # Horse name (td[3] for JRA)
            horse_name_el = tds[3].select_one("a")
            horse_name = horse_name_el.get_text(strip=True) if horse_name_el else tds[3].get_text(strip=True)

            sex_age = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            weight_text = tds[5].get_text(strip=True) if len(tds) > 5 else "0"
            weight = int(float(weight_text)) if weight_text.replace(".", "").isdigit() else 0

            # Jockey (td[6])
            jockey_el = tds[6].select_one("a")
            jockey = jockey_el.get_text(strip=True) if jockey_el else tds[6].get_text(strip=True)

            # Trainer (td[7])
            trainer_el = tds[7].select_one("a")
            trainer = trainer_el.get_text(strip=True) if trainer_el else tds[7].get_text(strip=True)

            entries.append(HorseEntry(
                horse_number=horse_number,
                horse_name=horse_name,
                jockey=jockey,
                trainer=trainer,
                post=post,
                sex_age=sex_age,
                weight=weight,
            ))
        except (ValueError, IndexError):
            continue

    summary.headcount = len(entries)

    return RaceDetail(summary=summary, entries=entries)
