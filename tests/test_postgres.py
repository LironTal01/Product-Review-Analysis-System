"""Tests for ``src.db.postgres``.

The persistence layer is deliberately tolerant of a missing or unreachable
Postgres instance — these tests verify both that contract and the SQL flow
when a connection is available (using a mocked ``psycopg.connect``).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from src.db import postgres
from src.utils.config import get_settings

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """``get_settings`` is ``lru_cache``-ed — reset between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_fake_connection(fetch_result=None) -> MagicMock:
    """Build a MagicMock shaped like a psycopg connection used by our code.

    Supports the patterns we rely on:
        with conn:
            with conn.cursor() as cur:
                cur.execute(...)
                cur.fetchone()
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = fetch_result
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


# ---------------------------------------------------------------------------
# Graceful degradation: no DATABASE_URL configured
# ---------------------------------------------------------------------------


def test_init_db_returns_false_when_database_url_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    assert postgres.init_db() is False


def test_save_analysis_returns_false_when_database_url_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    assert postgres.save_analysis("B08N5WRWNW", 100, {"x": 1}) is False


def test_get_analysis_returns_none_when_database_url_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    assert postgres.get_analysis("B08N5WRWNW", 100) is None


# ---------------------------------------------------------------------------
# Graceful degradation: configured but unreachable
# ---------------------------------------------------------------------------


def test_connect_returns_none_on_operational_error(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@127.0.0.1:1/none")

    with patch.object(psycopg, "connect", side_effect=psycopg.OperationalError("boom")):
        assert postgres._connect() is None


def test_save_analysis_returns_false_when_unreachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@127.0.0.1:1/none")
    with patch.object(psycopg, "connect", side_effect=psycopg.OperationalError("boom")):
        assert postgres.save_analysis("B08N5WRWNW", 100, {"x": 1}) is False


# ---------------------------------------------------------------------------
# Input validation guards
# ---------------------------------------------------------------------------


def test_save_analysis_rejects_empty_asin(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert postgres.save_analysis("", 100, {"x": 1}) is False


def test_save_analysis_rejects_non_dict_result(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert postgres.save_analysis("B08N5WRWNW", 100, "not a dict") is False  # type: ignore[arg-type]


def test_get_analysis_rejects_empty_asin(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert postgres.get_analysis("", 100) is None


# ---------------------------------------------------------------------------
# SQL flow with mocked connection
# ---------------------------------------------------------------------------


def test_init_db_executes_create_table_and_index(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    fake_conn = _make_fake_connection()

    with patch.object(psycopg, "connect", return_value=fake_conn):
        assert postgres.init_db() is True

    cursor = fake_conn.cursor.return_value
    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("CREATE TABLE" in sql for sql in executed)
    assert any("CREATE INDEX" in sql for sql in executed)
    fake_conn.close.assert_called_once()


def test_save_analysis_inserts_json(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    fake_conn = _make_fake_connection()

    payload = {"product_title": "Sample", "pros": ["a", "b"]}

    with patch.object(psycopg, "connect", return_value=fake_conn):
        assert postgres.save_analysis("B08N5WRWNW", 250, payload) is True

    cursor = fake_conn.cursor.return_value
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO analyses" in sql
    asin, max_reviews, result_json = params
    assert asin == "B08N5WRWNW"
    assert max_reviews == 250
    # Stored as a JSON string for JSONB; the dict round-trips losslessly.
    assert json.loads(result_json) == payload


def test_get_analysis_returns_dict_from_jsonb(monkeypatch):
    """psycopg 3 typically returns ``JSONB`` already decoded as a dict."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    expected = {"product_title": "Sample", "pros": ["a"]}
    fake_conn = _make_fake_connection(fetch_result=(expected,))

    with patch.object(psycopg, "connect", return_value=fake_conn):
        result = postgres.get_analysis("B08N5WRWNW", 100)

    assert result == expected
    cursor = fake_conn.cursor.return_value
    sql, params = cursor.execute.call_args.args
    assert "SELECT result_json" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params == ("B08N5WRWNW", 100)


def test_get_analysis_decodes_string_payload(monkeypatch):
    """If a driver returns the JSON column as a string, we still decode it."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    expected = {"product_title": "Sample"}
    fake_conn = _make_fake_connection(fetch_result=(json.dumps(expected),))

    with patch.object(psycopg, "connect", return_value=fake_conn):
        result = postgres.get_analysis("B08N5WRWNW", 100)

    assert result == expected


def test_get_analysis_returns_none_on_empty_result(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    fake_conn = _make_fake_connection(fetch_result=None)

    with patch.object(psycopg, "connect", return_value=fake_conn):
        assert postgres.get_analysis("B08N5WRWNW", 100) is None
