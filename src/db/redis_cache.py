"""Redis cache for analysis results.

Caches each ``AnalysisResult`` payload under a deterministic key derived
from ``(asin, max_reviews)`` for 24 hours. Used in front of the Postgres
read-through layer so that repeat requests for the same product never hit
either the DB or the LLM pipeline.

Graceful degradation: when ``settings.redis_url`` is empty or Redis is
unreachable, both ``get_cached`` and ``set_cached`` return a falsy value
and log a warning instead of raising. The web layer can therefore call
them unconditionally and still serve traffic without a cache.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import redis

from src.utils.config import get_settings
from src.utils.logger import logger

TTL_SECONDS = 86_400  # 24 hours


def _key(asin: str, max_reviews: int) -> str:
    return f"analysis:{asin}:{max_reviews}"


def _client() -> redis.Redis | None:
    """Build a Redis client or return ``None`` when not configured/reachable.

    ``decode_responses=True`` makes the client return Python strings instead
    of bytes, which keeps downstream JSON parsing trivial.
    """
    settings = get_settings()
    if not settings.redis_url:
        return None
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        return client
    except (redis.ConnectionError, redis.TimeoutError, OSError) as exc:
        logger.warning("Redis unavailable: %s", exc)
        return None


def get_cached(asin: str, max_reviews: int) -> dict[str, Any] | None:
    """Return the cached analysis dict for ``(asin, max_reviews)`` or ``None``."""
    if not asin:
        return None

    client = _client()
    if client is None:
        return None
    try:
        raw = client.get(_key(asin, max_reviews))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            # Stale or corrupt entry — drop it so the next request recomputes.
            logger.warning("Discarding bad cache entry for asin=%s: %s", asin, exc)
            client.delete(_key(asin, max_reviews))
            return None
    except redis.RedisError as exc:
        logger.warning("get_cached failed for asin=%s: %s", asin, exc)
        return None
    finally:
        with contextlib.suppress(Exception):
            client.close()


def set_cached(asin: str, max_reviews: int, result: dict[str, Any]) -> bool:
    """Cache ``result`` for ``TTL_SECONDS``. Returns ``True`` on success."""
    if not asin or not isinstance(result, dict):
        return False

    client = _client()
    if client is None:
        return False
    try:
        client.set(_key(asin, max_reviews), json.dumps(result), ex=TTL_SECONDS)
        logger.info("Cached analysis: asin=%s max_reviews=%d", asin, max_reviews)
        return True
    except (redis.RedisError, TypeError, ValueError) as exc:
        logger.warning("set_cached failed for asin=%s: %s", asin, exc)
        return False
    finally:
        with contextlib.suppress(Exception):
            client.close()
