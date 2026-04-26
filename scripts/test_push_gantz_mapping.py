#!/usr/bin/env python3
"""push_gantz_to_horse のマッピングロジックのオフラインテスト.

実 API 呼び出しなしで、ダミーレースから signal row が正しく生成されるか確認。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from push_gantz_to_horse import (  # noqa: E402
    race_to_signal_row,
    resolve_jo_code,
    build_note,
    date_to_iso,
)


def test_resolve_jo_code():
    assert resolve_jo_code("船橋", True) == "34"
    assert resolve_jo_code("園田", True) == "40"
    assert resolve_jo_code("東京", False) == "05"
    assert resolve_jo_code("UnknownVenue", True) is None
    # mismatch: 東京 reported as is_local
    assert resolve_jo_code("東京", True) is None
    print("[OK] resolve_jo_code")


def test_date_to_iso():
    assert date_to_iso("20260426") == "2026-04-26"
    print("[OK] date_to_iso")


def test_build_note():
    race = {
        "consensus": {
            "horse_number": 5,
            "horse_name": "ヒロイン",
            "agreed_engines": ["Dlogic", "Ilogic", "ViewLogic"],
            "count": 3,
        },
        "popularity_rank": 6,
        "start_time": "15:25",
    }
    note = build_note(race)
    assert "5番ヒロイン" in note
    assert "6人気" in note
    assert "15:25" in note
    assert "3/4" in note
    assert "D+I+V" in note
    print(f"[OK] build_note: {note}")


def test_race_to_signal_row_nar():
    race = {
        "race_id": "20260426-船橋-7",
        "venue": "船橋",
        "race_number": 7,
        "race_name": "C2",
        "start_time": "15:25",
        "is_local": True,
        "consensus": {
            "horse_number": 5,
            "horse_name": "ヒロイン",
            "agreed_engines": ["Dlogic", "Ilogic", "ViewLogic"],
            "count": 3,
        },
        "popularity_rank": 6,
        "is_golden_strict": True,
    }
    row = race_to_signal_row(race, "2026-04-26", "gantz_strict")
    assert row is not None
    assert row["signal_date"] == "2026-04-26"
    assert row["race_type"] == "NAR"
    assert row["jo_code"] == "34"
    assert row["jo_name"] == "船橋"
    assert row["race_no"] == 7
    assert row["bet_type"] == 1
    assert row["bet_type_name"] == "単勝"
    assert row["method"] == 0
    assert row["suggested_amount"] == 100
    assert row["kaime_data"] == ["5"]
    assert row["status"] == "active"
    assert row["start_time"] == "15:25"
    assert row["source"] == "gantz_strict"
    assert row["created_by"] is None
    print(f"[OK] race_to_signal_row NAR: {json.dumps(row, ensure_ascii=False)}")


def test_race_to_signal_row_jra():
    race = {
        "race_id": "20260426-東京-11",
        "venue": "東京",
        "race_number": 11,
        "start_time": "15:40",
        "is_local": False,
        "consensus": {"horse_number": 8, "horse_name": "サンプル", "agreed_engines": ["Dlogic"], "count": 2},
        "popularity_rank": 3,
    }
    row = race_to_signal_row(race, "2026-04-26", "gantz_strict")
    assert row is not None
    assert row["race_type"] == "JRA"
    assert row["jo_code"] == "05"
    assert row["kaime_data"] == ["8"]
    print(f"[OK] race_to_signal_row JRA: jo_code={row['jo_code']}")


def test_race_to_signal_row_invalid():
    # missing horse_number
    race = {"venue": "船橋", "race_number": 7, "is_local": True, "consensus": {}}
    assert race_to_signal_row(race, "2026-04-26", "gantz_strict") is None
    # unknown venue
    race = {"venue": "火星", "race_number": 7, "is_local": True,
            "consensus": {"horse_number": 1}}
    assert race_to_signal_row(race, "2026-04-26", "gantz_strict") is None
    # missing race_number
    race = {"venue": "船橋", "is_local": True, "consensus": {"horse_number": 1}}
    assert race_to_signal_row(race, "2026-04-26", "gantz_strict") is None
    print("[OK] race_to_signal_row invalid cases")


if __name__ == "__main__":
    test_resolve_jo_code()
    test_date_to_iso()
    test_build_note()
    test_race_to_signal_row_nar()
    test_race_to_signal_row_jra()
    test_race_to_signal_row_invalid()
    print("\nAll tests passed.")
