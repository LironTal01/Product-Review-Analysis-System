"""Unit tests for stats_calculator — Official TDD #2.

Red-green-refactor: tests were written before the implementation.
Covers rating distribution totals, negative counting, average
computation, and the empty-input edge case via parametrize-driven
scenarios.

A stub returning zeroed StatsResult passes the empty-input class but
fails distribution sums and averages — proving the tests drive a real
implementation.
"""

from __future__ import annotations

import pytest

from src.models.analysis import StatsResult
from src.models.review import Review
from src.processing.stats_calculator import calculate_stats

pytestmark = pytest.mark.unit


def _make_reviews(ratings: list[float]) -> list[Review]:
    """Shortcut to build Review objects when only the rating matters."""
    return [Review(text="review text", rating=r) for r in ratings]


# ── rating_distribution sums to total ───────────────────────────────────


class TestRatingDistributionSumsToTotal:
    """Every review must land in exactly one star bucket."""

    @pytest.mark.parametrize(
        "ratings",
        [
            pytest.param([5, 4, 3, 2, 1, 4, 5, 3], id="mixed_8_reviews"),
            pytest.param([1, 1, 1], id="all_one_star"),
            pytest.param([5], id="single_five_star"),
            pytest.param([1, 2, 3, 4, 5] * 4, id="uniform_20_reviews"),
        ],
    )
    def test_bucket_sum_equals_total_reviews(self, ratings: list[float]):
        reviews = _make_reviews(ratings)

        result = calculate_stats(reviews)

        assert sum(result.rating_distribution.values()) == result.total_reviews

    @pytest.mark.parametrize(
        "star",
        [1, 2, 3, 4, 5],
        ids=["one_star", "two_star", "three_star", "four_star", "five_star"],
    )
    def test_each_star_bucket_present_in_distribution(self, star: int):
        """Distribution dict should contain keys 1-5 even if some are zero."""
        reviews = _make_reviews([1, 2, 3, 4, 5])

        result = calculate_stats(reviews)

        assert star in result.rating_distribution


# ── negative_count counts ratings 1-3 ───────────────────────────────────


class TestNegativeCountCountsRatings1To3:
    """Stars 1-3 are considered negative; 4-5 are positive."""

    @pytest.mark.parametrize(
        ("ratings", "expected"),
        [
            pytest.param([1, 2, 3, 4, 5], 3, id="mixed_3_of_5_negative"),
            pytest.param([4, 5, 5, 4], 0, id="all_positive_yields_zero"),
            pytest.param([1, 1, 2, 3], 4, id="all_low_rated"),
            pytest.param([3], 1, id="boundary_3_star_counts_as_negative"),
            pytest.param([4], 0, id="boundary_4_star_counts_as_positive"),
        ],
    )
    def test_negative_count_matches_expected(self, ratings: list[float], expected: int):
        reviews = _make_reviews(ratings)

        result = calculate_stats(reviews)

        assert result.negative_count == expected


# ── avg_rating calculation ───────────────────────────────────────────────


class TestAvgRatingCalculation:
    """The average should reflect the arithmetic mean of all star values."""

    @pytest.mark.parametrize(
        ("ratings", "expected_avg"),
        [
            pytest.param([1, 2, 3, 4, 5], 3.0, id="sequential_1_to_5"),
            pytest.param([4, 4, 4, 4], 4.0, id="uniform_fours"),
            pytest.param([1, 1, 5], 7 / 3, id="fractional_result"),
            pytest.param([5, 5, 5, 5, 5], 5.0, id="perfect_score"),
            pytest.param([1], 1.0, id="single_review"),
        ],
    )
    def test_avg_rating_equals_arithmetic_mean(self, ratings: list[float], expected_avg: float):
        reviews = _make_reviews(ratings)

        result = calculate_stats(reviews)

        assert result.avg_rating == pytest.approx(expected_avg)


# ── empty input edge case ────────────────────────────────────────────────


class TestEmptyReviewsReturnsZeroStats:
    """Passing no reviews should not crash and must yield safe defaults."""

    def test_total_reviews_is_zero(self):
        result = calculate_stats([])

        assert result.total_reviews == 0

    def test_avg_rating_is_zero(self):
        result = calculate_stats([])

        assert result.avg_rating == 0.0

    def test_negative_count_is_zero(self):
        result = calculate_stats([])

        assert result.negative_count == 0

    def test_distribution_has_no_counted_reviews(self):
        """All buckets exist but their sum is zero."""
        result = calculate_stats([])

        assert sum(result.rating_distribution.values()) == 0

    def test_returns_stats_result_instance(self):
        result = calculate_stats([])

        assert isinstance(result, StatsResult)
