"""LLM analyzer - sends the top-K representative reviews and stats
to GPT and gets back a structured JSON analysis of the product.
"""

from __future__ import annotations

import json

from openai import OpenAI

from src.models.analysis import StatsResult
from src.models.review import Review
from src.utils.logger import setup_logger

logger = setup_logger("pras.llm_analyzer")

_MODEL = "gpt-5-nano"

# Maximum tokens for the LLM response
_MAX_COMPLETION_TOKENS = 4000

# The JSON keys we expect in the LLM response
_EXPECTED_KEYS = [
    "summary_text",
    "pros",
    "cons",
    "aspects",
    "recommendation",
    "confidence_explanation",
    "negative_summary",
]


def _build_system_prompt() -> str:
    """Build the system prompt that tells the LLM how to behave."""
    return (
        "You are a product review analyst. You receive a set of representative "
        "customer reviews and basic statistics about a product.\n\n"
        "Your job is to analyze them and return a structured JSON response.\n\n"
        "You must return ONLY valid JSON with these exact keys:\n"
        '- "summary_text": string, 3-6 sentences summarizing what most reviewers say\n'
        '- "pros": list of strings, main positive points (3-6 items)\n'
        '- "cons": list of strings, main negative points (2-5 items)\n'
        '- "aspects": list of objects, each with "name" (string), '
        '"sentiment" ("positive"/"negative"/"mixed"), "mention_count" (int)\n'
        '- "recommendation": string, a short buy/don\'t buy recommendation\n'
        '- "confidence_explanation": string, why you are confident or not in this analysis\n'
        '- "negative_summary": string, summary of what low-rated reviewers complain about\n\n'
        "Do NOT include any text outside the JSON object."
    )


def _build_user_prompt(reviews: list[Review], stats: StatsResult) -> str:
    """Build the user prompt with the actual review data and stats."""

    # Format each review as a short block with rating and text
    review_lines = []
    for i, r in enumerate(reviews, start=1):
        review_lines.append(f"Review {i} (rating: {r.rating}/5):\n{r.text}")

    reviews_block = "\n\n".join(review_lines)

    # Add the stats summary so the LLM has numeric context
    stats_block = (
        f"Total reviews analyzed: {stats.total_reviews}\n"
        f"Average rating: {stats.avg_rating:.2f}/5\n"
        f"Rating distribution: {stats.rating_distribution}\n"
        f"Negative reviews (1-3 stars): {stats.negative_count}"
    )

    return (
        f"Here are the stats for this product:\n{stats_block}\n\n"
        f"Here are the {len(reviews)} most representative reviews:\n\n"
        f"{reviews_block}\n\n"
        "Please analyze these reviews and return the JSON response."
    )


def _apply_defaults(raw: dict) -> dict:
    """Make sure all expected keys exist in the response, fill in defaults
    for any missing ones so the rest of the pipeline won't break.
    """
    defaults = {
        "summary_text": "Analysis could not be completed.",
        "pros": [],
        "cons": [],
        "aspects": [],
        "recommendation": "Not enough data to recommend.",
        "confidence_explanation": "Low confidence due to incomplete analysis.",
        "negative_summary": "No negative summary available.",
    }

    # Fill in any missing keys with safe defaults
    for key, default_value in defaults.items():
        if key not in raw:
            logger.warning("LLM response missing key '%s', using default", key)
            raw[key] = default_value

    return raw


def analyze_with_llm(
    top_k_reviews: list[Review],
    stats: StatsResult,
    client: OpenAI,
) -> dict:
    """Send top-K reviews and stats to GPT and get structured analysis back.

    Args:
        top_k_reviews: the most representative reviews (from embeddings step).
        stats: computed stats for the full review set.
        client: authenticated OpenAI client.

    Returns:
        dict with keys: summary_text, pros, cons, aspects, recommendation,
        confidence_explanation, negative_summary.
    """
    logger.info("Sending %d reviews to LLM for analysis", len(top_k_reviews))

    # Build the two parts of the prompt
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(top_k_reviews, stats)

    # Call the OpenAI chat API
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=_MAX_COMPLETION_TOKENS,
    )

    # Extract the text content from the response
    raw_text = response.choices[0].message.content or ""
    logger.info("Got LLM response (%d chars)", len(raw_text))

    # Sometimes the LLM wraps JSON in markdown code blocks, strip them
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Remove opening ```json or ``` and closing ```
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    # Parse the JSON string into a Python dict
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON, using all defaults. Raw: %s", raw_text[:300])
        parsed = {}

    # Make sure all required keys exist (fill defaults for missing ones)
    result = _apply_defaults(parsed)

    return result
