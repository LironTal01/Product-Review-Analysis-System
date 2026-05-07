"""Temporary local cache (non-Redis, non-Postgres).

This module centralizes short-term on-disk caches so it is easy to remove
later when persistent infrastructure is fully configured.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from src.models.review import Review
from src.utils.logger import setup_logger

logger = setup_logger("pras.temp_cache")

_ROOT = Path(".cache")
_RAW_DIR = _ROOT / "raw_reviews"
_META_DIR = _ROOT / "product_meta"
_EMB_DIR = _ROOT / "embeddings"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cache read failed (%s): %s", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_count_from_raw_name(path: Path) -> int | None:
    match = re.match(r".+_(\d+)$", path.stem)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_raw_reviews(asin: str, max_reviews: int) -> tuple[list[Review], dict[str, str]] | None:
    """Load raw reviews cache, allowing reuse of bigger cached sets."""
    exact = _RAW_DIR / f"{asin}_{max_reviews}.json"
    candidates = [exact]

    if _RAW_DIR.exists():
        for path in _RAW_DIR.glob(f"{asin}_*.json"):
            count = _parse_count_from_raw_name(path)
            if count is None or count < max_reviews:
                continue
            if path not in candidates:
                candidates.append(path)

    if not candidates:
        return None

    # Prefer exact key; otherwise the smallest available superset.
    if len(candidates) > 1:
        candidates = sorted(
            candidates,
            key=lambda p: (_parse_count_from_raw_name(p) or 10**9, len(str(p))),
        )

    for path in candidates:
        payload = _read_json(path)
        if not payload:
            continue
        reviews_raw = payload.get("reviews")
        meta_raw = payload.get("meta")
        if not isinstance(reviews_raw, list):
            continue

        reviews: list[Review] = []
        for item in reviews_raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            try:
                rating = float(str(item.get("rating", "3.0")))
            except ValueError:
                rating = 3.0
            reviews.append(
                Review(
                    text=text,
                    rating=rating,
                    date=str(item.get("date", "")),
                    helpful_votes=_to_int(item.get("helpful_votes", 0)),
                    verified_purchase=bool(item.get("verified_purchase", True)),
                )
            )
        if not reviews:
            continue

        meta: dict[str, str] = {}
        if isinstance(meta_raw, dict):
            meta = {str(k): str(v) for k, v in meta_raw.items()}

        result_reviews = reviews[:max_reviews]
        logger.info(
            "Raw cache hit: asin=%s asked=%d source=%s returned=%d",
            asin,
            max_reviews,
            path.name,
            len(result_reviews),
        )
        return result_reviews, meta

    return None


def save_raw_reviews(
    asin: str, max_reviews: int, reviews: list[Review], meta: dict[str, str]
) -> None:
    """Save raw reviews cache under (asin, max_reviews)."""
    path = _RAW_DIR / f"{asin}_{max_reviews}.json"
    payload = {
        "asin": asin,
        "max_reviews": max_reviews,
        "reviews": [
            {
                "text": review.text,
                "rating": review.rating,
                "date": review.date,
                "helpful_votes": review.helpful_votes,
                "verified_purchase": review.verified_purchase,
            }
            for review in reviews
        ],
        "meta": meta,
    }
    try:
        _write_json(path, payload)
        logger.info("Raw cache saved: %s (%d reviews)", path, len(reviews))
    except OSError as exc:
        logger.warning("Raw cache write failed (%s): %s", path, exc)


def load_product_meta(asin: str) -> dict[str, str] | None:
    payload = _read_json(_META_DIR / f"{asin}.json")
    if not payload:
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    result = {str(k): str(v) for k, v in meta.items()}
    if not result:
        return None
    logger.info("Product meta cache hit: asin=%s", asin)
    return result


def save_product_meta(asin: str, meta: dict[str, str]) -> None:
    if not meta:
        return
    path = _META_DIR / f"{asin}.json"
    try:
        _write_json(path, {"asin": asin, "meta": meta})
        logger.info("Product meta cache saved: asin=%s", asin)
    except OSError as exc:
        logger.warning("Product meta cache write failed (%s): %s", path, exc)


def _embedding_key(model: str, texts: list[str]) -> str:
    joined = "\x1f".join(texts)
    digest = hashlib.sha256(f"{model}\x1e{joined}".encode()).hexdigest()
    return digest


def load_embeddings(model: str, texts: list[str]) -> np.ndarray | None:
    key = _embedding_key(model, texts)
    payload = _read_json(_EMB_DIR / f"{key}.json")
    if not payload:
        return None
    vectors = payload.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        return None
    try:
        arr = np.array(vectors, dtype=np.float32)
    except Exception:
        return None
    logger.info("Embeddings cache hit: key=%s count=%d", key[:8], len(texts))
    return arr


def save_embeddings(model: str, texts: list[str], embeddings: np.ndarray) -> None:
    key = _embedding_key(model, texts)
    path = _EMB_DIR / f"{key}.json"
    payload = {
        "model": model,
        "count": len(texts),
        "vectors": embeddings.tolist(),
    }
    try:
        _write_json(path, payload)
        logger.info("Embeddings cache saved: key=%s count=%d", key[:8], len(texts))
    except OSError as exc:
        logger.warning("Embeddings cache write failed (%s): %s", path, exc)
