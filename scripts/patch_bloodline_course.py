"""Patch viewlogic_analysis.py to add sire/broodmare course stats to bloodline-analysis endpoint.

Usage on VPS:
  python3 /tmp/patch_bloodline_course.py
"""
import re

FILE = "/opt/dlogic/backend/api/v2/viewlogic_analysis.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Backup
with open(FILE + ".bak", "w", encoding="utf-8") as f:
    f.write(content)
print("Backup saved to", FILE + ".bak")

# ── 1. Add course caches ──
content = content.replace(
    "_broodmare_stats_cache: Dict[str, Dict[str, Dict[str, int]]] = {}\n_bloodline_cache_built = False",
    "_broodmare_stats_cache: Dict[str, Dict[str, Dict[str, int]]] = {}\n"
    "_sire_course_cache: Dict[str, Dict[str, Dict[str, int]]] = {}\n"
    "_broodmare_course_cache: Dict[str, Dict[str, Dict[str, int]]] = {}\n"
    "_bloodline_cache_built = False",
)

# ── 2. Update global declaration ──
content = content.replace(
    "global _sire_stats_cache, _broodmare_stats_cache, _bloodline_cache_built",
    "global _sire_stats_cache, _broodmare_stats_cache, _sire_course_cache, _broodmare_course_cache, _bloodline_cache_built",
)

# ── 3. Add VENUE_CODE_MAP + course collection in the loop ──
# Replace from "    sire_stats = {}" to the end of the function
old_body = '''    sire_stats = {}
    broodmare_stats = {}
    for source in [all_horses, jra_horses]:
        for hname, hdata in source.items():
            races = hdata.get("races", []) if isinstance(hdata, dict) else hdata
            if not races:
                continue
            sire = ""
            bms = ""
            for r in races:
                if isinstance(r, dict):
                    if not sire:
                        sire = (r.get("sire") or r.get("BAMEI_FATHER") or "").strip()
                    if not bms:
                        bms = (r.get("broodmare_sire") or r.get("BAMEI_MOTHER_FATHER") or "").strip()
                    if sire and bms:
                        break
            for r in races:
                if not isinstance(r, dict):
                    continue
                tc = r.get("TRACK_CODE", "")
                baba = r.get("SHIBA_BABAJOTAI_CODE", "0") if tc.startswith("1") else r.get("DIRT_BABAJOTAI_CODE", "0")
                if baba == "0":
                    continue
                try:
                    finish = int(r.get("KAKUTEI_CHAKUJUN", "99"))
                except (ValueError, TypeError):
                    continue
                if finish <= 0 or finish > 30:
                    continue
                baba_name = BABA_CODE_MAP.get(baba, "")
                if not baba_name:
                    continue
                if sire:
                    sire_stats.setdefault(sire, {}).setdefault(baba_name, {"runs": 0, "place": 0})
                    sire_stats[sire][baba_name]["runs"] += 1
                    if finish <= 3:
                        sire_stats[sire][baba_name]["place"] += 1
                if bms:
                    broodmare_stats.setdefault(bms, {}).setdefault(baba_name, {"runs": 0, "place": 0})
                    broodmare_stats[bms][baba_name]["runs"] += 1
                    if finish <= 3:
                        broodmare_stats[bms][baba_name]["place"] += 1

    _sire_stats_cache = sire_stats
    _broodmare_stats_cache = broodmare_stats
    _bloodline_cache_built = True
    logger.info("血統キャッシュ構築完了: 父%d種, 母父%d種", len(sire_stats), len(broodmare_stats))'''

new_body = '''    VENUE_CODE_MAP = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
        "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
        "30": "門別", "31": "帯広", "35": "盛岡", "36": "水沢",
        "42": "浦和", "43": "船橋", "44": "大井", "45": "川崎",
        "46": "金沢", "47": "笠松", "48": "名古屋", "50": "園田",
        "51": "姫路", "54": "高知", "55": "佐賀",
    }

    sire_stats = {}
    broodmare_stats = {}
    sire_course = {}
    broodmare_course = {}
    for source in [all_horses, jra_horses]:
        for hname, hdata in source.items():
            races = hdata.get("races", []) if isinstance(hdata, dict) else hdata
            if not races:
                continue
            sire = ""
            bms = ""
            for r in races:
                if isinstance(r, dict):
                    if not sire:
                        sire = (r.get("sire") or r.get("BAMEI_FATHER") or "").strip()
                    if not bms:
                        bms = (r.get("broodmare_sire") or r.get("BAMEI_MOTHER_FATHER") or "").strip()
                    if sire and bms:
                        break
            for r in races:
                if not isinstance(r, dict):
                    continue
                tc = r.get("TRACK_CODE", "")
                baba = r.get("SHIBA_BABAJOTAI_CODE", "0") if tc.startswith("1") else r.get("DIRT_BABAJOTAI_CODE", "0")
                try:
                    finish = int(r.get("KAKUTEI_CHAKUJUN", "99"))
                except (ValueError, TypeError):
                    continue
                if finish <= 0 or finish > 30:
                    continue

                # 馬場状態別 (既存)
                if baba != "0":
                    baba_name = BABA_CODE_MAP.get(baba, "")
                    if baba_name:
                        if sire:
                            sire_stats.setdefault(sire, {}).setdefault(baba_name, {"runs": 0, "place": 0})
                            sire_stats[sire][baba_name]["runs"] += 1
                            if finish <= 3:
                                sire_stats[sire][baba_name]["place"] += 1
                        if bms:
                            broodmare_stats.setdefault(bms, {}).setdefault(baba_name, {"runs": 0, "place": 0})
                            broodmare_stats[bms][baba_name]["runs"] += 1
                            if finish <= 3:
                                broodmare_stats[bms][baba_name]["place"] += 1

                # コース別 (新規: venue x distance)
                venue_code = r.get("KEIBAJO_CODE", "")
                venue_name = VENUE_CODE_MAP.get(venue_code, "")
                dist_raw = r.get("KYORI", "0")
                try:
                    dist_m = int(dist_raw)
                except (ValueError, TypeError):
                    dist_m = 0
                if venue_name and dist_m > 0:
                    track_label = "芝" if tc.startswith("1") else "ダ"
                    course_key = f"{venue_name}{track_label}{dist_m}m"
                    if sire:
                        sire_course.setdefault(sire, {}).setdefault(course_key, {"runs": 0, "wins": 0, "place": 0})
                        sire_course[sire][course_key]["runs"] += 1
                        if finish == 1:
                            sire_course[sire][course_key]["wins"] += 1
                        if finish <= 3:
                            sire_course[sire][course_key]["place"] += 1
                    if bms:
                        broodmare_course.setdefault(bms, {}).setdefault(course_key, {"runs": 0, "wins": 0, "place": 0})
                        broodmare_course[bms][course_key]["runs"] += 1
                        if finish == 1:
                            broodmare_course[bms][course_key]["wins"] += 1
                        if finish <= 3:
                            broodmare_course[bms][course_key]["place"] += 1

    _sire_stats_cache = sire_stats
    _broodmare_stats_cache = broodmare_stats
    _sire_course_cache = sire_course
    _broodmare_course_cache = broodmare_course
    _bloodline_cache_built = True
    logger.info("血統キャッシュ構築完了: 父%d種, 母父%d種 (コース別: 父%d種, 母父%d種)",
                len(sire_stats), len(broodmare_stats), len(sire_course), len(broodmare_course))'''

content = content.replace(old_body, new_body)

# ── 4. Add _get_course_performance helper ──
old_helper_end = '''    overall_rate = round(total_place / total_runs * 100, 1) if total_runs > 0 else 0
    return {"total_races": total_runs, "place_rate": overall_rate, "by_condition": by_condition}


@router.post("/bloodline-analysis")'''

new_helper_end = '''    overall_rate = round(total_place / total_runs * 100, 1) if total_runs > 0 else 0
    return {"total_races": total_runs, "place_rate": overall_rate, "by_condition": by_condition}


def _get_course_performance(course_cache, name, venue, distance_str):
    """指定コース（venue x distance）での産駒成績を返す"""
    if not name or name not in course_cache:
        return None
    import re as _re
    dist_match = _re.search(r'(\\d+)', distance_str or "")
    dist_m = int(dist_match.group(1)) if dist_match else 0
    track_label = "芝" if "芝" in (distance_str or "") else "ダ"

    if not venue or dist_m == 0:
        return None

    course_key = f"{venue}{track_label}{dist_m}m"
    courses = course_cache.get(name, {})
    if course_key not in courses:
        return None
    d = courses[course_key]
    runs = d["runs"]
    if runs == 0:
        return None
    return {
        "course_key": course_key,
        "total_runs": runs,
        "wins": d["wins"],
        "place_count": d["place"],
        "win_rate": round(d["wins"] / runs * 100, 1),
        "place_rate": round(d["place"] / runs * 100, 1),
    }


@router.post("/bloodline-analysis")'''

content = content.replace(old_helper_end, new_helper_end)

# ── 5. Update endpoint to include course stats per horse ──
old_append = '''                bloodline_data.append({
                    "horse_name": horse_name,
                    "horse_number": request.horse_numbers[idx] if idx < len(request.horse_numbers) else 0,
                    "sire": sire,
                    "broodmare_sire": broodmare_sire,
                    "sire_performance": _get_performance(_sire_stats_cache, sire),
                    "broodmare_performance": _get_performance(_broodmare_stats_cache, broodmare_sire),
                })'''

new_append = '''                sire_cs = _get_course_performance(_sire_course_cache, sire, request.venue, request.distance)
                bms_cs = _get_course_performance(_broodmare_course_cache, broodmare_sire, request.venue, request.distance)
                entry = {
                    "horse_name": horse_name,
                    "horse_number": request.horse_numbers[idx] if idx < len(request.horse_numbers) else 0,
                    "sire": sire,
                    "broodmare_sire": broodmare_sire,
                    "sire_performance": _get_performance(_sire_stats_cache, sire),
                    "broodmare_performance": _get_performance(_broodmare_stats_cache, broodmare_sire),
                }
                if sire_cs:
                    entry["sire_course_stats"] = sire_cs
                if bms_cs:
                    entry["broodmare_course_stats"] = bms_cs
                bloodline_data.append(entry)'''

content = content.replace(old_append, new_append)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched successfully!")
print(f"File size: {len(content)} bytes")
