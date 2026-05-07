"""Domain dataclasses for analysis and aggregation outputs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AspectInfo:
    """Represents one product aspect extracted from review text.

    Attributes:
        name: Aspect name (for example, "battery life").
        sentiment: Sentiment label: "positive", "negative", or "mixed".
        mention_count: Number of mentions (>= 1).
    """

    name: str
    sentiment: str
    mention_count: int = 1


@dataclass
class StatsResult:
    """Stores aggregate numeric metrics computed from a review batch.

    Attributes:
        avg_rating: Mean star rating on a 1.0-5.0 scale.
        total_reviews: Number of reviews included in the calculation. Unit: reviews. Must be >= 0.
        rating_distribution: Mapping of star value (1-5) to count of reviews at that star.
        negative_count: Number of low-rated reviews (typically 1-3 stars). Unit: reviews. Must be >= 0.
    """

    avg_rating: float
    total_reviews: int
    rating_distribution: dict[int, int]
    negative_count: int


@dataclass
class AnalysisResult:
    """Final analysis payload model for one product.

    Attributes:
        product_title: Product display title shown to end users.
        product_image_url: Public URL to the product image. Empty string means unavailable.
        product_price: Product price as display text (for example, "$49.99", "EUR 39.90").
        amazon_rating: Amazon headline rating on a 0.0-5.0 scale.
        total_review_count: Total reviews reported by Amazon for the product. Unit: reviews. Must be >= 0.
        summary_text: Natural-language summary of review insights (typically 3-6 sentences).
        recommendation: Buy/no-buy style recommendation text for the product.
        confidence_score: Confidence in the generated analysis on a 0.0-1.0 scale.
        confidence_explanation: Short explanation of why the confidence has this value.
        pros: List of positive points extracted from reviews.
        cons: List of negative points extracted from reviews.
        aspects: List of extracted aspect-level insights.
        negative_summary: Text summary of common issues from low-star reviews.
        total_reviews_analyzed: Number of reviews actually analyzed by the pipeline. Unit: reviews. Must be >= 0.
        avg_rating: Mean rating across analyzed reviews on a 1.0-5.0 scale.
        raw_reviews: Raw review text payload captured for debugging/inspection.
        raw_reviews_count: Count of raw reviews captured before cleaning.
    """

    product_title: str
    product_image_url: str = ""
    product_price: str = ""
    amazon_rating: float = 0.0
    total_review_count: int = 0

    # Core analysis (from LLM)
    summary_text: str = ""
    recommendation: str = ""
    confidence_score: float = 0.0
    confidence_explanation: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    aspects: list[AspectInfo] = field(default_factory=list)

    negative_summary: str = ""

    total_reviews_analyzed: int = 0
    avg_rating: float = 0.0
    raw_reviews: list[str] = field(default_factory=list)
    raw_reviews_count: int = 0
