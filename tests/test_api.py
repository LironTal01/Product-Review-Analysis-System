"""Tests for the FastAPI web layer.

Covers three layers:

1. **Smoke** — ``GET /health``, ``GET /``, and the static asset mount.
2. **Validation** — ``POST /api/analyze`` rejects bad URLs, bad ranges,
   and bad JSON bodies with the right status codes.
3. **Cache flow** — the read-through ordering Redis → compute,
   with verification that we don't recompute on a hit.

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
from src.models.analysis import AnalysisResult

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


@pytest.mark.parametrize(
    "amazon_url",
    [
        "https://www.google.com",
        "https://www.amazon.com/bestsellers",
    ],
    ids=["non_amazon_host", "amazon_without_asin"],
)
def test_analyze_rejects_bad_urls(amazon_url: str):
    response = client.post(
        "/api/analyze",
        json={"amazon_url": amazon_url, "max_reviews": 100},
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


def test_analyze_response_schema_and_invariants():
    """Pin down response schema and UI-critical invariants in one place."""
    response = client.post(
        "/api/analyze",
        json={"amazon_url": VALID_URL, "max_reviews": 100},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
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

    # Confidence is a probability-like value.
    assert 0.0 <= data["confidence_score"] <= 1.0
    # total_reviews_analyzed is bounded by the user's max_reviews.
    assert data["total_reviews_analyzed"] <= 100

    for aspect in data["aspects"]:
        assert {"name", "sentiment", "mention_count"}.issubset(aspect.keys())
        assert isinstance(aspect["name"], str) and aspect["name"].strip()
        assert aspect["sentiment"] in {"positive", "negative", "mixed"}
        assert isinstance(aspect["mention_count"], int)
        assert aspect["mention_count"] >= 0


# ---------------------------------------------------------------------------
# Cache flow: Redis → compute
# ---------------------------------------------------------------------------


def test_analyze_redis_hit_returns_cached_without_touching_pipeline():
    """A Redis hit must short-circuit: no recompute and no cache write."""
    cached_payload = {"product_title": "From Redis", "marker": "redis"}

    with (
        patch.object(main_module, "get_cached", return_value=cached_payload) as mock_get_cached,
        patch.object(main_module, "analyze_product") as mock_analyze,
        patch.object(main_module, "set_cached") as mock_set_cached,
    ):
        response = client.post(
            "/api/analyze",
            json={"amazon_url": VALID_URL, "max_reviews": 100},
        )

    assert response.status_code == 200
    assert response.json() == cached_payload
    mock_get_cached.assert_called_once_with(VALID_ASIN, 100)
    mock_analyze.assert_not_called()
    mock_set_cached.assert_not_called()


def test_analyze_full_miss_computes_and_caches_fresh_payload():
    """Cache miss: compute and cache in Redis."""
    fake_result = AnalysisResult(
        product_title="Fresh compute",
        confidence_score=0.5,
        total_reviews_analyzed=10,
        avg_rating=4.2,
    )
    with (
        patch.object(main_module, "get_cached", return_value=None),
        patch.object(main_module, "analyze_product", return_value=fake_result) as mock_analyze,
        patch.object(main_module, "set_cached", return_value=True) as mock_set_cached,
    ):
        response = client.post(
            "/api/analyze",
            json={"amazon_url": VALID_URL, "max_reviews": 100},
        )

    assert response.status_code == 200

    mock_analyze.assert_called_once()
    mock_set_cached.assert_called_once()

    cache_asin, cache_max, cache_payload = mock_set_cached.call_args.args
    assert cache_asin == VALID_ASIN
    assert cache_max == 100
    assert isinstance(cache_payload["product_title"], str)
    assert cache_payload["product_title"].strip()


def test_analyze_keeps_serving_when_storage_unavailable():
    """Cache returning falsy must not break the response."""
    fake_result = AnalysisResult(product_title="Still works")
    with (
        patch.object(main_module, "get_cached", return_value=None),
        patch.object(main_module, "analyze_product", return_value=fake_result),
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


def test_lifespan_runs_without_errors():
    """Booting the app must not raise (no DB init expected)."""
    with TestClient(app):
        pass  # entering and exiting the context manager runs lifespan
