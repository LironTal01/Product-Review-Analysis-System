"""FastAPI application entrypoint for PRAS.

This file wires the static browser UI to a JSON API. The analysis endpoint
uses the full pipeline: URL parsing, mock reviews, cleaning, embeddings,
LLM analysis, and result assembly.
"""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.analyzer import analyze_product
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
    """Load .env, clear settings cache, bootstrap DB."""
    from dotenv import load_dotenv

    from src.utils.config import get_settings

    load_dotenv()
    get_settings.cache_clear()

    settings = get_settings()
    logger.info(
        "PRAS API starting up (scraper key: %s)", "SET" if settings.scraper_api_key else "NOT SET"
    )
    init_db()
    yield
    logger.info("PRAS API shutting down")


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
        ge=25,
        le=250,
        description="How many reviews to analyze (clamped 25–250).",
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
    4. Otherwise compute, persist/cache the result, and return it.

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

    # Run the real analysis pipeline (embeddings + LLM)
    try:
        result = analyze_product(request.amazon_url, request.max_reviews)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    # Convert dataclass to dict so it can be serialized to JSON
    payload = dataclasses.asdict(result)

    # Cache and persist the result for future requests
    save_analysis(asin, request.max_reviews, payload)
    set_cached(asin, request.max_reviews, payload)
    return JSONResponse(payload)
