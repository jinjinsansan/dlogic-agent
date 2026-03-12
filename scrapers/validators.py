"""Data validation for scraped race data.

Ensures data integrity before serving to users.
Catches scraping failures, HTML structure changes, and partial data.
"""

import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when scraped data fails validation."""
    pass


def validate_entry(horse_name: str, horse_number: int, jockey: str,
                   post: int = 0, index: int = 0) -> list[str]:
    """Validate a single horse entry. Returns list of warnings (empty = OK)."""
    warnings = []

    if not horse_name or not horse_name.strip():
        warnings.append(f"entry[{index}]: 馬名が空")

    if horse_number <= 0:
        warnings.append(f"entry[{index}]: 馬番が不正 ({horse_number})")

    if not jockey or not jockey.strip():
        warnings.append(f"entry[{index}] {horse_name}: 騎手名が空")

    return warnings


def validate_race_entries(entries: list[dict], race_id: str = "",
                          min_entries: int = 2) -> tuple[bool, list[str]]:
    """Validate a list of entry dicts (executor format).

    Returns:
        (is_valid, warnings) — is_valid=False means data should NOT be served.
    """
    warnings = []

    if not entries:
        return False, [f"{race_id}: 出走馬が0頭"]

    if len(entries) < min_entries:
        warnings.append(f"{race_id}: 出走馬が{len(entries)}頭（通常2頭以上）")

    # Validate each entry
    empty_names = 0
    empty_jockeys = 0
    invalid_numbers = 0
    seen_numbers = set()
    duplicates = []

    for i, e in enumerate(entries):
        name = e.get("horse_name", "")
        num = e.get("horse_number", 0)
        jockey = e.get("jockey", "")

        if not name or not name.strip():
            empty_names += 1
        if num <= 0:
            invalid_numbers += 1
        if not jockey or not jockey.strip():
            empty_jockeys += 1
        if num in seen_numbers and num > 0:
            duplicates.append(num)
        seen_numbers.add(num)

    # Critical: more than 30% of entries have empty horse names → data is corrupt
    if empty_names > 0:
        ratio = empty_names / len(entries)
        warnings.append(f"{race_id}: 馬名空が{empty_names}/{len(entries)}頭")
        if ratio > 0.3:
            return False, warnings

    if invalid_numbers > 0:
        ratio = invalid_numbers / len(entries)
        warnings.append(f"{race_id}: 馬番不正が{invalid_numbers}/{len(entries)}頭")
        if ratio > 0.3:
            return False, warnings

    if empty_jockeys > len(entries) * 0.5:
        warnings.append(f"{race_id}: 騎手名空が{empty_jockeys}/{len(entries)}頭")

    if duplicates:
        warnings.append(f"{race_id}: 馬番重複 {duplicates}")

    return True, warnings


def validate_parallel_arrays(data: dict, race_id: str = "") -> tuple[bool, list[str]]:
    """Validate parallel arrays in prefetch format (horses, jockeys, etc. must be same length).

    Returns:
        (is_valid, warnings)
    """
    warnings = []
    horses = data.get("horses", [])

    if not horses:
        return False, [f"{race_id}: horses配列が空"]

    expected_len = len(horses)
    array_keys = ["horse_numbers", "jockeys", "posts", "trainers", "sex_ages", "weights"]

    for key in array_keys:
        arr = data.get(key, [])
        if arr and len(arr) != expected_len:
            warnings.append(
                f"{race_id}: {key}の長さ不一致 (horses={expected_len}, {key}={len(arr)})"
            )

    # Check for empty horse names
    empty_count = sum(1 for h in horses if not h or not str(h).strip())
    if empty_count > 0:
        warnings.append(f"{race_id}: 馬名空が{empty_count}/{expected_len}頭")
        if empty_count > expected_len * 0.3:
            return False, warnings

    # Check horse numbers validity
    nums = data.get("horse_numbers", [])
    if nums:
        invalid = sum(1 for n in nums if not isinstance(n, int) or n <= 0)
        if invalid > expected_len * 0.3:
            warnings.append(f"{race_id}: 馬番不正が{invalid}/{expected_len}頭")
            return False, warnings

    # If there are any length mismatches, it's invalid
    if any(w for w in warnings if "長さ不一致" in w):
        return False, warnings

    return True, warnings


def validate_race_metadata(race_name: str = "", venue: str = "",
                           distance: str = "", race_id: str = "") -> list[str]:
    """Validate race-level metadata. Returns warnings."""
    warnings = []

    if not race_name:
        warnings.append(f"{race_id}: レース名が空")

    if not venue:
        warnings.append(f"{race_id}: 会場名が空")

    if not distance:
        warnings.append(f"{race_id}: 距離が空")

    return warnings


def validate_html_has_race_data(soup, race_id: str = "") -> tuple[bool, str]:
    """Check that the HTML page actually contains race data (not an error page or different page).

    Returns:
        (is_valid, error_message)
    """
    if soup is None:
        return False, f"{race_id}: HTMLの取得に失敗"

    # Check for race table
    race_table = soup.select_one("table.RaceTable01, table.Shutuba_Table")
    horse_rows = soup.select("tr.HorseList")

    if not race_table and not horse_rows:
        # Check if it's an error page or no-data page
        body_text = soup.get_text(strip=True)[:500]
        if "レース情報がありません" in body_text or "存在しません" in body_text:
            return False, f"{race_id}: レースが存在しません"
        return False, f"{race_id}: 出馬表テーブルが見つかりません（HTML構造変更の可能性）"

    if not horse_rows:
        return False, f"{race_id}: HorseList行が0件（HTML構造変更の可能性）"

    return True, ""
