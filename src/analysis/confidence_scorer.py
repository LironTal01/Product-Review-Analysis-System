"""Confidence score for a batch of reviews (duck-typed).

We mix three simple signals: how many reviews there are, how spread out the
ratings are, and how long the texts are on average. Empty input always gives 0.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from typing import TypeVar

TReview = TypeVar("TReview")

# Max population std for ratings in [1, 5] is about 2.0 (half 1s, half 5s).
_MAX_RATING_STDEV = 2.0

# Text length is capped so one crazy long review does not dominate.
_TEXT_LEN_CAP = 200


def calculate_confidence(reviews: Iterable[TReview]) -> float:
    """Return a confidence score in [0.0, 1.0] from count, rating spread, and text length."""

    reviews_list = list(reviews)
    if not reviews_list:
        return 0.0

    n = len(reviews_list)

    # More reviews -> higher score, but it flattens after ~200 (log scale).
    count_factor = min(math.log(n + 1) / math.log(201), 1.0)

    # Pull numeric ratings only (ignore None / weird types).
    ratings: list[float] = []
    for r in reviews_list:
        rating = getattr(r, "rating", None)
        if rating is None or isinstance(rating, bool) or not isinstance(rating, int | float):
            continue
        ratings.append(float(rating))

    spread_raw = statistics.pstdev(ratings) if len(ratings) >= 2 else 0.0
    # Normalize: more spread in 1..5 -> closer to 1.
    spread_factor = min(spread_raw / _MAX_RATING_STDEV, 1.0)

    # Average "effective" text length (None counts as 0), then squash into 0..1.
    text_lengths: list[float] = []
    for r in reviews_list:
        text = getattr(r, "text", None)
        if text is None:
            text_lengths.append(0.0)
        else:
            text_lengths.append(float(min(len(str(text)), _TEXT_LEN_CAP)))
    avg_len = sum(text_lengths) / n if n else 0.0
    text_quality_factor = min(avg_len / float(_TEXT_LEN_CAP), 1.0)

    score = (0.5 * count_factor) + (0.3 * spread_factor) + (0.2 * text_quality_factor)
    return max(0.0, min(1.0, float(score)))
