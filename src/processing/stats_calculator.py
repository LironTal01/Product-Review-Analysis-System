"""Compute aggregate statistics from a list of reviews.

Official TDD #2 — implementation written after tests were green-lit as failing.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from src.models.analysis import StatsResult
from src.models.review import Review

_NEGATIVE_CEILING = 3  # ratings 1-3 count as negative


def calculate_stats(reviews: Sequence[Review]) -> StatsResult:
    """Aggregate a batch of reviews into a StatsResult.

    Args:
        reviews: Sequence of Review objects (may be empty).

    Returns:
        StatsResult with avg_rating, total_reviews, rating_distribution,
        and negative_count populated.  Empty input yields all-zero fields.
    """
    if not reviews:
        return StatsResult(
            avg_rating=0.0,
            total_reviews=0,
            rating_distribution={s: 0 for s in range(1, 6)},
            negative_count=0,
        )

    ratings = [int(r.rating) for r in reviews]
    counts: Counter[int] = Counter(ratings)

    return StatsResult(
        avg_rating=sum(r.rating for r in reviews) / len(reviews),
        total_reviews=len(reviews),
        rating_distribution={s: counts.get(s, 0) for s in range(1, 6)},
        negative_count=sum(1 for r in reviews if r.rating <= _NEGATIVE_CEILING),
    )
