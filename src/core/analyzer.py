"""Core pipeline orchestrator - chains every processing step into one
analyze_product call that returns a fully populated AnalysisResult.

Pipeline: URL -> ASIN -> fetch reviews (real scraping or mock fallback)
-> clean -> stats -> embed -> top-K -> LLM -> assemble result.
"""

from __future__ import annotations

from openai import OpenAI

from src.analysis.confidence_scorer import calculate_confidence
from src.analysis.embeddings import embed_reviews, select_top_k
from src.analysis.llm_analyzer import analyze_with_llm
from src.data.amazon_scraper import scrape_product_meta, scrape_reviews_with_meta
from src.data.mock_reviews import PRODUCT_META, get_mock_reviews
from src.models.analysis import AnalysisResult, AspectInfo, StatsResult
from src.processing.review_cleaner import clean_reviews_pipeline
from src.processing.stats_calculator import calculate_stats
from src.utils.config import get_settings
from src.utils.logger import setup_logger
from src.utils.url_parser import extract_asin

logger = setup_logger("pras.analyzer")

_TOP_K = 20


def _as_float(value) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fallback_llm_output(stats: StatsResult) -> dict:
    """Return a safe structured fallback when LLM/embeddings are unavailable."""
    positive = stats.total_reviews - stats.negative_count
    negative = stats.negative_count

    if stats.total_reviews == 0:
        tone = "No review data is available."
    elif stats.avg_rating >= 4.0:
        tone = "Review sentiment is mostly positive."
    elif stats.avg_rating >= 3.0:
        tone = "Review sentiment is mixed."
    else:
        tone = "Review sentiment is mostly negative."

    return {
        "summary_text": (
            f"{tone} Average rating is {stats.avg_rating:.2f}/5 based on "
            f"{stats.total_reviews} analyzed reviews."
        ),
        "pros": (
            [
                "Many customers report a positive overall experience.",
                "Higher-star reviews outweigh lower-star ones.",
            ]
            if positive >= negative
            else ["Some customers still report acceptable baseline performance."]
        ),
        "cons": (
            [
                "Low-rated reviews indicate recurring quality or expectation gaps.",
                "A meaningful share of users report dissatisfaction.",
            ]
            if negative > 0
            else ["No strong recurring complaints were detected from ratings alone."]
        ),
        "aspects": [
            {
                "name": "overall satisfaction",
                "sentiment": "positive" if stats.avg_rating >= 3.5 else "negative",
                "mention_count": stats.total_reviews,
            }
        ],
        "recommendation": (
            "Recommended — average rating is above 3.5."
            if stats.avg_rating >= 3.5
            else "Consider alternatives — average rating is below 3.5."
        ),
        "confidence_explanation": (
            "Fallback analysis was generated from rating statistics because "
            "the LLM pipeline was unavailable for this request."
        ),
        "negative_summary": (
            f"{stats.negative_count} out of {stats.total_reviews} reviews are 1-3 stars."
            if stats.total_reviews
            else "No negative summary available."
        ),
    }


def analyze_product(url: str, max_reviews: int = 200) -> AnalysisResult:
    """Run the full analysis pipeline for an Amazon product URL.

    Args:
        url: Amazon product page URL containing a valid ASIN.
        max_reviews: how many reviews to analyze (clamped 25-250).

    Returns:
        Fully populated AnalysisResult ready for JSON serialization.
    """
    # 1. Extract ASIN from URL
    asin = extract_asin(url)
    logger.info("Pipeline start: asin=%s max_reviews=%d", asin, max_reviews)

    # 2. Try to scrape real reviews from Amazon first
    reviews, review_page_meta = scrape_reviews_with_meta(asin, max_reviews)

    if len(reviews) >= 5:
        # Got enough real reviews, use them
        logger.info("Using %d REAL reviews from Amazon", len(reviews))
        use_real = True
    else:
        # Scraping failed or got too few, fall back to mock data
        logger.warning("Scraping got only %d reviews, falling back to mock data", len(reviews))
        reviews = get_mock_reviews(asin, max_reviews)
        use_real = False
        logger.info("Using %d MOCK reviews", len(reviews))

    # 3. Clean and filter
    cleaned = clean_reviews_pipeline(reviews)
    logger.info("Cleaned down to %d reviews", len(cleaned))

    # 4. Compute stats on cleaned set
    stats = calculate_stats(cleaned)

    # 5. Confidence score
    confidence = calculate_confidence(cleaned)

    # 6-7. Embed and select top-K, then send to LLM
    settings = get_settings()
    llm_output: dict
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        embeddings = embed_reviews(cleaned, client)
        top_k = select_top_k(cleaned, embeddings, k=_TOP_K)
        logger.info("Selected %d representative reviews for LLM", len(top_k))
        llm_output = analyze_with_llm(top_k, stats, client)
    except Exception as exc:
        logger.warning("LLM pipeline unavailable, using stats fallback: %s", exc)
        llm_output = _fallback_llm_output(stats)

    # 8. Try to get real product info from Amazon if we used real reviews
    real_meta = {}
    if use_real:
        real_meta = scrape_product_meta(asin)
        if review_page_meta:
            # Prefer product meta for title/image/price, but keep review-page
            # review-count aggregate when available.
            for key in ("total_review_count",):
                if key not in real_meta and key in review_page_meta:
                    real_meta[key] = review_page_meta[key]
        logger.info("Scraped product meta: %s", list(real_meta.keys()))

    # 9. Assemble final result
    return _assemble_result(llm_output, stats, confidence, asin, real_meta)


def _assemble_result(
    llm_output: dict,
    stats: StatsResult,
    confidence: float,
    asin: str,
    real_meta: dict | None = None,
) -> AnalysisResult:
    """Map LLM structured output + computed stats + confidence into a
    complete AnalysisResult with safe fallbacks for missing fields.
    """
    # Use real product metadata if available, otherwise fall back to mock catalog
    meta = real_meta if real_meta else PRODUCT_META.get(asin, {})

    # Build AspectInfo objects from the raw dicts returned by the LLM
    aspects = [
        AspectInfo(
            name=a.get("name", "unknown"),
            sentiment=a.get("sentiment", "mixed"),
            mention_count=a.get("mention_count", 1),
        )
        for a in llm_output.get("aspects", [])
    ]

    recommendation = llm_output.get("recommendation", "")
    if not recommendation:
        recommendation = (
            "Recommended — average rating is above 3.5."
            if stats.avg_rating >= 3.5
            else "Consider alternatives — average rating is below 3.5."
        )

    amazon_rating = _as_float(meta.get("amazon_rating"))
    if amazon_rating is None:
        amazon_rating = round(stats.avg_rating, 1)

    total_review_count = _as_int(meta.get("total_review_count"))
    if total_review_count is None:
        total_review_count = stats.total_reviews

    return AnalysisResult(
        product_title=meta.get("title", f"Product {asin}"),
        product_image_url=meta.get("image_url", ""),
        product_price=meta.get("price", ""),
        amazon_rating=amazon_rating,
        total_review_count=total_review_count,
        summary_text=llm_output.get("summary_text", ""),
        recommendation=recommendation,
        confidence_score=round(confidence, 4),
        confidence_explanation=llm_output.get("confidence_explanation", ""),
        pros=llm_output.get("pros", []),
        cons=llm_output.get("cons", []),
        aspects=aspects,
        negative_summary=llm_output.get("negative_summary", ""),
        total_reviews_analyzed=stats.total_reviews,
        avg_rating=round(stats.avg_rating, 2),
    )
