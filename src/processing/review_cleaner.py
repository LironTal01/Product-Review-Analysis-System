"""Review cleaning helpers.
Note: This file is intentionally a minimal stub for now.
It exists so tests can run (red) without import errors.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from typing import TypeVar

TReview = TypeVar("TReview")

# Small list of promo phrases we consider spam (case-insensitive match).
_PROMO_PHRASES = (
    "buy now",
    "click here",
    "huge discount",
    "visit our website",
    "limited time",
    "for more deals",
)


def filter_spam_reviews(reviews: Iterable[TReview]) -> list[TReview]:
    """Remove only clear promo spam while keeping most real user phrasing."""

    # Precompile patterns once for speed + cleaner loop.
    promo_re = re.compile("|".join(re.escape(p) for p in _PROMO_PHRASES), re.IGNORECASE)
    out: list[TReview] = []
    for review in reviews:
        # If text is missing we just ignore the row here.
        text = getattr(review, "text", None)
        if text is None:
            continue

        normalized = str(text).strip()

        # Keep short reviews too; only drop near-empty snippets.
        if len(normalized) < 3:
            continue

        # Drop explicit promo-like rows.
        if promo_re.search(normalized):
            continue

        # Passed all filters -> keep it.
        out.append(review)

    return out


def normalize_ratings(reviews: Iterable[TReview]) -> list[TReview]:
    """Keep only numeric ratings and clamp them into [1.0, 5.0]."""

    out: list[TReview] = []
    for review in reviews:
        rating = getattr(review, "rating", None)
        # No rating -> drop the row (we can't normalize it).
        if rating is None:
            continue

        # bool is an int subclass; treat it as invalid for ratings.
        if isinstance(rating, bool) or not isinstance(rating, int | float):
            continue

        # Clamp to the valid range. We keep float output to be consistent.
        clamped = max(1.0, min(5.0, float(rating)))
        try:
            # Tests expect we don't mutate objects in-place (dataclass replace).
            out.append(replace(review, rating=clamped))
        except TypeError:
            # Fallback for non-dataclass objects: best-effort copy.
            new_obj = review
            try:
                data = dict(vars(review))
                data["rating"] = clamped
                new_obj = type(review)(**data)
            except Exception:  # noqa: BLE001
                pass
            out.append(new_obj)

    return out


def remove_empty_reviews(reviews: Iterable[TReview]) -> list[TReview]:
    """Drop reviews with no real readable text."""

    out: list[TReview] = []
    for review in reviews:
        text = getattr(review, "text", None)
        # If text is None there is nothing to clean/keep.
        if text is None:
            continue

        s = str(text)
        # Empty string or just spaces.
        if not s.strip():
            continue

        # Only punctuation like "!!!" / "..." is not helpful.
        if not any(ch.isalpha() for ch in s):
            continue

        out.append(review)

    return out


def validate_review_quality(review: TReview) -> float:
    """Give a simple quality score (0..1) for ranking/filtering."""

    text = getattr(review, "text", None) or ""
    text = str(text).strip()
    length = len(text)

    # Longer text is usually better, but after ~200 chars it matters less.
    length_score = min(length / 200.0, 1.0)

    # Word count helps too (but also saturates).
    tokens = re.findall(r"\b\w+\b", text)
    word_count = sum(1 for t in tokens if any(ch.isalpha() for ch in t))
    word_score = min(word_count / 40.0, 1.0)

    # Base score from text signals.
    score = (0.6 * length_score) + (0.3 * word_score)

    # Helpful votes are a small bonus (capped so it won't dominate).
    helpful_votes = getattr(review, "helpful_votes", 0) or 0
    if isinstance(helpful_votes, int) and helpful_votes > 0:
        score += 0.05 + (min(helpful_votes, 20) / 20.0) * 0.05

    # Verified purchase is also a small bonus.
    if bool(getattr(review, "verified_purchase", False)):
        score += 0.10

    # Safety clamp to stay inside 0..1.
    return max(0.0, min(1.0, float(score)))


def _canonical_text_for_dedupe(text: str) -> str:
    """Canonical text used for soft dedupe comparisons."""
    lowered = text.lower()
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def dedupe_similar_reviews(reviews: Iterable[TReview]) -> list[TReview]:
    """Drop near-identical reviews while preserving original order."""
    out: list[TReview] = []
    seen_canonical: set[str] = set()
    for review in reviews:
        text = getattr(review, "text", None)
        if text is None:
            continue
        canonical = _canonical_text_for_dedupe(str(text))
        if not canonical:
            continue
        if canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        out.append(review)
    return out


def clean_reviews_pipeline(reviews: Iterable[TReview]) -> list[TReview]:
    """Run the cleaning steps in a fixed order."""

    # Order matters: first drop empty texts, then normalize ratings, then spam filter.
    out = remove_empty_reviews(reviews)
    out = normalize_ratings(out)
    out = filter_spam_reviews(out)
    out = dedupe_similar_reviews(out)
    return out
