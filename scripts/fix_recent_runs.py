"""Fix recent-runs key mapping in backend viewlogic_analysis.py"""

path = "/opt/dlogic/backend/api/v2/viewlogic_analysis.py"
with open(path, "r") as f:
    content = f.read()

old_block = '''                history = engine.get_horse_history(horse_name)
                races = history.get("races", [])[:5]
                runs = []
                for r in races:
                    runs.append({
                        "date": r.get("date", r.get("KAISAI_NENGAPPI", "")),
                        "venue": r.get("venue", r.get("KEIBAJO_MEI", "")),
                        "distance": r.get("distance", r.get("KYORI", "")),
                        "finish": r.get("finish", r.get("KAKUTEI_CHAKUJUN", 0)),
                        "jockey": r.get("jockey", r.get("KISHUMEI_RYAKUSHO", "")),
                        "odds": r.get("odds", r.get("TANSHO_ODDS", 0)),
                    })'''

new_block = '''                history = engine.get_horse_history(horse_name)
                races = history.get("races", [])[:5]
                runs = []
                for r in races:
                    import re as _re
                    # Support Japanese keys from get_horse_history()
                    finish_raw = r.get("finish", r.get("\u7740\u9806", r.get("KAKUTEI_CHAKUJUN", 0)))
                    if isinstance(finish_raw, str):
                        _m = _re.search(r"(\\d+)", str(finish_raw))
                        finish_raw = int(_m.group(1)) if _m else 0
                    odds_raw = r.get("odds", r.get("TANSHO_ODDS", 0))
                    if isinstance(odds_raw, str):
                        _m = _re.search(r"([\\d.]+)", str(odds_raw))
                        odds_raw = float(_m.group(1)) if _m else 0
                    runs.append({
                        "date": r.get("date", r.get("\u958b\u50ac\u65e5", r.get("KAISAI_NENGAPPI", ""))),
                        "venue": r.get("venue", r.get("\u7af6\u99ac\u5834", r.get("KEIBAJO_MEI", ""))),
                        "distance": r.get("distance", r.get("\u8ddd\u96e2", r.get("KYORI", ""))),
                        "finish": finish_raw,
                        "jockey": r.get("jockey", r.get("\u9a0e\u624b", r.get("KISHUMEI_RYAKUSHO", ""))),
                        "odds": odds_raw,
                    })'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w") as f:
        f.write(content)
    print("FIXED")
else:
    print("Pattern not found")
    idx = content.find("get_horse_history(horse_name)")
    if idx >= 0:
        print(content[idx:idx+600])
