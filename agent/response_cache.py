"""Response-level cache — serves identical race answers to multiple users.

File-backed JSON cache shared across all Gunicorn workers.
Cache flow:
  1. Pre-loop:  button press + race_id in history → return cached text ($0)
  2. Mid-loop:  Claude calls cacheable tool → check cache → skip remaining loop
  3. Post-loop: save final response for future users
  4. Warm-up:   daily_prefetch writes cache entries directly
"""

import json
import logging
import os
import time

try:
    import fcntl
except ImportError:
    fcntl = None  # Windows — file locking skipped

logger = logging.getLogger(__name__)

# Cache file location
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
_CACHE_FILE = os.path.join(_CACHE_DIR, 'response_cache.json')

# In-memory read cache (per-worker, refreshed from file)
_mem_cache: dict[str, dict[str, dict]] = {}
_mem_cache_mtime: float = 0

# Tool name → query type (for mid-loop detection)
TOOL_QUERY_MAP = {
    "get_predictions": "prediction",
    "get_race_flow": "race-flow",
    "get_jockey_analysis": "jockey",
    "get_bloodline_analysis": "bloodline",
    "get_recent_runs": "recent-runs",
    "get_odds_probability": "odds-probability",
    "get_stable_comments": "stable-comments",
    "get_engine_stats": "engine-stats",
}

# User message patterns → query type (for pre-loop + post-loop)
_MSG_PATTERNS = [
    ("予想して", "prediction"),
    ("予想を", "prediction"),
    ("予想出して", "prediction"),
    ("展開は", "race-flow"),
    ("展開予想", "race-flow"),
    ("展開を", "race-flow"),
    ("騎手の成績", "jockey"),
    ("騎手分析", "jockey"),
    ("騎手の", "jockey"),
    ("血統は", "bloodline"),
    ("血統分析", "bloodline"),
    ("血統的", "bloodline"),
    ("過去の成績", "recent-runs"),
    ("過去走", "recent-runs"),
    ("直近の", "recent-runs"),
    ("予測勝率", "odds-probability"),
    ("勝率を", "odds-probability"),
    ("勝率見", "odds-probability"),
    ("複勝率", "odds-probability"),
    ("厩舎コメント", "stable-comments"),
    ("調教師コメント", "stable-comments"),
    ("陣営コメント", "stable-comments"),
    ("調教師の", "stable-comments"),
    ("関係者情報", "stable-comments"),
    ("関係者の", "stable-comments"),
    ("的中率", "engine-stats"),
    ("エンジンの精度", "engine-stats"),
    ("どのくらい当たる", "engine-stats"),
    ("予想精度", "engine-stats"),
]


def _load_file() -> dict:
    """Load cache from JSON file."""
    global _mem_cache, _mem_cache_mtime
    try:
        if not os.path.exists(_CACHE_FILE):
            return {}
        mtime = os.path.getmtime(_CACHE_FILE)
        if mtime == _mem_cache_mtime and _mem_cache:
            return _mem_cache
        with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
            _mem_cache = json.load(f)
        _mem_cache_mtime = mtime
        return _mem_cache
    except Exception:
        return {}


def _save_file(data: dict):
    """Save cache to JSON file with file locking."""
    global _mem_cache, _mem_cache_mtime
    try:
        tmp = _CACHE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False)
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, _CACHE_FILE)
        _mem_cache = data
        _mem_cache_mtime = os.path.getmtime(_CACHE_FILE)
    except Exception as e:
        logger.warning(f"ResponseCache save error: {e}")


def detect_query_type(message: str) -> str | None:
    """Detect cacheable query type from user message."""
    for pattern, qtype in _MSG_PATTERNS:
        if pattern in message:
            return qtype
    return None


def find_race_id(history: list[dict]) -> str | None:
    """Find the most recent race_id from conversation history (tool_use blocks).

    Handles both Anthropic SDK ToolUseBlock objects and plain dict entries
    (created by template_router for synthetic history).
    """
    for msg in reversed(history):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            # Anthropic SDK ToolUseBlock objects
            if hasattr(block, "type") and block.type == "tool_use":
                inp = getattr(block, "input", None)
                if isinstance(inp, dict) and inp.get("race_id"):
                    return inp["race_id"]
            # Plain dict entries (from template_router synthetic history)
            elif isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input")
                if isinstance(inp, dict) and inp.get("race_id"):
                    return inp["race_id"]
    return None


def get(race_id: str, query_type: str) -> dict | None:
    """Get cached response. Returns {"text", "footer", "tools_used"} or None."""
    cache = _load_file()
    entry = cache.get(race_id, {}).get(query_type)
    if entry:
        logger.info(f"ResponseCache HIT: {race_id}:{query_type}")
    return entry


def save(race_id: str, query_type: str, text: str, footer: str, tools_used: list[str]):
    """Save response to cache."""
    cache = _load_file()
    cache.setdefault(race_id, {})[query_type] = {
        "text": text,
        "footer": footer,
        "tools_used": tools_used,
        "ts": time.time(),
    }
    _save_file(cache)
    logger.info(f"ResponseCache SAVE: {race_id}:{query_type}")


def clear_old(max_age_hours: int = 24):
    """Remove cache entries older than max_age_hours."""
    cache = _load_file()
    cutoff = time.time() - max_age_hours * 3600
    to_delete = []
    for race_id, queries in cache.items():
        for qtype, entry in list(queries.items()):
            if entry.get("ts", 0) < cutoff:
                del queries[qtype]
        if not queries:
            to_delete.append(race_id)
    for rid in to_delete:
        del cache[rid]
    if to_delete:
        _save_file(cache)
        logger.info(f"ResponseCache cleanup: removed {len(to_delete)} stale races")


def stats() -> dict:
    """Return cache statistics."""
    cache = _load_file()
    total = sum(len(v) for v in cache.values())
    return {"races": len(cache), "entries": total}
