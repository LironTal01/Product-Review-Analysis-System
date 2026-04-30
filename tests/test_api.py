"""Smoke tests for the FastAPI app.

These tests target the three public surfaces of the web layer:
- ``GET /health`` (liveness probe)
- ``GET /`` (serves the static single-page UI shell)
- ``POST /api/analyze`` (JSON in / JSON out, with URL validation)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app

pytestmark = pytest.mark.unit

client = TestClient(app)


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


def test_analyze_returns_complete_payload_for_valid_url():
    response = client.post(
        "/api/analyze",
        json={
            "amazon_url": "https://www.amazon.com/dp/B08N5WRWNW",
            "max_reviews": 100,
        },
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
        "rating_distribution",
        "negative_summary",
        "total_reviews_analyzed",
        "avg_rating",
    }
    assert expected_keys.issubset(data.keys())

    assert isinstance(data["pros"], list)
    assert isinstance(data["cons"], list)
    assert isinstance(data["aspects"], list)
    assert 0.0 <= data["confidence_score"] <= 1.0

    # Aspect entries must have the schema the UI consumes.
    for aspect in data["aspects"]:
        assert {"name", "sentiment", "mention_count"}.issubset(aspect.keys())
        assert aspect["sentiment"] in {"positive", "negative", "mixed"}


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
    """``max_reviews`` is clamped to 100–500 by the request schema."""
    too_low = client.post(
        "/api/analyze",
        json={"amazon_url": "https://www.amazon.com/dp/B08N5WRWNW", "max_reviews": 50},
    )
    assert too_low.status_code == 422

    too_high = client.post(
        "/api/analyze",
        json={"amazon_url": "https://www.amazon.com/dp/B08N5WRWNW", "max_reviews": 1000},
    )
    assert too_high.status_code == 422


def test_analyze_rejects_missing_url():
    response = client.post("/api/analyze", json={"max_reviews": 100})
    assert response.status_code == 422
