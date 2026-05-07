"""Embeddings module - converts review texts into vectors and selects
the most representative reviews using cosine similarity (RAG approach).
"""

from __future__ import annotations

import numpy as np
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity

from src.models.review import Review
from src.utils.logger import setup_logger

logger = setup_logger("pras.embeddings")

_MODEL = "text-embedding-3-small"

# How many texts to send in one API call (avoids token limit issues)
_BATCH_SIZE = 100


def embed_reviews(reviews: list[Review], client: OpenAI) -> np.ndarray:
    """Send review texts to OpenAI and get back embedding vectors."""
    if not reviews:
        raise ValueError("Cannot embed an empty review list.")

    # Pull out just the text from each review
    texts = [r.text for r in reviews]
    all_embeddings: list[list[float]] = []

    # Send texts in batches so we don't hit API limits
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        logger.info(
            "Embedding batch %d-%d of %d reviews", start, start + len(batch) - 1, len(texts)
        )

        # Call OpenAI embeddings API for this batch
        response = client.embeddings.create(model=_MODEL, input=batch)

        # Extract the vector from each item in the response
        for item in response.data:
            all_embeddings.append(item.embedding)

    # Convert list of lists into a 2D numpy array
    return np.array(all_embeddings, dtype=np.float32)


def select_top_k(
    reviews: list[Review],
    embeddings: np.ndarray,
    k: int = 20,
) -> list[Review]:
    """Pick the k most representative reviews based on cosine similarity."""
    if len(reviews) == 0:
        return []

    # Don't try to select more reviews than we have
    k = min(k, len(reviews))

    # Compute the centroid - the "average" review vector
    centroid = embeddings.mean(axis=0, keepdims=True)  # shape (1, dim)

    # Measure how close each review is to the centroid
    similarities = cosine_similarity(embeddings, centroid).flatten()  # shape (N,)

    # Sort by similarity descending and take the top k indices
    top_indices = np.argsort(similarities)[::-1][:k]

    logger.info(
        "Selected top-%d reviews out of %d (similarity range %.4f - %.4f)",
        k,
        len(reviews),
        similarities[top_indices[-1]],
        similarities[top_indices[0]],
    )

    # Return the actual Review objects for those indices
    return [reviews[i] for i in top_indices]
