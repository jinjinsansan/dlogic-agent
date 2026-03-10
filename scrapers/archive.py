"""Parse TypeScript archive files from the Dlogic frontend."""

import os
import re
import json
from dataclasses import dataclass, field

# Path to the frontend archive directory (configurable via env var)
ARCHIVE_DIR = os.environ.get(
    "ARCHIVE_DIR",
    "E:/dev/Cusor/front/d-logic-ai-frontend/src/data/archive",
)
LOCAL_ARCHIVE_DIR = os.path.join(ARCHIVE_DIR, "local")


@dataclass
class ArchiveRace:
    race_id: str
    race_date: str
    venue: str
    race_number: int
    race_name: str
    distance: str
    track_condition: str
    horses: list[str] = field(default_factory=list)
    jockeys: list[str] = field(default_factory=list)
    posts: list[int] = field(default_factory=list)
    horse_numbers: list[int] = field(default_factory=list)
    sex_ages: list[str] = field(default_factory=list)
    weights: list = field(default_factory=list)
    trainers: list[str] = field(default_factory=list)
    odds: list[float] = field(default_factory=list)
    popularities: list[int] = field(default_factory=list)
    predictions: dict = field(default_factory=dict)


def _parse_ts_array(text: str) -> list:
    """Parse a TypeScript array literal into a Python list."""
    # Remove comments
    text = re.sub(r'//.*$', '', text, flags=re.MULTILINE)
    # Replace single quotes with double quotes for JSON compat
    text = text.replace("'", '"')
    # Remove trailing commas before ] or }
    text = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


def _parse_ts_file(filepath: str) -> list[ArchiveRace]:
    """Parse a single TS archive file and return list of ArchiveRace."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract the array content between "ArchiveRace[] = [" and the final "];"
    match = re.search(r'(?:ArchiveRace\[\]\s*=\s*|export\s+const\s+races\s*[=:]\s*(?:ArchiveRace\[\]\s*=\s*)?)\[(.+)\];?\s*$',
                       content, re.DOTALL)
    if not match:
        return []

    array_body = match.group(1)

    # Split into individual race objects by finding top-level { }
    races = []
    depth = 0
    start = None
    for i, ch in enumerate(array_body):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                race_text = array_body[start:i+1]
                race = _parse_race_object(race_text)
                if race:
                    races.append(race)
                start = None

    return races


def _parse_race_object(text: str) -> ArchiveRace | None:
    """Parse a single race object from TS text."""
    def extract_field(name: str, default="") -> str:
        m = re.search(rf"{name}:\s*'([^']*)'", text)
        if not m:
            m = re.search(rf'{name}:\s*"([^"]*)"', text)
        return m.group(1) if m else default

    def extract_int(name: str, default=0) -> int:
        m = re.search(rf"{name}:\s*(\d+)", text)
        return int(m.group(1)) if m else default

    def extract_bool(name: str, default=False) -> bool:
        m = re.search(rf"{name}:\s*(true|false)", text)
        return m.group(1) == "true" if m else default

    def extract_array(name: str) -> list:
        m = re.search(rf"{name}:\s*\[([^\]]*)\]", text, re.DOTALL)
        if not m:
            return []
        return _parse_ts_array("[" + m.group(1) + "]")

    def extract_predictions() -> dict:
        m = re.search(r"predictions:\s*\{([^}]+)\}", text, re.DOTALL)
        if not m:
            return {}
        pred_text = m.group(1)
        result = {}
        for engine in ["dlogic", "ilogic", "viewlogic", "metalogic"]:
            em = re.search(rf"{engine}:\s*\[([^\]]*)\]", pred_text)
            if em:
                nums = _parse_ts_array("[" + em.group(1) + "]")
                result[engine] = nums
        return result

    race_id = extract_field("race_id")
    if not race_id:
        return None

    return ArchiveRace(
        race_id=race_id,
        race_date=extract_field("race_date"),
        venue=extract_field("venue"),
        race_number=extract_int("race_number"),
        race_name=extract_field("race_name"),
        distance=extract_field("distance"),
        track_condition=extract_field("track_condition"),
        horses=extract_array("horses"),
        jockeys=extract_array("jockeys"),
        posts=extract_array("posts"),
        horse_numbers=extract_array("horse_numbers"),
        sex_ages=extract_array("sex_ages"),
        weights=extract_array("weights"),
        trainers=extract_array("trainers"),
        odds=extract_array("odds"),
        popularities=extract_array("popularities"),
        predictions=extract_predictions(),
    )


def find_archive_races(date_str: str, venue: str = "", is_local: bool = False) -> list[ArchiveRace]:
    """
    Find races from TS archive files.

    Args:
        date_str: Date in YYYYMMDD format.
        venue: Optional venue name filter.
        is_local: If True, search in local/ (NAR) directory.

    Returns:
        List of ArchiveRace, or empty list if no archive found.
    """
    base_dir = LOCAL_ARCHIVE_DIR if is_local else ARCHIVE_DIR
    races = []

    # Find matching files
    pattern = f"races-{date_str}"
    if venue:
        pattern += f"-{venue}"

    if not os.path.isdir(base_dir):
        return races

    for filename in os.listdir(base_dir):
        if filename.startswith(f"races-{date_str}") and filename.endswith(".ts"):
            if venue and venue not in filename:
                continue
            filepath = os.path.join(base_dir, filename)
            file_races = _parse_ts_file(filepath)
            races.extend(file_races)

    return races


def find_archive_race_by_id(race_id: str) -> ArchiveRace | None:
    """
    Find a specific race by race_id from archive files.
    race_id format: "20260308-中山-11" or similar.
    """
    parts = race_id.split("-")
    if len(parts) < 2:
        return None

    date_str = parts[0]
    venue = parts[1] if len(parts) > 1 else ""

    # Try JRA first, then local
    for is_local in [False, True]:
        races = find_archive_races(date_str, venue, is_local=is_local)
        for race in races:
            if race.race_id == race_id:
                return race

    return None


def get_available_dates(is_local: bool = False) -> list[str]:
    """Get list of available archive dates."""
    base_dir = LOCAL_ARCHIVE_DIR if is_local else ARCHIVE_DIR
    dates = set()

    if not os.path.exists(base_dir):
        return []

    for filename in os.listdir(base_dir):
        m = re.match(r"races-(\d{8})", filename)
        if m:
            dates.add(m.group(1))

    return sorted(dates, reverse=True)
