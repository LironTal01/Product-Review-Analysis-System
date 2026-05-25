"""Amazon review scraper - fetches real reviews via ScraperAPI.

ScraperAPI handles proxies, browsers, and captcha solving so we get
the real Amazon HTML without being blocked. We just parse the reviews
with BeautifulSoup.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from src.db.redis_cache import get_cached_raw_reviews, set_cached_raw_reviews
from src.models.review import Review
from src.utils.config import get_settings
from src.utils.logger import setup_logger

logger = setup_logger("pras.scraper")

_SCRAPER_API_URL = "https://api.scraperapi.com"
_REVIEWS_PER_PAGE = 15
_PAGE_DELAY = 0.5
_REQUEST_TIMEOUT_SECONDS = 60
_META_FETCH_RETRIES = 3
_MAX_REVIEW_PAGES = 25
_MAX_CONSECUTIVE_STALE_PAGES = 3
_ROUTE_PROFILES: list[tuple[str, str | None]] = [
    ("helpful", None),
    ("recent", None),
    ("recent", "critical"),
    ("recent", "positive"),
]

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
        # Bypass HTTP(S)_PROXY from the environment: many proxies block tunneling to third‑party APIs.
        resp = requests.get(
            _SCRAPER_API_URL,
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            proxies={"http": None, "https": None},
        )
        resp.raise_for_status()
        logger.debug("ScraperAPI returned %d bytes", len(resp.text))
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


def _extract_display_price(soup: BeautifulSoup) -> str:
    """Extract visible product price from common Amazon selectors."""
    selectors = (
        "span.priceToPay span.a-offscreen",
        "span#priceblock_ourprice",
        "span#priceblock_dealprice",
    )
    for selector in selectors:
        elem = soup.select_one(selector)
        if not elem:
            continue
        text = elem.get_text(" ", strip=True)
        if text:
            return text
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
    logger.debug("Found %d review containers in HTML", len(containers))

    for container in containers:
        text = _extract_review_text(container)
        if not text:
            continue
        review_id = (container.get("id") or container.get("data-review-id") or "").strip()
        if review_id.startswith("customer_review-"):
            review_id = review_id.replace("customer_review-", "", 1)

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
                review_id=review_id,
            )
        )

    return reviews


def _normalize_review_text(text: str) -> str:
    """Normalize review text for deduplication."""
    return text.strip().lower()


def _review_dedupe_key(review: Review) -> str:
    """Merge duplicates using body + rating + date.

    Amazon markup IDs are unreliable across sorts/routes (missing, reused, or unstable),
    which made ID-first dedupe stop pagination early with far fewer rows than expected.
    """
    norm = _normalize_review_text(review.text)
    date_part = (review.date or "").strip()
    return f"text:{norm}|rating:{review.rating}|date:{date_part}"


def _count_new_unique(candidate_reviews: list[Review], seen_keys: set[str]) -> int:
    """Count how many candidate reviews are new against the seen set."""
    return sum(1 for review in candidate_reviews if _review_dedupe_key(review) not in seen_keys)


def _build_review_page_urls(
    asin: str, page_num: int, sort_by: str, filter_by_star: str | None = None
) -> list[str]:
    """Build fallback URLs for one page and one route profile."""
    params: dict[str, str | int] = {
        "reviewerType": "all_reviews",
        "sortBy": sort_by,
        "pageNumber": page_num,
    }
    if filter_by_star:
        params["filterByStar"] = filter_by_star
    query = urlencode(params)
    dp_params = f"reviewerType=all_reviews&pageNumber={page_num}&sortBy={sort_by}"
    if filter_by_star:
        dp_params += f"&filterByStar={filter_by_star}"
    # Keep only dp-based variants: in practice they are the most stable with ScraperAPI.
    return [
        f"https://www.amazon.com/dp/{asin}/ref=cm_cr_arp_d_viewopt_srt?{dp_params}",
        f"https://www.amazon.com/dp/{asin}?{query}",
    ]


def scrape_product_meta(asin: str) -> dict[str, str]:
    """Scrape product title/image/price/rating/count from product page."""
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

    title_elem = soup.find("span", {"id": "productTitle"})
    if title_elem:
        meta["title"] = title_elem.get_text(strip=True)

    img_elem = soup.find("img", {"id": "landingImage"})
    if img_elem and img_elem.get("src"):
        meta["image_url"] = img_elem["src"]

    display_price = _extract_display_price(soup)
    if display_price:
        meta["price"] = display_price

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
        logger.debug("Product price extracted: %s", meta["price"])
    if "amazon_rating" in meta:
        logger.debug("Amazon rating extracted: %s", meta["amazon_rating"])
    if "total_review_count" in meta:
        logger.debug("Amazon review count extracted: %s", meta["total_review_count"])
    logger.debug("Product meta: %s", meta.get("title", "no title"))
    return meta


def scrape_reviews_with_meta(
    asin: str, max_reviews: int = 250
) -> tuple[list[Review], dict[str, str]]:
    """Scrape unique reviews and return optional aggregate metadata."""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("No SCRAPER_API_KEY, cannot scrape")
        return [], {}

    max_reviews = max(25, min(max_reviews, 250))
    # Read-through Redis raw cache keyed by ``(asin, max_reviews)``.
    cached = get_cached_raw_reviews(asin, max_reviews)
    if cached is not None:
        return cached

    unique_reviews: list[Review] = []
    seen_keys: set[str] = set()
    aggregate_meta: dict[str, str] = {}
    pages_needed = (max_reviews + _REVIEWS_PER_PAGE - 1) // _REVIEWS_PER_PAGE
    # Keep extra headroom for sparse pages, but avoid very long requests in production.
    pages_to_try = min(_MAX_REVIEW_PAGES, pages_needed + 3)
    consecutive_empty_pages = 0

    for page_num in range(1, pages_to_try + 1):
        logger.debug("Scraping page %d for ASIN %s", page_num, asin)
        page_reviews: list[Review] = []
        page_meta: dict[str, str] = {}
        best_new_unique = -1
        best_reviews_count = 0

        # Route priority: helpful -> recent -> star filters.
        # Use every profile on each page so stale pagination on one sort still yields rows from others.
        # Page 1 probes all route profiles to quickly discover a rich path.
        # Later pages use only the two most stable routes to bound request time.
        route_profiles = _ROUTE_PROFILES if page_num == 1 else _ROUTE_PROFILES[:2]
        for sort_by, filter_by_star in route_profiles:
            for page_url in _build_review_page_urls(asin, page_num, sort_by, filter_by_star):
                html = _fetch_page(page_url, api_key, country_code="us")
                if not html:
                    continue

                candidate_reviews = _parse_reviews_from_html(html)
                if not candidate_reviews:
                    continue

                candidate_meta = _extract_review_page_meta(html)
                new_unique = _count_new_unique(candidate_reviews, seen_keys)
                logger.debug(
                    "Candidate page parsed: route=%s/%s url=%s reviews=%d new_unique=%d",
                    sort_by,
                    filter_by_star or "all",
                    page_url,
                    len(candidate_reviews),
                    new_unique,
                )

                if new_unique > best_new_unique:
                    best_new_unique = new_unique
                    best_reviews_count = len(candidate_reviews)
                    page_reviews = candidate_reviews
                    page_meta = candidate_meta
                    # Good enough for this page, avoid extra slow route probes.
                    if best_new_unique >= _REVIEWS_PER_PAGE:
                        break
            if best_new_unique >= _REVIEWS_PER_PAGE:
                break

        if page_num == 1 and page_meta:
            aggregate_meta.update(page_meta)

        logger.debug(
            "Selected page %d candidate: reviews=%d",
            page_num,
            best_reviews_count,
        )

        if not page_reviews:
            consecutive_empty_pages += 1
            logger.debug(
                "No reviews on page %d (consecutive empty pages: %d)",
                page_num,
                consecutive_empty_pages,
            )
            if consecutive_empty_pages >= _MAX_CONSECUTIVE_STALE_PAGES:
                logger.debug("Stopping after repeated empty pages")
                break
            continue

        new_on_page = 0
        for review in page_reviews:
            dedupe_key = _review_dedupe_key(review)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            unique_reviews.append(review)
            new_on_page += 1

        logger.debug(
            "Total unique reviews: %d after page %d (new on page: %d)",
            len(unique_reviews),
            page_num,
            new_on_page,
        )
        if new_on_page > 0:
            consecutive_empty_pages = 0
        if new_on_page == 0:
            consecutive_empty_pages += 1
            logger.debug(
                "Page %d added no new unique reviews (consecutive empty pages: %d)",
                page_num,
                consecutive_empty_pages,
            )
            if consecutive_empty_pages >= _MAX_CONSECUTIVE_STALE_PAGES:
                logger.debug("Stopping after repeated duplicate-only pages")
                break
            continue

        if len(unique_reviews) >= max_reviews:
            break

        time.sleep(_PAGE_DELAY)

    result = unique_reviews[:max_reviews]
    logger.info("Scraping done: %d unique reviews for ASIN %s", len(result), asin)
    # Persist raw payload to Redis so repeated calls can skip scraping.
    set_cached_raw_reviews(asin, max_reviews, result, aggregate_meta)
    return result, aggregate_meta
