"""Tests for the FastAPI web layer.

Covers three layers:

1. **Smoke** — ``GET /health``, ``GET /``, and the static asset mount.
2. **Validation** — ``POST /api/analyze`` rejects bad URLs, bad ranges,
   and bad JSON bodies with the right status codes.
3. **Cache flow** — the read-through ordering Redis → Postgres → compute,
   with verification that we don't recompute on a hit and that a Postgres
   hit warms the Redis cache.

These tests deliberately avoid trivial assertions (e.g. "endpoint
returned 200") and instead pin down the **behavior** that matters for
the project: the lookup chain, which side effects fire on which path,
and the schema invariants the browser UI depends on.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src import main as main_module
from src.main import app

pytestmark = pytest.mark.unit

client = TestClient(app)

VALID_URL = "https://www.amazon.com/dp/B08N5WRWNW"
VALID_ASIN = "B08N5WRWNW"


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_home_serves_html_shell():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text.lower()
    # Sanity: the form-related markup must be present.
    assert "amazon" in body
    assert "<form" in body


def test_static_assets_served():
    """style.css and app.js must be reachable at /static/*."""
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")

    js = client.get("/static/app.js")
    assert js.status_code == 200
    # Some servers send application/javascript, others text/javascript.
    assert "javascript" in js.headers["content-type"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_analyze_rejects_non_amazon_url():
    response = client.post(
        "/api/analyze",
        json={"amazon_url": "https://www.google.com", "max_reviews": 100},
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_analyze_rejects_amazon_url_without_asin():
    response = client.post(
        "/api/analyze",
        json={"amazon_url": "https://www.amazon.com/bestsellers", "max_reviews": 100},
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_analyze_validates_max_reviews_bounds():
    """``max_reviews`` is clamped to 25–250 by the request schema."""
    too_low = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 10},
    )
    assert too_low.status_code == 422

    too_high = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 300},
    )
    assert too_high.status_code == 422


def test_analyze_rejects_missing_url():
    response = client.post("/api/analyze", json={"max_reviews": 100})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Response shape and invariants
# ---------------------------------------------------------------------------


def test_analyze_response_returns_json_content_type():
    response = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 100},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_analyze_returns_complete_payload_schema():
    """All fields the static UI reads must be present, with the right types."""
    response = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 100},
    )
    assert response.status_code == 200
    data = response.json()

    expected_keys = {
        "product_title",
        "product_image_url",
        "product_price",
        "amazon_rating",
        "total_review_count",
        "summary_text",
        "recommendation",
        "confidence_score",
        "confidence_explanation",
        "pros",
        "cons",
        "aspects",
        "negative_summary",
        "total_reviews_analyzed",
        "avg_rating",
    }
    assert expected_keys.issubset(data.keys())

    assert isinstance(data["pros"], list)
    assert isinstance(data["cons"], list)
    assert isinstance(data["aspects"], list)


def test_analyze_response_business_invariants():
    """Numeric fields must be internally consistent and clamped correctly.

    These are the invariants the UI depends on for rendering bars and the
    confidence meter — if they break, the page renders garbage.
    """
    response = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 100},
    )
    data = response.json()

    # Confidence is a probability-like value.
    assert 0.0 <= data["confidence_score"] <= 1.0

    # total_reviews_analyzed is bounded by the user's max_reviews.
    assert data["total_reviews_analyzed"] <= 100


def test_analyze_aspect_entries_have_valid_schema():
    response = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 100},
    )
    aspects = response.json()["aspects"]
    assert isinstance(aspects, list)

    for aspect in aspects:
        assert {"name", "sentiment", "mention_count"}.issubset(aspect.keys())
        assert isinstance(aspect["name"], str) and aspect["name"].strip()
        assert aspect["sentiment"] in {"positive", "negative", "mixed"}
        assert isinstance(aspect["mention_count"], int)
        assert aspect["mention_count"] >= 0


# ---------------------------------------------------------------------------
# Cache flow: Redis → Postgres → compute
# ---------------------------------------------------------------------------


def test_analyze_redis_hit_returns_cached_without_touching_postgres():
    """A Redis hit must short-circuit: no DB read, no DB write, no caching."""
    cached_payload = {"product_title": "From Redis", "marker": "redis"}

    with (
        patch.object(main_module, "get_cached", return_value=cached_payload) as mock_get_cached,
        patch.object(main_module, "get_analysis") as mock_get_analysis,
        patch.object(main_module, "save_analysis") as mock_save,
        patch.object(main_module, "set_cached") as mock_set_cached,
    ):
        response = client.post(
            "/api/analyze",
            json={"amazon_url": VALID_URL, "max_reviews": 100},
        )

    assert response.status_code == 200
    assert response.json() == cached_payload
    mock_get_cached.assert_called_once_with(VALID_ASIN, 100)
    mock_get_analysis.assert_not_called()
    mock_save.assert_not_called()
    mock_set_cached.assert_not_called()


def test_analyze_postgres_hit_warms_redis_cache():
    """When Redis misses but Postgres has it: return the row AND repopulate Redis."""
    db_payload = {"product_title": "From Postgres", "marker": "postgres"}

    with (
        patch.object(main_module, "get_cached", return_value=None),
        patch.object(main_module, "get_analysis", return_value=db_payload) as mock_get_db,
        patch.object(main_module, "save_analysis") as mock_save,
        patch.object(main_module, "set_cached") as mock_set_cached,
    ):
        response = client.post(
            "/api/analyze",
            json={"amazon_url": VALID_URL, "max_reviews": 200},
        )

    assert response.status_code == 200
    assert response.json() == db_payload
    mock_get_db.assert_called_once_with(VALID_ASIN, 200)
    # We do NOT re-save to Postgres on a Postgres hit.
    mock_save.assert_not_called()
    # We DO warm the Redis cache so the next request short-circuits.
    mock_set_cached.assert_called_once_with(VALID_ASIN, 200, db_payload)


def test_analyze_full_miss_persists_and_caches_fresh_payload():
    """Both layers miss: compute, save to Postgres, cache in Redis."""
    with (
        patch.object(main_module, "get_cached", return_value=None),
        patch.object(main_module, "get_analysis", return_value=None),
        patch.object(main_module, "save_analysis", return_value=True) as mock_save,
        patch.object(main_module, "set_cached", return_value=True) as mock_set_cached,
    ):
        response = client.post(
            "/api/analyze",
            json={"amazon_url": VALID_URL, "max_reviews": 100},
        )

    assert response.status_code == 200

    # Both side effects must fire exactly once with the same payload object.
    mock_save.assert_called_once()
    mock_set_cached.assert_called_once()

    save_asin, save_max, save_payload = mock_save.call_args.args
    cache_asin, cache_max, cache_payload = mock_set_cached.call_args.args
    assert save_asin == cache_asin == VALID_ASIN
    assert save_max == cache_max == 100
    assert save_payload is cache_payload  # exact same dict instance
    assert isinstance(save_payload["product_title"], str)
    assert save_payload["product_title"].strip()


def test_analyze_keeps_serving_when_storage_unavailable():
    """Both DB and cache returning falsy must not break the response."""
    with (
        patch.object(main_module, "get_cached", return_value=None),
        patch.object(main_module, "get_analysis", return_value=None),
        patch.object(main_module, "save_analysis", return_value=False),
        patch.object(main_module, "set_cached", return_value=False),
    ):
        response = client.post(
            "/api/analyze",
            json={"amazon_url": VALID_URL, "max_reviews": 100},
        )

    assert response.status_code == 200
    assert "product_title" in response.json()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


def test_lifespan_runs_init_db_on_startup():
    """Booting the app must attempt to initialize the database schema once."""
    with patch.object(main_module, "init_db") as mock_init, TestClient(app):
        pass  # entering and exiting the context manager runs lifespan
    mock_init.assert_called_once()
