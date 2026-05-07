"""Amazon review scraper - fetches real reviews via ScraperAPI.

ScraperAPI handles proxies, browsers, and captcha solving so we get
the real Amazon HTML without being blocked. We just parse the reviews
with BeautifulSoup.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from src.data.temp_cache import (
    load_product_meta,
    load_raw_reviews,
    save_product_meta,
    save_raw_reviews,
)
from src.models.review import Review
from src.utils.config import get_settings
from src.utils.logger import setup_logger

logger = setup_logger("pras.scraper")

_SCRAPER_API_URL = "https://api.scraperapi.com"
_REVIEWS_PER_PAGE = 10
_PAGE_DELAY = 1.5
_REQUEST_TIMEOUT_SECONDS = 60
_META_FETCH_RETRIES = 2

_RATING_RE = re.compile(r"([0-5](?:[.,][0-9])?)")


def _get_api_key() -> str:
    """Get the ScraperAPI key from settings."""
    return get_settings().scraper_api_key


def _fetch_page(url: str, api_key: str, country_code: str | None = None) -> str | None:
    """Fetch one URL through ScraperAPI."""
    params = {
        "api_key": api_key,
        "url": url,
        "keep_headers": "true",
    }
    if country_code:
        params["country_code"] = country_code
    try:
        resp = requests.get(_SCRAPER_API_URL, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        logger.info("ScraperAPI returned %d bytes", len(resp.text))
        lower = resp.text.lower()
        if "sorry, we just need to make sure you're not a robot" in lower:
            logger.warning("Amazon anti-bot page returned for url=%s", url)
        return resp.text
    except requests.RequestException as exc:
        logger.warning("ScraperAPI request failed: %s", exc)
        return None


def _parse_rating(rating_text: str) -> float:
    """Parse a 1-5 rating from text."""
    match = _RATING_RE.search(rating_text or "")
    if not match:
        return 3.0
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return 3.0


def _parse_helpful_votes(helpful_text: str) -> int:
    """Parse helpful vote count from text."""
    if not helpful_text:
        return 0

    normalized = helpful_text.strip().lower()
    if normalized.startswith("one "):
        return 1

    digits = re.sub(r"[^\d]", "", normalized)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value or "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    normalized = (value or "").strip().replace(",", ".")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _format_price(price_value: float | None, currency: str | None) -> str:
    if price_value is None:
        return ""
    symbol = "$" if (currency or "").upper() == "USD" or not currency else f"{currency} "
    return f"{symbol}{price_value:.2f}"


def _extract_display_price(soup: BeautifulSoup) -> str:
    """Extract the visible 'price to pay' from product page DOM."""
    selectors = (
        "span.priceToPay span.a-offscreen",
        "#corePrice_feature_div span.priceToPay span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.priceToPay span.a-offscreen",
        "#apex_desktop span.priceToPay span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-price span.a-offscreen",
        "#corePrice_feature_div span.a-price span.a-offscreen",
        "#apex_desktop span.a-price span.a-offscreen",
        "span#priceblock_ourprice",
        "span#priceblock_dealprice",
        "#corePrice_feature_div .a-price.aok-align-center .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-price.aok-align-center .a-offscreen",
    )
    for selector in selectors:
        elem = soup.select_one(selector)
        if not elem:
            continue
        text = elem.get_text(" ", strip=True)
        if text:
            return text
    return ""


def _extract_price_from_html_blob(html: str) -> str:
    """Extract price from embedded JSON snippets in HTML."""
    patterns = (
        r'"priceToPay"\s*:\s*\{[^{}]*?"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]{2})?)',
        r'"corePriceDisplay"\s*:\s*\{[^{}]*?"price"\s*:\s*"[$]?([0-9]+(?:\.[0-9]{2})?)"',
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if not match:
            continue
        parsed = _parse_float(match.group(1))
        if parsed is not None:
            return f"${parsed:.2f}"
    return ""


def _extract_review_page_meta(html: str) -> dict[str, str]:
    """Extract aggregate review metadata from a review page."""
    soup = BeautifulSoup(html, "html.parser")
    meta: dict[str, str] = {}

    info_elem = soup.select_one("div[data-hook='cr-filter-info-review-rating-count']")
    info_text = info_elem.get_text(" ", strip=True) if info_elem else ""
    if info_text:
        # Example: "134,907 global ratings | 8,532 global reviews"
        count_match = re.search(r"([\d,]+)\s+global\s+ratings", info_text, re.IGNORECASE)
        if count_match:
            parsed = _parse_int(count_match.group(1))
            if parsed is not None:
                meta["total_review_count"] = str(parsed)

    return meta


def _extract_meta_from_json_ld(soup: BeautifulSoup) -> dict[str, str]:
    """Extract product metadata from JSON-LD blocks if present."""
    meta: dict[str, str] = {}
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue

            type_value = item.get("@type")
            type_list = type_value if isinstance(type_value, list) else [type_value]
            is_product = any(str(t).lower() == "product" for t in type_list if t)
            if not is_product:
                continue

            name = item.get("name")
            if isinstance(name, str) and name.strip():
                meta["title"] = name.strip()

            image = item.get("image")
            if isinstance(image, str) and image.strip():
                meta["image_url"] = image.strip()
            elif isinstance(image, list) and image:
                first = image[0]
                if isinstance(first, str) and first.strip():
                    meta["image_url"] = first.strip()

            aggregate = item.get("aggregateRating")
            if isinstance(aggregate, dict):
                rating_value = _parse_float(str(aggregate.get("ratingValue", "")))
                rating_count = _parse_int(str(aggregate.get("ratingCount", "")))
                if rating_value is not None:
                    meta["amazon_rating"] = f"{rating_value:.1f}"
                if rating_count is not None:
                    meta["total_review_count"] = str(rating_count)

            offers = item.get("offers")
            offer = None
            if isinstance(offers, dict):
                offer = offers
            elif isinstance(offers, list) and offers and isinstance(offers[0], dict):
                offer = offers[0]
            if isinstance(offer, dict):
                price_value = _parse_float(str(offer.get("price", "")))
                price_currency = str(offer.get("priceCurrency", "")).strip()
                formatted = _format_price(price_value, price_currency)
                if formatted:
                    meta["price"] = formatted
    return meta


def _extract_review_text(container: BeautifulSoup) -> str:
    """Extract review text from a review container."""
    selectors = (
        "span[data-hook='review-body'] span",
        "span[data-hook='review-body']",
        "span[data-hook='review-collapsed']",
        "div[data-hook='review-collapsed']",
        "span.review-text-content span",
    )
    for selector in selectors:
        elem = container.select_one(selector)
        if not elem:
            continue
        text = elem.get_text(" ", strip=True)
        if len(text) >= 10:
            return text
    # Fallback for variant layouts where data-hook selectors are missing.
    raw = container.get_text(" ", strip=True)
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) >= 40:
        return raw[:4000]
    return ""


def _parse_reviews_from_html(html: str) -> list[Review]:
    """Parse review data from an Amazon review page HTML response."""
    soup = BeautifulSoup(html, "html.parser")
    reviews: list[Review] = []

    containers = soup.select("div[data-hook='review'], div[id^='customer_review-']")
    logger.info("Found %d review containers in HTML", len(containers))

    for container in containers:
        text = _extract_review_text(container)
        if not text:
            continue

        rating_elem = container.select_one("i[data-hook='review-star-rating'] span.a-icon-alt")
        if not rating_elem:
            rating_elem = container.select_one("i[data-hook='review-star-rating']")
        if not rating_elem:
            rating_elem = container.select_one("i[data-hook='cmps-review-star-rating']")
        rating = _parse_rating(rating_elem.get_text(" ", strip=True) if rating_elem else "")

        date_str = ""
        date_elem = container.select_one("span[data-hook='review-date']")
        if date_elem:
            date_str = date_elem.get_text(" ", strip=True)

        helpful = 0
        helpful_elem = container.select_one("span[data-hook='helpful-vote-statement']")
        if helpful_elem:
            helpful = _parse_helpful_votes(helpful_elem.get_text(" ", strip=True))

        verified = container.select_one("span[data-hook='avp-badge']") is not None

        reviews.append(
            Review(
                text=text,
                rating=rating,
                date=date_str,
                helpful_votes=helpful,
                verified_purchase=verified,
            )
        )

    return reviews


def _normalize_review_text(text: str) -> str:
    """Normalize review text for deduplication."""
    return text.strip().lower()


def _count_new_unique(candidate_reviews: list[Review], seen_texts: set[str]) -> int:
    """Count how many reviews are new against current seen set."""
    return sum(
        1 for review in candidate_reviews if _normalize_review_text(review.text) not in seen_texts
    )


def _build_review_page_urls(asin: str, page_num: int) -> list[str]:
    """Build fallback URL variants for a review page."""
    query = urlencode(
        {
            "reviewerType": "all_reviews",
            "sortBy": "recent",
            "pageNumber": page_num,
        }
    )
    return [
        (
            f"https://www.amazon.com/dp/{asin}/ref=cm_cr_arp_d_viewopt_srt"
            f"?reviewerType=all_reviews&pageNumber={page_num}&sortBy=recent"
        ),
        f"https://www.amazon.com/dp/{asin}?{query}",
        f"https://www.amazon.com/product-reviews/{asin}/?{query}",
        f"https://www.amazon.com/product-reviews/{asin}/ref=cm_cr_getr_d_paging_btm_next_{page_num}?{query}",
    ]


def scrape_product_meta(asin: str) -> dict[str, str]:
    """Scrape product title/image/price/rating/count from product page."""
    cached = load_product_meta(asin)
    if cached is not None:
        return cached

    api_key = _get_api_key()
    if not api_key:
        return {}

    url = f"https://www.amazon.com/dp/{asin}"
    logger.info("Fetching product meta: %s", url)

    html = None
    for attempt in range(1, _META_FETCH_RETRIES + 1):
        html = _fetch_page(url, api_key, country_code="us")
        if html:
            break
        logger.warning(
            "Product meta fetch failed (attempt %d/%d) for %s", attempt, _META_FETCH_RETRIES, asin
        )
        if attempt < _META_FETCH_RETRIES:
            time.sleep(1.0)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    meta: dict[str, str] = {}

    meta.update(_extract_meta_from_json_ld(soup))

    title_elem = soup.find("span", {"id": "productTitle"})
    if title_elem:
        meta["title"] = title_elem.get_text(strip=True)

    img_elem = soup.find("img", {"id": "landingImage"})
    if img_elem and img_elem.get("src"):
        meta["image_url"] = img_elem["src"]

    display_price = _extract_display_price(soup)
    if display_price:
        meta["price"] = display_price
    else:
        blob_price = _extract_price_from_html_blob(html)
        if blob_price:
            meta["price"] = blob_price

    if "amazon_rating" not in meta:
        rating_anchor = soup.find("span", {"id": "acrPopover"})
        if rating_anchor and rating_anchor.get("title"):
            parsed_rating = _parse_rating(rating_anchor.get("title", ""))
            if parsed_rating > 0:
                meta["amazon_rating"] = f"{parsed_rating:.1f}"

    if "total_review_count" not in meta:
        count_elem = soup.find("span", {"id": "acrCustomerReviewText"})
        if count_elem:
            parsed_count = _parse_int(count_elem.get_text(" ", strip=True))
            if parsed_count is not None:
                meta["total_review_count"] = str(parsed_count)

    if "price" in meta:
        logger.info("Product price extracted: %s", meta["price"])
    if "amazon_rating" in meta:
        logger.info("Amazon rating extracted: %s", meta["amazon_rating"])
    if "total_review_count" in meta:
        logger.info("Amazon review count extracted: %s", meta["total_review_count"])

    if "price" not in meta:
        price_elem = soup.find("span", {"class": "a-price-whole"})
        if price_elem:
            fraction = soup.find("span", {"class": "a-price-fraction"})
            price_text = price_elem.get_text(strip=True).rstrip(".")
            if fraction:
                price_text += "." + fraction.get_text(strip=True)
            meta["price"] = f"${price_text}"

    save_product_meta(asin, meta)
    logger.info("Product meta: %s", meta.get("title", "no title"))
    return meta


def scrape_reviews_with_meta(
    asin: str,
    max_reviews: int = 100,
) -> tuple[list[Review], dict[str, str]]:
    """Scrape unique reviews and return optional aggregate metadata."""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("No SCRAPER_API_KEY, cannot scrape")
        return [], {}

    max_reviews = max(25, min(max_reviews, 250))
    cached = load_raw_reviews(asin, max_reviews)
    if cached is not None:
        return cached

    unique_reviews: list[Review] = []
    seen_texts: set[str] = set()
    aggregate_meta: dict[str, str] = {}
    pages_needed = (max_reviews + _REVIEWS_PER_PAGE - 1) // _REVIEWS_PER_PAGE
    consecutive_empty_pages = 0

    for page_num in range(1, pages_needed + 1):
        logger.info("Scraping page %d for ASIN %s", page_num, asin)
        page_reviews: list[Review] = []
        best_candidate_new = -1
        best_candidate_total = 0
        best_candidate_meta: dict[str, str] = {}
        for candidate_url in _build_review_page_urls(asin, page_num):
            html = _fetch_page(candidate_url, api_key)
            if not html:
                continue

            candidate_reviews = _parse_reviews_from_html(html)
            if not candidate_reviews:
                continue

            candidate_meta = _extract_review_page_meta(html)
            new_unique = _count_new_unique(candidate_reviews, seen_texts)

            logger.info(
                "Candidate page parsed: url=%s reviews=%d new_unique=%d",
                candidate_url,
                len(candidate_reviews),
                new_unique,
            )

            if new_unique > best_candidate_new:
                best_candidate_new = new_unique
                best_candidate_total = len(candidate_reviews)
                page_reviews = candidate_reviews
                best_candidate_meta = candidate_meta

        if page_num == 1 and best_candidate_meta:
            aggregate_meta.update(best_candidate_meta)

        if not page_reviews:
            consecutive_empty_pages += 1
            logger.info(
                "No reviews on page %d (consecutive empty pages: %d)",
                page_num,
                consecutive_empty_pages,
            )
            if consecutive_empty_pages >= 2:
                logger.info("Stopping after repeated empty pages")
                break
            continue

        new_on_page = 0
        for review in page_reviews:
            normalized = _normalize_review_text(review.text)
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)
            unique_reviews.append(review)
            new_on_page += 1

        logger.info(
            "Total unique reviews: %d after page %d (new on page: %d)",
            len(unique_reviews),
            page_num,
            new_on_page,
        )
        if new_on_page > 0:
            consecutive_empty_pages = 0
        if best_candidate_total > 0:
            logger.info(
                "Accepted candidate for page %d: parsed=%d, new_unique=%d",
                page_num,
                best_candidate_total,
                new_on_page,
            )
        if new_on_page == 0:
            consecutive_empty_pages += 1
            logger.info(
                "Page %d added no new unique reviews (consecutive empty pages: %d)",
                page_num,
                consecutive_empty_pages,
            )
            if consecutive_empty_pages >= 2:
                logger.info("Stopping after repeated duplicate-only pages")
                break
            continue

        if len(unique_reviews) >= max_reviews:
            break

        time.sleep(_PAGE_DELAY)

    result = unique_reviews[:max_reviews]
    logger.info("Scraping done: %d unique reviews for ASIN %s", len(result), asin)
    save_raw_reviews(asin, max_reviews, result, aggregate_meta)
    return result, aggregate_meta
