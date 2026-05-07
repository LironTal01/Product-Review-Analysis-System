"""Unit tests for review cleaning and spam filtering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from src.processing.review_cleaner import (
    clean_reviews_pipeline,
    filter_spam_reviews,
    normalize_ratings,
    remove_empty_reviews,
    validate_review_quality,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 3, 24, 12, 0, 0)


@dataclass
class MockReview:
    """Mock review for testing purposes."""

    text: str | None
    rating: float | None
    date: datetime
    helpful_votes: int = 0
    verified_purchase: bool = True


class TestFilterSpamReviews:
    """Low-signal / promo-like rows should be dropped; substantive text kept."""

    @pytest.mark.parametrize(
        ("reviews", "expected_texts"),
        [
            (
                [
                    MockReview("Buy now at a huge discount!", 5.0, NOW),
                    MockReview("This is a normal review about quality.", 4.0, NOW),
                    MockReview("Visit our website for more deals!", 5.0, NOW),
                ],
                ["This is a normal review about quality."],
            ),
            (
                [
                    MockReview("Good", 5.0, NOW),
                    MockReview("This product exceeded my expectations.", 4.0, NOW),
                    MockReview("Ok", 3.0, NOW),
                ],
                ["This product exceeded my expectations."],
            ),
            (
                [
                    MockReview("Greaaaaaaat product!!!!!!", 5.0, NOW),
                    MockReview("This is a normal review with proper text.", 4.0, NOW),
                    MockReview("Wooooooooow amazing", 5.0, NOW),
                ],
                ["This is a normal review with proper text."],
            ),
            (
                [
                    MockReview(
                        "The battery life is excellent, lasting about 8 hours.",
                        5.0,
                        NOW,
                    ),
                    MockReview("Delivery was fast but had minor scratches.", 3.0, NOW),
                    MockReview("Good value for money, quality could be better.", 4.0, NOW),
                ],
                [
                    "The battery life is excellent, lasting about 8 hours.",
                    "Delivery was fast but had minor scratches.",
                    "Good value for money, quality could be better.",
                ],
            ),
        ],
    )
    def test_filter_spam_reviews_keeps_expected_reviews(self, reviews, expected_texts):
        # Regression: exact expected list encodes current product rules.
        filtered = filter_spam_reviews(reviews)
        assert [r.text for r in filtered] == expected_texts

    def test_filter_spam_drops_promo_and_keeps_substantive_row(self):
        # Behavior-focused: promo rows go away; one substantive review remains.
        reviews = [
            MockReview("Limited time!!! Buy now cheap!!!", 5.0, NOW),
            MockReview(
                "After two weeks of daily use the build quality still feels solid.",
                4.0,
                NOW,
            ),
            MockReview("Click here for more deals!", 5.0, NOW),
        ]
        filtered = filter_spam_reviews(reviews)
        assert len(filtered) == 1 and len(filtered[0].text or "") > 40


class TestNormalizeRatings:
    """Policy tested here: clamp numeric ratings into [1, 5]; drop missing or invalid ratings."""

    @pytest.mark.parametrize(
        ("reviews", "expected_ratings"),
        [
            (
                [
                    MockReview("Good product", 0.0, NOW),
                    MockReview("Great product", 6.0, NOW),
                    MockReview("Normal rating", 4.0, NOW),
                ],
                [1.0, 5.0, 4.0],
            ),
            (
                [
                    MockReview("No rating given", None, NOW),
                    MockReview("Has rating", 4.0, NOW),
                ],
                [4.0],
            ),
            (
                [
                    MockReview("Bad type", "not-a-number", NOW),  # type: ignore[arg-type]
                    MockReview("Has rating", 4.0, NOW),
                ],
                [4.0],
            ),
        ],
    )
    def test_normalize_ratings_returns_expected_values(self, reviews, expected_ratings):
        normalized = normalize_ratings(reviews)
        assert [r.rating for r in normalized] == expected_ratings


class TestRemoveEmptyReviews:
    """Drop rows with no readable text; keep short but meaningful text."""

    @pytest.mark.parametrize(
        ("reviews", "expected_texts"),
        [
            (
                [
                    MockReview("", 4.0, NOW),
                    MockReview("   ", 3.0, NOW),
                    MockReview("Actual review text", 5.0, NOW),
                    MockReview("", 2.0, NOW),
                ],
                ["Actual review text"],
            ),
            (
                [
                    MockReview("Short but valid", 4.0, NOW),
                    MockReview("Another valid review with more content", 3.0, NOW),
                ],
                ["Short but valid", "Another valid review with more content"],
            ),
            (
                [
                    MockReview(None, 4.0, NOW),
                    MockReview("Kept", 5.0, NOW),
                ],
                ["Kept"],
            ),
            (
                [
                    MockReview("!!!", 4.0, NOW),
                    MockReview("...", 4.0, NOW),
                    MockReview("Real words here", 5.0, NOW),
                ],
                ["Real words here"],
            ),
        ],
    )
    def test_remove_empty_reviews_keeps_expected_reviews(self, reviews, expected_texts):
        cleaned = remove_empty_reviews(reviews)
        assert [r.text for r in cleaned] == expected_texts

    def test_remove_empty_keeps_short_legitimate_phrase(self):
        reviews = [MockReview("Works well", 4.0, NOW)]
        assert [r.text for r in remove_empty_reviews(reviews)] == ["Works well"]


class TestValidateReviewQuality:
    """Scores should be comparable and stay in range (implementation can tune weights)."""

    @pytest.mark.parametrize(
        "review",
        [
            MockReview(
                "This is a detailed review about quality and performance.",
                4.0,
                NOW - timedelta(days=30),
                helpful_votes=10,
                verified_purchase=True,
            ),
            MockReview(
                "bad",
                5.0,
                NOW,
                helpful_votes=0,
                verified_purchase=False,
            ),
        ],
    )
    def test_validate_review_quality_score_between_zero_and_one(self, review):
        score = validate_review_quality(review)
        assert 0.0 <= score <= 1.0

    def test_detailed_review_scores_higher_than_low_signal_review(self):
        detailed = MockReview(
            "This is a detailed review about quality and performance.",
            4.0,
            NOW - timedelta(days=30),
            helpful_votes=10,
            verified_purchase=True,
        )
        low_signal = MockReview(
            "bad",
            5.0,
            NOW,
            helpful_votes=0,
            verified_purchase=False,
        )
        assert validate_review_quality(detailed) > validate_review_quality(low_signal)


class TestReviewCleaningPipeline:
    """End-to-end ordering of steps (empty strip → normalize → spam filter)."""

    def test_clean_reviews_pipeline_returns_expected_texts(self):
        reviews = [
            MockReview("", 4.0, NOW),
            MockReview("Buy now!!!", 5.0, NOW),
            MockReview("Excellent product with great battery life", 5.0, NOW),
            MockReview("ok", 3.0, NOW),
            MockReview(
                "Good value for the price, recommended",
                4.0,
                NOW,
            ),
        ]

        cleaned = clean_reviews_pipeline(reviews)
        assert [r.text for r in cleaned] == [
            "Excellent product with great battery life",
            "Good value for the price, recommended",
        ]


class TestEmptyInputsOnSingleStepFunctions:
    """Each public helper should accept an empty list without crashing."""

    @pytest.mark.parametrize(
        "func",
        [filter_spam_reviews, normalize_ratings, remove_empty_reviews],
    )
    def test_empty_reviews_returns_empty_list(self, func):
        assert func([]) == []
