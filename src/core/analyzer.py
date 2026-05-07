"""Core pipeline orchestrator — chains every processing step into a single
``analyze_product`` call that returns a fully populated ``AnalysisResult``.
"""

from __future__ import annotations

from openai import OpenAI

from src.analysis.confidence_scorer import calculate_confidence
from src.analysis.embeddings import embed_reviews, select_top_k
from src.analysis.llm_analyzer import analyze_with_llm
from src.data.mock_reviews import PRODUCT_META, get_mock_reviews
from src.models.analysis import AnalysisResult, AspectInfo, StatsResult
from src.processing.review_cleaner import clean_reviews_pipeline
from src.processing.stats_calculator import calculate_stats
from src.utils.config import get_settings
from src.utils.logger import setup_logger
from src.utils.url_parser import extract_asin

logger = setup_logger("pras.analyzer")

_TOP_K = 20


def analyze_product(url: str, max_reviews: int = 200) -> AnalysisResult:
    """Run the full analysis pipeline for an Amazon product URL.

    Args:
        url: Amazon product page URL containing a valid ASIN.
        max_reviews: How many mock reviews to fetch (clamped 100-500).

    Returns:
        Fully populated AnalysisResult ready for JSON serialization.

    Raises:
        AmazonURLError: If the URL is not a valid Amazon URL.
        InvalidASINError: If no 10-character ASIN can be extracted.
    """
    # 1. Extract ASIN from URL
    asin = extract_asin(url)
    logger.info("Pipeline start: asin=%s max_reviews=%d", asin, max_reviews)

    # 2. Fetch reviews (mock data for now)
    reviews = get_mock_reviews(asin, max_reviews)
    logger.info("Fetched %d raw reviews", len(reviews))

    # 3. Clean and filter
    cleaned = clean_reviews_pipeline(reviews)
    logger.info("Cleaned down to %d reviews", len(cleaned))

    # 4. Compute stats on cleaned set
    stats = calculate_stats(cleaned)

    # 5. Confidence score
    confidence = calculate_confidence(cleaned)

    # 6-7. Embed and select top-K, then send to LLM
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    embeddings = embed_reviews(cleaned, client)
    top_k = select_top_k(cleaned, embeddings, k=_TOP_K)
    logger.info("Selected %d representative reviews for LLM", len(top_k))

    llm_output = analyze_with_llm(top_k, stats, client)

    # 8. Assemble final result
    return _assemble_result(llm_output, stats, confidence, asin)


def _assemble_result(
    llm_output: dict,
    stats: StatsResult,
    confidence: float,
    asin: str,
) -> AnalysisResult:
    """Map LLM structured output + computed stats + confidence into a
    complete AnalysisResult with safe fallbacks for missing fields.
    """
    meta = PRODUCT_META.get(asin, {})

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

    return AnalysisResult(
        product_title=meta.get("title", f"Product {asin}"),
        product_image_url=meta.get("image_url", ""),
        product_price=meta.get("price", ""),
        amazon_rating=round(stats.avg_rating, 1),
        total_review_count=stats.total_reviews,
        summary_text=llm_output.get("summary_text", ""),
        recommendation=recommendation,
        confidence_score=round(confidence, 4),
        confidence_explanation=llm_output.get("confidence_explanation", ""),
        pros=llm_output.get("pros", []),
        cons=llm_output.get("cons", []),
        aspects=aspects,
        rating_distribution=stats.rating_distribution,
        negative_summary=llm_output.get("negative_summary", ""),
        total_reviews_analyzed=stats.total_reviews,
        avg_rating=round(stats.avg_rating, 2),
    )
