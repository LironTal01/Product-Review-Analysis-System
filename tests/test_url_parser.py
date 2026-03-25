"""Tests for Amazon product URL parsing (ASIN extraction and domain checks)."""

import pytest

from src.utils.url_parser import (
    AmazonURLError,
    InvalidASINError,
    extract_asin,
    validate_amazon_url,
)

pytestmark = pytest.mark.unit

# Realistic listing URL: title slug, /ref/, and query string; ASIN stays in the /dp/ segment.
LONG_LISTING_URL = (
    "https://www.amazon.com/Apple-Bluetooth-Headphones-Personalized-Resistant/dp/"
    "B0DGW54P27/ref=sr_1_3?keywords=airpods&qid=1774368273&sr=8-3"
)


@pytest.mark.parametrize(
    ("url", "expected_asin"),
    [
        # Typical shapes: bare /dp/, /dp/ after product slug, /gp/product/, query params, http.
        ("https://www.amazon.com/dp/B08N5WRWNW", "B08N5WRWNW"),
        (
            "https://www.amazon.com/Some-Product/dp/B012345678/ref=sr_1_1",
            "B012345678",
        ),
        ("https://www.amazon.com/gp/product/B087QZXR2L", "B087QZXR2L"),
        # Path segments before /gp/product/ should not matter.
        ("https://www.amazon.com/some/path/gp/product/B087QZXR2L", "B087QZXR2L"),
        (
            "https://www.amazon.com/dp/B08N5WRWNW?ref=x&keywords=test",
            "B08N5WRWNW",
        ),
        ("http://www.amazon.com/dp/B08N5WRWNW", "B08N5WRWNW"),
        # Edges: another Amazon TLD, lowercase ASIN in path, long listing-style URL.
        ("https://www.amazon.co.uk/dp/B08N5WRWNW", "B08N5WRWNW"),
        ("https://www.amazon.com/dp/b08n5wrwnw", "B08N5WRWNW"),
        (LONG_LISTING_URL, "B0DGW54P27"),
        # No 'www' and uppercase host should still be accepted.
        ("https://amazon.com/dp/B08N5WRWNW", "B08N5WRWNW"),
        ("https://WWW.AMAZON.COM/dp/B08N5WRWNW", "B08N5WRWNW"),
        # ASIN is 10 alphanumerics; it does not have to start with 'B'.
        ("https://www.amazon.com/dp/A08N5WRWNW", "A08N5WRWNW"),
    ],
)
def test_extract_asin_returns_expected(url, expected_asin):
    """extract_asin must return the 10-character ASIN for each accepted URL shape."""
    assert extract_asin(url) == expected_asin


@pytest.mark.parametrize(
    ("url", "expected_exc"),
    [
        # Garbage URL, non-Amazon host, empty string, page without /dp/ ASIN, invalid ASIN token.
        ("not-a-url", AmazonURLError),
        ("https://www.ebay.com/dp/B08N5WRWNW", AmazonURLError),
        ("", AmazonURLError),
        ("https://www.amazon.com/bestsellers", InvalidASINError),
        ("https://www.amazon.com/dp/B08N5WRW", InvalidASINError),
        # Non-alphanumeric tokens are not valid ASINs.
        ("https://www.amazon.com/dp/B08N5WRW-W", InvalidASINError),
    ],
)
def test_extract_asin_raises(url, expected_exc):
    """extract_asin must raise the right error class for bad or unusable URLs."""
    with pytest.raises(expected_exc):
        extract_asin(url)


def test_extract_asin_none_raises_typeerror():
    """None is not a valid input type for extract_asin."""
    with pytest.raises(TypeError):
        extract_asin(None)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.com/dp/B08N5WRWNW",
        "https://www.amazon.co.uk/dp/B08N5WRWNW",
        "https://amazon.com/dp/B08N5WRWNW",
        "https://WWW.AMAZON.COM/dp/B08N5WRWNW",
    ],
)
def test_validate_amazon_url_accepts(url):
    """Known Amazon hosts over http(s) are accepted."""
    assert validate_amazon_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ebay.com/item/1",
        "ftp://amazon.com/dp/B08N5WRWNW",
        "",
    ],
)
def test_validate_amazon_url_rejects(url):
    """Wrong site, unsupported scheme, or empty input is rejected."""
    assert validate_amazon_url(url) is False
