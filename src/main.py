"""FastAPI application entrypoint for PRAS.

This file wires the static browser UI to a JSON API. The analysis endpoint
currently returns deterministic mock data so the frontend can be developed
end-to-end before the backend pipeline (Partner A) is finished. When
``src.core.analyzer.analyze_product`` becomes available, the handler will
delegate to it instead of returning the mock payload.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.db.postgres import get_analysis, init_db, save_analysis
from src.db.redis_cache import get_cached, set_cached
from src.utils.logger import logger
from src.utils.url_parser import (
    AmazonURLError,
    InvalidASINError,
    extract_asin,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Best-effort schema bootstrap. Missing/unreachable Postgres is non-fatal."""
    init_db()
    yield


app = FastAPI(
    title="Product Review Analysis System",
    description="Analyze Amazon product reviews with AI.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AnalyzeRequest(BaseModel):
    """Request body for ``POST /api/analyze``."""

    amazon_url: str = Field(..., min_length=1, description="Amazon product URL")
    max_reviews: int = Field(
        100,
        ge=100,
        le=500,
        description="How many reviews to analyze (clamped 100–500).",
    )


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    """Serve the single-page browser UI."""
    return FileResponse(str(INDEX_FILE))


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by Azure / Docker / smoke tests."""
    return {"status": "healthy"}


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest) -> JSONResponse:
    """Validate the URL and return an analysis payload.

    Lookup order:
    1. Validate URL → ``asin``.
    2. Redis cache (24h TTL) — fastest path, returns immediately on hit.
    3. Postgres (durable storage) — if found, refresh the Redis cache and
       return.
    4. Otherwise compute (currently a deterministic mock until Partner A's
       core pipeline lands), persist the result to Postgres, cache it in
       Redis, and return it.

    Both stores are **optional**: when ``REDIS_URL`` / ``DATABASE_URL``
    are empty or unreachable, the affected layers degrade silently and the
    endpoint still returns a fresh payload.
    """
    try:
        asin = extract_asin(request.amazon_url)
    except (AmazonURLError, InvalidASINError) as exc:
        logger.warning("Rejected analyze request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Analyze request accepted: asin=%s max_reviews=%d", asin, request.max_reviews)

    cached = get_cached(asin, request.max_reviews)
    if cached is not None:
        logger.info("Redis hit: asin=%s max_reviews=%d", asin, request.max_reviews)
        return JSONResponse(cached)

    stored = get_analysis(asin, request.max_reviews)
    if stored is not None:
        logger.info("Postgres hit: asin=%s max_reviews=%d", asin, request.max_reviews)
        set_cached(asin, request.max_reviews, stored)
        return JSONResponse(stored)

    payload = _build_mock_analysis(asin=asin, max_reviews=request.max_reviews)
    save_analysis(asin, request.max_reviews, payload)
    set_cached(asin, request.max_reviews, payload)
    return JSONResponse(payload)


def _build_mock_analysis(*, asin: str, max_reviews: int) -> dict:
    """Return a deterministic mock payload shaped like ``AnalysisResult``.

    Replaced by a real call to ``analyze_product`` once Partner A's pipeline
    lands in ``src/core/analyzer.py``.
    """
    rating_distribution = {5: 142, 4: 78, 3: 31, 2: 15, 1: 9}
    total_reviews = sum(rating_distribution.values())
    avg_rating = sum(star * count for star, count in rating_distribution.items()) / total_reviews

    return {
        "product_title": f"Sample product ({asin})",
        "product_image_url": "",
        "product_price": "$129.99",
        "amazon_rating": round(avg_rating, 1),
        "total_review_count": total_reviews,
        "summary_text": (
            "Most reviewers praise the build quality and battery life, while a "
            "minority report connectivity issues with older devices. Overall the "
            "product is described as a strong value for the price."
        ),
        "recommendation": (
            "Recommended for users who prioritize battery life and comfort. "
            "Less ideal if you need flawless multi-device pairing on day one."
        ),
        "confidence_score": 0.82,
        "confidence_explanation": (
            f"Based on {min(max_reviews, total_reviews)} cleaned reviews with "
            "consistent themes across rating bands."
        ),
        "pros": [
            "Long battery life (often 20+ hours)",
            "Comfortable for extended wear",
            "Clear call quality on the primary device",
            "Solid build, feels premium for the price",
        ],
        "cons": [
            "Occasional Bluetooth dropouts when switching devices",
            "Touch controls are sensitive and easy to trigger by accident",
            "Carrying case scratches more easily than expected",
        ],
        "aspects": [
            {"name": "battery life", "sentiment": "positive", "mention_count": 87},
            {"name": "comfort", "sentiment": "positive", "mention_count": 64},
            {"name": "sound quality", "sentiment": "positive", "mention_count": 52},
            {"name": "bluetooth pairing", "sentiment": "negative", "mention_count": 28},
            {"name": "touch controls", "sentiment": "mixed", "mention_count": 22},
            {"name": "build quality", "sentiment": "positive", "mention_count": 19},
            {"name": "shipping", "sentiment": "mixed", "mention_count": 11},
            {"name": "price", "sentiment": "positive", "mention_count": 35},
        ],
        "rating_distribution": rating_distribution,
        "negative_summary": (
            "Lower-rated reviews focus mainly on Bluetooth pairing problems with "
            "older laptops and a few reports of the case finish wearing quickly."
        ),
        "total_reviews_analyzed": min(max_reviews, total_reviews),
        "avg_rating": round(avg_rating, 2),
    }
