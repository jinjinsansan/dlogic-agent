"""今日の golden-pattern/today を nar/both で叩いてLayer 1該当を確認 (一時)。"""
import json
import sys
import urllib.request

DATE = sys.argv[1] if len(sys.argv) > 1 else "20260505"

for label, url in [
    ("HTTPS race_type=nar (frontend path)",
     f"https://bot.dlogicai.in/api/data/golden-pattern/today?date={DATE}&race_type=nar"),
    ("LOCAL race_type=both (telegram path)",
     f"http://localhost:5000/api/data/golden-pattern/today?date={DATE}&race_type=both"),
]:
    print(f"\n=== {label} ===")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            d = json.loads(r.read())
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    races = d.get("races") or []
    strict = [r for r in races if r.get("is_golden_strict")]
    print(f"  weekday={d.get('weekday')}, date={d.get('date')}, "
          f"total_races={len(races)}, layer1_strict={len(strict)}")
    for r in strict[:8]:
        cons = r.get("consensus") or {}
        print(f"    - {r.get('venue')} {r.get('race_number')}R  "
              f"{cons.get('horse_name','')}  pop={r.get('popularity_rank')}  "
              f"agreed={cons.get('count')}")
    summary = d.get("summary") or {}
    if summary:
        print(f"  summary: {summary}")
