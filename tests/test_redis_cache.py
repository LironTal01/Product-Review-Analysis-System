"""Tests for ``src.db.redis_cache``.
degradation when Redis is missing/unreachable, plus the happy-path flow
with a mocked ``redis.Redis`` client.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import redis

from src.db import redis_cache
from src.models.review import Review
from src.utils.config import get_settings

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """``get_settings`` is ``lru_cache``-ed — reset between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake_client() -> MagicMock:
    """Return a MagicMock shaped like a ``redis.Redis`` client."""
    client = MagicMock()
    client.ping.return_value = True
    return client


# ---------------------------------------------------------------------------
# Graceful degradation: REDIS_URL unset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("func", "args", "expected"),
    [
        (redis_cache.get_cached, ("B08N5WRWNW", 100), None),
        (redis_cache.set_cached, ("B08N5WRWNW", 100, {"x": 1}), False),
    ],
    ids=["get_cached", "set_cached"],
)
def test_cache_ops_noop_when_redis_url_empty(monkeypatch, func, args, expected):
    monkeypatch.setenv("REDIS_URL", "")
    assert func(*args) == expected


# ---------------------------------------------------------------------------
# Graceful degradation: configured but unreachable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("func", "args", "expected"),
    [
        (redis_cache.get_cached, ("B08N5WRWNW", 100), None),
        (redis_cache.set_cached, ("B08N5WRWNW", 100, {"x": 1}), False),
    ],
    ids=["get_cached", "set_cached"],
)
def test_cache_ops_noop_when_unreachable(monkeypatch, func, args, expected):
    monkeypatch.setenv("REDIS_URL", "redis://nope:1/0")
    bad = MagicMock()
    bad.ping.side_effect = redis.ConnectionError("nope")
    with patch.object(redis.Redis, "from_url", return_value=bad):
        assert func(*args) == expected


# ---------------------------------------------------------------------------
# Input validation guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("func", "args", "expected"),
    [
        (redis_cache.get_cached, ("", 100), None),
        (redis_cache.set_cached, ("", 100, {"x": 1}), False),
        (redis_cache.set_cached, ("B08N5WRWNW", 100, "not a dict"), False),  # type: ignore[arg-type]
    ],
    ids=["get_cached_empty_asin", "set_cached_empty_asin", "set_cached_non_dict"],
)
def test_cache_input_validation_guards(monkeypatch, func, args, expected):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    assert func(*args) == expected


# ---------------------------------------------------------------------------
# Happy path with mocked client
# ---------------------------------------------------------------------------


def test_set_cached_writes_json_with_ttl(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    client = _fake_client()
    payload = {"product_title": "Sample", "pros": ["a"]}

    with patch.object(redis.Redis, "from_url", return_value=client):
        assert redis_cache.set_cached("B08N5WRWNW", 250, payload) is True

    client.set.assert_called_once()
    args, kwargs = client.set.call_args
    key, value = args
    assert key == "analysis:B08N5WRWNW:250"
    assert json.loads(value) == payload
    assert kwargs.get("ex") == redis_cache.TTL_SECONDS


def test_get_cached_returns_dict_on_hit(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    expected = {"product_title": "Sample", "pros": ["a"]}
    client = _fake_client()
    client.get.return_value = json.dumps(expected)

    with patch.object(redis.Redis, "from_url", return_value=client):
        result = redis_cache.get_cached("B08N5WRWNW", 100)

    assert result == expected
    client.get.assert_called_once_with("analysis:B08N5WRWNW:100")


def test_get_cached_returns_none_on_miss(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    client = _fake_client()
    client.get.return_value = None

    with patch.object(redis.Redis, "from_url", return_value=client):
        assert redis_cache.get_cached("B08N5WRWNW", 100) is None


def test_get_cached_drops_corrupt_entry(monkeypatch):
    """Bad JSON in Redis should be deleted so the next request recomputes."""
    monkeypatch.setenv("REDIS_URL", "redis://x")
    client = _fake_client()
    client.get.return_value = "{not valid json"

    with patch.object(redis.Redis, "from_url", return_value=client):
        result = redis_cache.get_cached("B08N5WRWNW", 100)

    assert result is None
    client.delete.assert_called_once_with("analysis:B08N5WRWNW:100")


def test_set_cached_raw_reviews_writes_json_with_ttl(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    client = _fake_client()
    reviews = [
        Review(
            text="Great mouse",
            rating=5.0,
            date="2026-01-01",
            helpful_votes=2,
            verified_purchase=True,
        ),
        Review(
            text="Battery is okay",
            rating=3.0,
            date="2026-01-02",
            helpful_votes=1,
            verified_purchase=True,
        ),
    ]

    with patch.object(redis.Redis, "from_url", return_value=client):
        assert (
            redis_cache.set_cached_raw_reviews(
                "B08N5WRWNW", 50, reviews, {"total_review_count": "123"}
            )
            is True
        )

    client.set.assert_called_once()
    args, kwargs = client.set.call_args
    key, value = args
    assert key == "raw_reviews:B08N5WRWNW:50"
    payload = json.loads(value)
    assert isinstance(payload.get("reviews"), list)
    assert len(payload["reviews"]) == 2
    assert payload["meta"] == {"total_review_count": "123"}
    assert kwargs.get("ex") == redis_cache.TTL_SECONDS


def test_get_cached_raw_reviews_returns_typed_reviews(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    client = _fake_client()
    client.get.return_value = json.dumps(
        {
            "reviews": [
                {
                    "text": "Works great",
                    "rating": 4.0,
                    "date": "2026-01-01",
                    "helpful_votes": 3,
                    "verified_purchase": True,
                }
            ],
            "meta": {"total_review_count": "200"},
        }
    )

    with patch.object(redis.Redis, "from_url", return_value=client):
        result = redis_cache.get_cached_raw_reviews("B08N5WRWNW", 50)

    assert result is not None
    reviews, meta = result
    assert len(reviews) == 1
    assert isinstance(reviews[0], Review)
    assert meta == {"total_review_count": "200"}
