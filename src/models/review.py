"""Domain dataclass for raw review records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Review:
    """Represents one customer review used in the analysis pipeline.

    Attributes:
        review_id: Stable Amazon review ID when available.
        text: Review text.
        rating: Star rating in the range 1.0-5.0.
        date: Review date string (usually "YYYY-MM-DD").
        helpful_votes: Helpful vote count (>= 0).
        verified_purchase: Whether the review is from a verified purchase.
    """

    text: str
    rating: float
    date: str = ""
    helpful_votes: int = 0
    verified_purchase: bool = True
    review_id: str = ""
