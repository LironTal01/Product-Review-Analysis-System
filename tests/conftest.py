"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_amazon_urls():
    """Sample Amazon URLs for testing."""
    return {
        "us_full": "https://www.amazon.com/dp/B08N5WRWNW",
        "us_with_title": "https://www.amazon.com/Sony-WH-1000XM4-Canceling-Headphones/dp/B0863TXGM3",
        "uk": "https://www.amazon.co.uk/dp/B08N5WRWNW",
        "de": "https://www.amazon.de/dp/B08N5WRWNW",
        "with_params": "https://www.amazon.com/dp/B08N5WRWNW?ref=something&tag=abc",
        "short": "https://amzn.to/3abc123",
        "invalid": "https://google.com/search?q=product",
        "asin_only": "B08N5WRWNW",
    }


@pytest.fixture
def sample_reviews():
    """Sample reviews for testing."""
    return [
        {
            "id": "R1",
            "text": "Great battery life! The headphones last for days. Sound quality is amazing.",
            "rating": 5,
            "date": "2024-01-15",
        },
        {
            "id": "R2",
            "text": "Comfortable to wear but the noise cancellation could be better.",
            "rating": 4,
            "date": "2024-01-10",
        },
        {
            "id": "R3",
            "text": "Terrible product. Broke after one week. Waste of money.",
            "rating": 1,
            "date": "2024-01-05",
        },
    ]
