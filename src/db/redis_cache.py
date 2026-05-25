"""Redis cache helpers for analysis and raw review payloads.

This module provides two read-through caches:
1. ``analysis:{asin}:{max_reviews}`` for final API payloads.
2. ``raw_reviews:{asin}:{max_reviews}`` for scraped raw review records.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import redis

from src.models.review import Review
from src.utils.config import get_settings
from src.utils.logger import logger

TTL_SECONDS = 86400  # 24 hours


def _key(asin: str, max_reviews: int) -> str:
    """Build Redis key for final analysis payload."""
    return f"analysis:{asin}:{max_reviews}"


def _raw_key(asin: str, max_reviews: int) -> str:
    """Build Redis key for raw review payload."""
    return f"raw_reviews:{asin}:{max_reviews}"


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
        logger.debug("Cached analysis: asin=%s max_reviews=%d", asin, max_reviews)
        return True
    except (redis.RedisError, TypeError, ValueError) as exc:
        logger.warning("set_cached failed for asin=%s: %s", asin, exc)
        return False
    finally:
        with contextlib.suppress(Exception):
            client.close()


def get_cached_raw_reviews(
    asin: str, max_reviews: int
) -> tuple[list[Review], dict[str, str]] | None:
    """Return cached raw reviews + meta for ``(asin, max_reviews)`` or ``None``."""
    if not asin:
        return None

    client = _client()
    if client is None:
        return None
    try:
        raw = client.get(_raw_key(asin, max_reviews))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning("Discarding bad raw cache entry for asin=%s: %s", asin, exc)
            client.delete(_raw_key(asin, max_reviews))
            return None

        reviews_raw = payload.get("reviews")
        meta_raw = payload.get("meta")
        if not isinstance(reviews_raw, list):
            return None

        # Rebuild typed ``Review`` objects from cached JSON dicts.
        reviews: list[Review] = []
        for item in reviews_raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            try:
                rating = float(str(item.get("rating", "3.0")))
            except ValueError:
                rating = 3.0
            reviews.append(
                Review(
                    text=text,
                    rating=rating,
                    date=str(item.get("date", "")),
                    helpful_votes=int(item.get("helpful_votes", 0) or 0),
                    verified_purchase=bool(item.get("verified_purchase", True)),
                    review_id=str(item.get("review_id", "")),
                )
            )
        if not reviews:
            return None

        # Keep metadata stringly-typed for stable JSON serialization.
        meta: dict[str, str] = {}
        if isinstance(meta_raw, dict):
            meta = {str(k): str(v) for k, v in meta_raw.items()}

        logger.debug("Redis raw cache hit: asin=%s max_reviews=%d", asin, max_reviews)
        return reviews[:max_reviews], meta
    except (redis.RedisError, TypeError, ValueError) as exc:
        logger.warning("get_cached_raw_reviews failed for asin=%s: %s", asin, exc)
        return None
    finally:
        with contextlib.suppress(Exception):
            client.close()


def set_cached_raw_reviews(
    asin: str,
    max_reviews: int,
    reviews: list[Review],
    meta: dict[str, str],
) -> bool:
    """Cache raw reviews + metadata for ``TTL_SECONDS``. Returns ``True`` on success."""
    if not asin or not isinstance(reviews, list):
        return False
    if not reviews:
        # Avoid caching empty scrape results so the next request can retry scraping.
        return False

    client = _client()
    if client is None:
        return False
    try:
        payload = {
            "asin": asin,
            "max_reviews": max_reviews,
            "reviews": [
                {
                    "text": review.text,
                    "rating": review.rating,
                    "date": review.date,
                    "helpful_votes": review.helpful_votes,
                    "verified_purchase": review.verified_purchase,
                    "review_id": review.review_id,
                }
                for review in reviews
            ],
            "meta": meta or {},
        }
        client.set(_raw_key(asin, max_reviews), json.dumps(payload), ex=TTL_SECONDS)
        logger.debug("Cached raw reviews in Redis: asin=%s max_reviews=%d", asin, max_reviews)
        return True
    except (redis.RedisError, TypeError, ValueError) as exc:
        logger.warning("set_cached_raw_reviews failed for asin=%s: %s", asin, exc)
        return False
    finally:
        with contextlib.suppress(Exception):
            client.close()
