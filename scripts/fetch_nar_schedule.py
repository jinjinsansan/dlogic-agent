"""Fetch NAR (地方競馬) race schedules from official keiba.go.jp website.

Builds a schedule master JSON mapping dates to venues for all NAR tracks.
Used to correct unreliable PCKEIBA venue codes.
"""

import json
import os
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# NAR official calendar URL
CALENDAR_URL = "https://www.keiba.go.jp/KeibaWeb/MonthlyConveneInfo/MonthlyConveneInfoTop"

# NAR website babaCode -> PCKEIBA keibajo_code mapping
# NAR site uses its own codes; PCKEIBA uses different ones
BABA_TO_VENUE = {
    "3": {"name": "帯広", "pckeiba_code": "83"},
    "36": {"name": "門別", "pckeiba_code": "30"},
    "10": {"name": "盛岡", "pckeiba_code": "35"},
    "11": {"name": "水沢", "pckeiba_code": "36"},
    "18": {"name": "浦和", "pckeiba_code": "45"},
    "19": {"name": "船橋", "pckeiba_code": "43"},
    "20": {"name": "大井", "pckeiba_code": "42"},
    "21": {"name": "川崎", "pckeiba_code": "44"},
    "22": {"name": "金沢", "pckeiba_code": "46"},
    "23": {"name": "笠松", "pckeiba_code": "47"},
    "24": {"name": "名古屋", "pckeiba_code": "48"},
    "27": {"name": "園田", "pckeiba_code": "50"},
    "28": {"name": "姫路", "pckeiba_code": "51"},
    "31": {"name": "高知", "pckeiba_code": "54"},
    "32": {"name": "佐賀", "pckeiba_code": "55"},
}

# Reverse: PCKEIBA code -> venue name
PCKEIBA_VENUE_MAP = {v["pckeiba_code"]: v["name"] for v in BABA_TO_VENUE.values()}


def fetch_month_schedule(year: int, month: int) -> dict[str, list[str]]:
    """
    Fetch one month's schedule from NAR official site.

    Returns:
        dict mapping "YYYYMMDD" -> list of PCKEIBA venue codes
        e.g. {"20240601": ["83"], "20240602": ["83", "46"]}
    """
    r = requests.get(
        CALENDAR_URL,
        params={"k_year": str(year), "k_month": str(month)},
        timeout=15,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")
    if not table:
        return {}

    rows = table.find_all("tr")
    schedule = {}

    for row in rows[1:]:  # skip header
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        venue_name = cells[0].get_text(strip=True)
        if not venue_name:
            continue

        # Extract babaCode from links
        baba_code = ""
        for link in row.find_all("a"):
            href = link.get("href", "")
            if "k_babaCode" in href:
                baba_code = href.split("k_babaCode=")[-1].split("&")[0]
                break

        if baba_code not in BABA_TO_VENUE:
            continue

        pckeiba_code = BABA_TO_VENUE[baba_code]["pckeiba_code"]

        # Check each day cell for race markers
        for i, cell in enumerate(cells[1:], 1):
            text = cell.get_text(strip=True)
            if any(c in text for c in ["●", "☆", "Ｄ"]):
                date_str = f"{year}{month:02d}{i:02d}"
                if date_str not in schedule:
                    schedule[date_str] = []
                if pckeiba_code not in schedule[date_str]:
                    schedule[date_str].append(pckeiba_code)

    return schedule


def fetch_all_schedules(start_year: int, end_year: int) -> dict[str, list[str]]:
    """Fetch schedules for all months in the given year range."""
    all_schedule = {}
    total_months = (end_year - start_year + 1) * 12
    current = 0

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            current += 1
            # Skip future months
            now = datetime.now()
            if year > now.year or (year == now.year and month > now.month + 1):
                continue

            print(f"  [{current}/{total_months}] {year}/{month:02d}...", end=" ", flush=True)
            try:
                month_data = fetch_month_schedule(year, month)
                all_schedule.update(month_data)
                print(f"{len(month_data)} days")
            except Exception as e:
                print(f"ERROR: {e}")

            # Be polite to the server
            time.sleep(0.5)

    return all_schedule


def main():
    start_year = 2020
    end_year = 2026

    print(f"=== NAR開催スケジュール取得 ({start_year}〜{end_year}) ===")
    print(f"ソース: {CALENDAR_URL}")
    print()

    schedule = fetch_all_schedules(start_year, end_year)

    # Sort by date
    schedule = dict(sorted(schedule.items()))

    # Build output
    output = {
        "metadata": {
            "created": datetime.now().isoformat(),
            "period": f"{start_year}-01-01 to {end_year}-12-31",
            "total_race_days": len(schedule),
            "source": "NAR公式サイト (keiba.go.jp)",
            "venues": PCKEIBA_VENUE_MAP,
            "baba_to_pckeiba": {k: v["pckeiba_code"] for k, v in BABA_TO_VENUE.items()},
        },
        "schedule_data": schedule,
    }

    # Stats
    venue_counts = {}
    for codes in schedule.values():
        for code in codes:
            name = PCKEIBA_VENUE_MAP.get(code, code)
            venue_counts[name] = venue_counts.get(name, 0) + 1

    print(f"\n=== 結果 ===")
    print(f"総開催日数: {len(schedule)}")
    print(f"\n競馬場別開催日数:")
    for name, count in sorted(venue_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}日")

    # Save
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "nar_schedule_master_2020_2026.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n保存先: {out_path}")
    print(f"ファイルサイズ: {os.path.getsize(out_path) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
