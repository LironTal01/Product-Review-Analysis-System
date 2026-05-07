"""Tests for ``src.db.redis_cache``.

Mirrors the structure of ``test_postgres.py`` — verifies graceful
degradation when Redis is missing/unreachable, plus the happy-path flow
with a mocked ``redis.Redis`` client.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import redis

from src.db import redis_cache
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
# Key shape
# ---------------------------------------------------------------------------


def test_key_format():
    assert redis_cache._key("B08N5WRWNW", 100) == "analysis:B08N5WRWNW:100"


# ---------------------------------------------------------------------------
# Graceful degradation: REDIS_URL unset
# ---------------------------------------------------------------------------


def test_get_cached_returns_none_when_redis_url_empty(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    assert redis_cache.get_cached("B08N5WRWNW", 100) is None


def test_set_cached_returns_false_when_redis_url_empty(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    assert redis_cache.set_cached("B08N5WRWNW", 100, {"x": 1}) is False


# ---------------------------------------------------------------------------
# Graceful degradation: configured but unreachable
# ---------------------------------------------------------------------------


def test_client_returns_none_on_connection_error(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://nope:1/0")

    bad = MagicMock()
    bad.ping.side_effect = redis.ConnectionError("nope")

    with patch.object(redis.Redis, "from_url", return_value=bad):
        assert redis_cache._client() is None


def test_get_cached_returns_none_when_unreachable(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://nope:1/0")
    bad = MagicMock()
    bad.ping.side_effect = redis.ConnectionError("nope")

    with patch.object(redis.Redis, "from_url", return_value=bad):
        assert redis_cache.get_cached("B08N5WRWNW", 100) is None


def test_set_cached_returns_false_when_unreachable(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://nope:1/0")
    bad = MagicMock()
    bad.ping.side_effect = redis.ConnectionError("nope")

    with patch.object(redis.Redis, "from_url", return_value=bad):
        assert redis_cache.set_cached("B08N5WRWNW", 100, {"x": 1}) is False


# ---------------------------------------------------------------------------
# Input validation guards
# ---------------------------------------------------------------------------


def test_get_cached_rejects_empty_asin(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    assert redis_cache.get_cached("", 100) is None


def test_set_cached_rejects_empty_asin(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    assert redis_cache.set_cached("", 100, {"x": 1}) is False


def test_set_cached_rejects_non_dict_result(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    assert redis_cache.set_cached("B08N5WRWNW", 100, "not a dict") is False  # type: ignore[arg-type]


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


def test_get_cached_handles_redis_error(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://x")
    client = _fake_client()
    client.get.side_effect = redis.RedisError("boom")

    with patch.object(redis.Redis, "from_url", return_value=client):
        assert redis_cache.get_cached("B08N5WRWNW", 100) is None
