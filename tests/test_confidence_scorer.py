"""Unit tests for confidence_scorer — Official TDD #1.

Red-green-refactor: tests were written before the implementation.
Covers edge cases (empty list, single review), monotonicity with review
count, score ceiling, and the effect of review diversity on the score.

A stub returning 0.0 passes the empty-list and ceiling checks but fails
monotonicity and diversity — proving the tests drive a real implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from src.analysis.confidence_scorer import calculate_confidence

pytestmark = pytest.mark.unit

NOW = datetime(2026, 3, 24, 12, 0, 0)


@dataclass
class MockReview:
    """Small review object used only for tests."""

    text: str | None
    rating: float | None
    date: datetime
    helpful_votes: int = 0
    verified_purchase: bool = True


def _make_reviews(*, n: int, rating: float, text: str, days_step: int) -> list[MockReview]:
    """Create repeated reviews with predictable dates."""
    base = NOW - timedelta(days=days_step * (n - 1))
    return [MockReview(text, rating, base + timedelta(days=i * days_step)) for i in range(n)]


class TestCalculateConfidence:
    """Tests for calculate_confidence covering score range, monotonicity, and diversity."""

    @pytest.mark.parametrize(
        "reviews, expected",
        [
            pytest.param([], 0.0, id="empty_list_returns_zero"),
        ],
    )
    def test_confidence_exact_expected_value(self, reviews, expected):
        """Exact expected values for deterministic edge cases."""
        assert calculate_confidence(reviews) == expected

    def test_single_review_returns_low_but_nonzero_score(self):
        """One review is not enough for high confidence, but should not return zero."""
        reviews = [MockReview("A decent review with enough content.", 4.0, NOW)]
        score = calculate_confidence(reviews)
        assert 0.0 < score < 0.5

    def test_confidence_increases_with_review_count(self):
        """More reviews always produce higher confidence (monotonic across three levels)."""
        text = "This review has enough words to look real and consistent."
        few = _make_reviews(n=5, rating=4.0, text=text, days_step=7)
        medium = _make_reviews(n=25, rating=4.0, text=text, days_step=4)
        many = _make_reviews(n=100, rating=4.0, text=text, days_step=2)

        score_few = calculate_confidence(few)
        score_medium = calculate_confidence(medium)
        score_many = calculate_confidence(many)

        # All three levels must be strictly ordered.
        assert score_few < score_medium < score_many

    def test_confidence_never_exceeds_one(self):
        """Score is capped at 1.0 regardless of review count."""
        reviews = _make_reviews(
            n=500,
            rating=4.0,
            text="Long detailed review with many words.",
            days_step=1,
        )
        assert calculate_confidence(reviews) <= 1.0

    def test_diverse_long_reviews_have_higher_confidence(self):
        """Diverse ratings, long texts, and spread dates produce higher confidence than short clustered reviews."""
        high_texts = [
            "Excellent product with great build quality and fast delivery.",
            "Good value for money, works as advertised with no surprises.",
            "Minor issues were handled quickly by customer service and resolved fast.",
            "Perfect for my needs, highly recommended after a few weeks of use.",
            "Decent product but could be improved in some small areas.",
        ]
        # Spread across 5 distinct rating values to maximize diversity.
        high_ratings = [1.0, 2.0, 3.0, 4.0, 5.0] * 10
        high_reviews = [
            MockReview(
                high_texts[i % len(high_texts)],
                high_ratings[i],
                NOW - timedelta(days=i * 3),
            )
            for i in range(50)
        ]

        # Short, identical texts, same rating, all clustered within a few days.
        low_reviews = [MockReview("Great!", 5.0, NOW - timedelta(days=i // 10)) for i in range(10)]

        high_score = calculate_confidence(high_reviews)
        low_score = calculate_confidence(low_reviews)
        assert high_score > low_score
