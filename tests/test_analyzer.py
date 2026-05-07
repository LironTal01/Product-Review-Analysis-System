"""Integration tests for the core analysis pipeline.

The OpenAI client is fully mocked so no network calls are made.
Tests verify that analyze_product chains every step correctly and
that _assemble_result maps LLM output into a valid AnalysisResult.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.core.analyzer import _assemble_result, analyze_product
from src.models.analysis import AnalysisResult, AspectInfo, StatsResult
from src.utils.url_parser import AmazonURLError

pytestmark = pytest.mark.unit

# ── mock helpers ─────────────────────────────────────────────────────────

_FAKE_LLM_RESPONSE = {
    "summary_text": "Most reviewers praise the sound quality and comfort.",
    "pros": ["Great sound", "Comfortable fit", "Long battery"],
    "cons": ["Bluetooth drops occasionally", "Touch controls too sensitive"],
    "aspects": [
        {"name": "sound quality", "sentiment": "positive", "mention_count": 40},
        {"name": "comfort", "sentiment": "positive", "mention_count": 30},
        {"name": "bluetooth", "sentiment": "negative", "mention_count": 12},
    ],
    "recommendation": "Recommended for casual listeners.",
    "confidence_explanation": "High volume of consistent positive reviews.",
    "negative_summary": "Low-rated reviews focus on Bluetooth pairing issues.",
}


def _mock_openai_client() -> MagicMock:
    """Build a mock OpenAI client that returns fake embeddings and LLM JSON."""
    client = MagicMock()

    # Embeddings: return random vectors for any input
    def fake_embed(*args, **kwargs):
        batch = kwargs.get("input")
        if batch is None and len(args) >= 2:
            batch = args[1]
        if batch is None:
            batch = []
        data = [MagicMock(embedding=np.random.default_rng(42).random(256).tolist()) for _ in batch]
        resp = MagicMock()
        resp.data = data
        return resp

    client.embeddings.create = MagicMock(side_effect=fake_embed)

    # Responses API: return the canned LLM JSON
    llm_response = MagicMock()
    llm_response.output_text = json.dumps(_FAKE_LLM_RESPONSE)
    client.responses.create.return_value = llm_response

    return client


# ── analyze_product end-to-end ───────────────────────────────────────────


class TestAnalyzeProductEndToEnd:
    """Full pipeline with mocked OpenAI — no network, no real API key."""

    @patch("src.core.analyzer.OpenAI")
    def test_returns_complete_analysis_result(self, mock_openai_cls):
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert isinstance(result, AnalysisResult)

    @patch("src.core.analyzer.OpenAI")
    def test_summary_text_is_populated(self, mock_openai_cls):
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert len(result.summary_text) > 0

    @patch("src.core.analyzer.OpenAI")
    def test_confidence_score_in_valid_range(self, mock_openai_cls):
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert 0.0 <= result.confidence_score <= 1.0

    @patch("src.core.analyzer.OpenAI")
    def test_reviews_analyzed_is_positive(self, mock_openai_cls):
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert result.total_reviews_analyzed >= 1

    @patch("src.core.analyzer.OpenAI")
    def test_pros_or_cons_present(self, mock_openai_cls):
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert len(result.pros) > 0 or len(result.cons) > 0

    @patch("src.core.analyzer.OpenAI")
    def test_aspects_are_typed_correctly(self, mock_openai_cls):
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert all(isinstance(a, AspectInfo) for a in result.aspects)

    @patch("src.core.analyzer.OpenAI")
    def test_product_metadata_from_mock_catalog(self, mock_openai_cls):
        """Product title should come from PRODUCT_META, not be generic."""
        mock_openai_cls.return_value = _mock_openai_client()

        result = analyze_product("https://www.amazon.com/dp/B08N5WRWNW", 100)

        assert "ProSound" in result.product_title


# ── invalid URL ──────────────────────────────────────────────────────────


class TestAnalyzeProductInvalidUrl:
    """Bad URLs should raise before any pipeline work starts."""

    def test_non_amazon_url_raises(self):
        with pytest.raises(AmazonURLError):
            analyze_product("https://google.com", 100)

    def test_empty_url_raises(self):
        with pytest.raises(AmazonURLError):
            analyze_product("", 100)


# ── _assemble_result unit-level ──────────────────────────────────────────


class TestAssembleResult:
    """Verify _assemble_result maps fields correctly with fallbacks."""

    def test_uses_llm_recommendation_when_present(self):
        stats = StatsResult(
            avg_rating=4.2,
            total_reviews=50,
            rating_distribution={5: 30, 4: 10, 3: 5, 2: 3, 1: 2},
            negative_count=10,
        )

        result = _assemble_result(_FAKE_LLM_RESPONSE, stats, 0.85, "B08N5WRWNW")

        assert result.recommendation == "Recommended for casual listeners."

    def test_fallback_recommendation_when_llm_empty(self):
        stats = StatsResult(
            avg_rating=2.5,
            total_reviews=10,
            rating_distribution={5: 1, 4: 1, 3: 2, 2: 3, 1: 3},
            negative_count=8,
        )
        llm_out = {**_FAKE_LLM_RESPONSE, "recommendation": ""}

        result = _assemble_result(llm_out, stats, 0.4, "B08N5WRWNW")

        assert "alternatives" in result.recommendation.lower()

    def test_aspects_converted_to_aspect_info(self):
        stats = StatsResult(
            avg_rating=4.0,
            total_reviews=20,
            rating_distribution={5: 10, 4: 5, 3: 3, 2: 1, 1: 1},
            negative_count=5,
        )

        result = _assemble_result(_FAKE_LLM_RESPONSE, stats, 0.8, "B08N5WRWNW")

        assert len(result.aspects) == 3
        assert all(isinstance(a, AspectInfo) for a in result.aspects)
