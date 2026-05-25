"""LLM analyzer - sends the top-K representative reviews and stats
to GPT and gets back a structured JSON analysis of the product.
"""

from __future__ import annotations

import json

from openai import OpenAI

from src.models.analysis import StatsResult
from src.models.review import Review
from src.utils.config import get_settings
from src.utils.logger import setup_logger

logger = setup_logger("pras.llm_analyzer")

_DEFAULT_MODEL = "gpt-5-nano"

# Maximum tokens for the LLM response
_MAX_OUTPUT_TOKENS = 1800

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
        f"Negative reviews (1-3 stars): {stats.negative_count}"
    )

    return (
        f"Here are the stats for this product:\n{stats_block}\n\n"
        f"Here are the {len(reviews)} most representative reviews:\n\n"
        f"{reviews_block}\n\n"
        "Please analyze these reviews and return the JSON response."
    )


def _resolve_model_name() -> str:
    """Resolve the configured LLM model with a GPT-5+ safety fallback."""
    configured = (get_settings().openai_llm_model or "").strip()
    if not configured:
        return _DEFAULT_MODEL

    if not configured.lower().startswith("gpt-5"):
        logger.warning(
            "Configured LLM model '%s' is not GPT-5+, using '%s' instead",
            configured,
            _DEFAULT_MODEL,
        )
        return _DEFAULT_MODEL
    return configured


def _extract_response_text(response: object) -> str:
    """Extract plain text from OpenAI Responses API object."""
    output_text = getattr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks: list[str] = []
    output_items = getattr(response, "output", []) or []
    for item in output_items:
        content_items = getattr(item, "content", []) or []
        for content in content_items:
            text = getattr(content, "text", "")
            if isinstance(text, str) and text:
                chunks.append(text)

    return "\n".join(chunks).strip()


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


def analyze_with_llm(top_k_reviews: list[Review], stats: StatsResult, client: OpenAI) -> dict:
    """Send top-K reviews and stats to GPT and get structured analysis back.
    This function will send the top-K reviews and stats to the LLM to get the analysis.
    Finally, it will return the analysis.
    """
    logger.info("Sending %d reviews to LLM for analysis", len(top_k_reviews))

    # Build the two parts of the prompt
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(top_k_reviews, stats)
    model = _resolve_model_name()

    # Try to get the analysis from the LLM 3 times
    raw_text = ""
    for attempt in range(3):
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                ],
                reasoning={"effort": "low"},
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:
            logger.warning("LLM request failed (attempt %d/3): %s", attempt + 1, exc)
            continue

        raw_text = _extract_response_text(response)
        if raw_text.strip():
            break
        logger.warning("LLM returned empty response (attempt %d/3), retrying", attempt + 1)

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
        logger.error("LLM returned invalid JSON, using all defaults.")
        logger.debug("Raw LLM response (truncated): %s", raw_text[:300])
        parsed = {}

    # Make sure all required keys exist (fill defaults for missing ones)
    result = _apply_defaults(parsed)

    return result
