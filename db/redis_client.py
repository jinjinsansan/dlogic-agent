"""Redis client singleton for shared state."""

import logging
import os

try:
    import redis
except Exception:  # pragma: no cover - optional dependency
    redis = None

logger = logging.getLogger(__name__)

_client = None


def get_redis():
    """Get or create Redis client. Returns None if unavailable."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    if redis is None:
        logger.warning("redis package not installed")
        return None

    try:
        _client = redis.Redis.from_url(url, decode_responses=True)
        _client.ping()
        logger.info("Redis client initialized")
        return _client
    except Exception:
        logger.exception("Failed to initialize Redis client")
        _client = None
        return None
