"""Parse Amazon product URLs and extract the ASIN (10-character product id).
Supports common path forms (/dp/, /gp/product/) and a fixed set of Amazon hostnames.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


class AmazonURLError(ValueError):
    """URL is missing, not a string, not parseable, or not an allowed Amazon host."""


class InvalidASINError(ValueError):
    """No ASIN in the path, or token fails ASIN format rules."""


# Hosts we treat as Amazon (no wildcard — avoids lookalike domains).
AMAZON_DOMAINS = {
    "amazon.com",
    "amazon.co.uk",
    "amazon.de",
    "amazon.fr",
    "amazon.ca",
    "amazon.com.au",
    "amazon.it",
    "amazon.es",
    "amazon.co.jp",
    "amazon.in",
    "smile.amazon.com",
}

# ASIN format: 10 alphanumeric characters (case-insensitive input)
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

# Grab candidate token from path; final validity is ASIN_PATTERN.
DP_PATTERN = re.compile(r"/dp/([A-Z0-9@_-]{8,12})(?:/|$|\?|#)", re.IGNORECASE)
GP_PRODUCT_PATTERN = re.compile(r"/gp/product/([A-Z0-9@_-]{8,12})(?:/|$|\?|#)", re.IGNORECASE)


def validate_amazon_url(url: str) -> bool:
    """Return True if url uses http(s) and host is in AMAZON_DOMAINS."""
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if not url:
        return False

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False

        # Check protocol (only http/https allowed)
        if parsed.scheme.lower() not in ("http", "https"):
            return False

        # Check if domain is Amazon (case-insensitive)
        domain = parsed.netloc.lower()
        # Remove 'www.' prefix if present
        if domain.startswith("www."):
            domain = domain[4:]

        return domain in AMAZON_DOMAINS

    except Exception:
        return False


def _validate_asin_format(asin: str) -> bool:
    """True if asin matches 10 alphanumerics (case-insensitive input)."""
    if not asin or not isinstance(asin, str):
        return False

    return bool(ASIN_PATTERN.match(asin.upper()))


def _extract_asin_from_path(path: str) -> str | None:
    """Pull ASIN candidate from path: try /dp/ first, then /gp/product/."""
    match = DP_PATTERN.search(path)
    if match:
        return match.group(1).upper()

    # Try /gp/product/ pattern
    match = GP_PRODUCT_PATTERN.search(path)
    if match:
        return match.group(1).upper()

    return None


def extract_asin(url: str) -> str:
    """Return ASIN string or raise AmazonURLError / InvalidASINError / TypeError."""
    if url is None:
        raise TypeError("URL cannot be None")

    if not isinstance(url, str):
        raise AmazonURLError("URL must be a string")

    url = url.strip()
    if not url:
        raise AmazonURLError("URL cannot be empty")

    # Validate Amazon domain
    if not validate_amazon_url(url):
        raise AmazonURLError(f"Invalid Amazon URL: {url}")

    # Parse URL
    try:
        parsed = urlparse(url)
        path = parsed.path
    except Exception as e:
        raise AmazonURLError(f"Failed to parse URL: {url}") from e

    # Extract ASIN from path
    asin = _extract_asin_from_path(path)

    if not asin:
        raise InvalidASINError(f"No valid ASIN found in URL: {url}")

    # Validate ASIN format
    if not _validate_asin_format(asin):
        raise InvalidASINError(f"Invalid ASIN format: {asin}")

    return asin


def extract_asins_batch(urls: list[str]) -> dict[str, str]:
    """Map each URL to its ASIN; skip entries that cannot be parsed."""
    results = {}
    for url in urls:
        try:
            results[url] = extract_asin(url)
        except (AmazonURLError, InvalidASINError, TypeError):
            # Skip invalid URLs
            continue
    return results
