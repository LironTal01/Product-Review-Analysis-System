"""Mock review data source for development and testing.

Provides realistic Amazon-style reviews for three product ASINs so the
pipeline can run end-to-end without network access.
"""

from __future__ import annotations

import random

from src.models.review import Review

_MIN_REVIEWS = 25
_MAX_REVIEWS = 250

# Each tuple: (text, rating, date, helpful_votes, verified_purchase)

_HEADPHONES_ASIN = "B08N5WRWNW"
_HEADPHONES: list[tuple[str, float, str, int, bool]] = [
    (
        "Amazing noise cancellation — can't hear anything on the subway.",
        5.0,
        "2025-11-02",
        34,
        True,
    ),
    (
        "Sound quality is excellent for the price. Bass is deep and clear.",
        5.0,
        "2025-10-18",
        22,
        True,
    ),
    ("Comfortable for hours of use. Padding is soft and breathable.", 5.0, "2025-09-30", 18, True),
    ("Battery lasts over 30 hours easily. Very impressed.", 5.0, "2025-10-05", 15, True),
    (
        "Bluetooth pairing is instant. Works great with my phone and laptop.",
        5.0,
        "2025-08-22",
        11,
        True,
    ),
    ("Solid build quality, feels premium despite the mid-range price.", 4.0, "2025-11-10", 9, True),
    ("Good headphones overall, but the app is clunky and slow.", 4.0, "2025-10-25", 7, True),
    ("ANC is very good but not quite Bose-level. Still worth it.", 4.0, "2025-09-14", 13, True),
    (
        "Nice sound, though the treble can be slightly harsh at high volume.",
        4.0,
        "2025-08-30",
        5,
        True,
    ),
    ("Folds flat for travel. The carrying case is a nice bonus.", 4.0, "2025-07-20", 4, True),
    ("Decent sound but nothing special. Expected more for the price.", 3.0, "2025-10-12", 6, True),
    ("Ear cups get warm after about two hours of continuous use.", 3.0, "2025-09-05", 8, True),
    ("ANC works, but it introduces a faint hissing noise.", 3.0, "2025-08-18", 10, True),
    ("They're okay. My old pair sounded almost as good honestly.", 3.0, "2025-07-28", 3, True),
    ("Microphone quality is mediocre — callers say I sound muffled.", 3.0, "2025-11-01", 12, True),
    ("Headband started cracking after three months. Disappointed.", 2.0, "2025-10-08", 20, True),
    ("Keeps disconnecting randomly from my Windows laptop.", 2.0, "2025-09-22", 16, True),
    (
        "Noise cancellation stopped working on the left ear after a month.",
        2.0,
        "2025-08-15",
        14,
        False,
    ),
    ("Too tight on my head. Gives me a headache after 30 minutes.", 1.0, "2025-07-10", 19, True),
    ("Arrived broken — right speaker produces no sound at all.", 1.0, "2025-10-30", 25, True),
    (
        "Terrible battery. Barely lasts 10 hours despite the claim of 30.",
        1.0,
        "2025-09-18",
        21,
        False,
    ),
    ("Sound leaks badly. People around me can hear my music.", 2.0, "2025-11-08", 7, True),
    (
        "Pairing drops every time I walk more than 5 feet from my phone.",
        1.0,
        "2025-08-02",
        17,
        True,
    ),
    (
        "Love the multipoint connection — seamless switching between devices.",
        5.0,
        "2025-10-14",
        8,
        True,
    ),
    ("Great value compared to Sony and Bose. 90% of the quality.", 5.0, "2025-09-27", 10, True),
    ("EQ customization in the app makes a real difference.", 4.0, "2025-08-11", 6, True),
    ("Packaging was damaged but headphones were fine inside.", 4.0, "2025-07-15", 2, True),
    ("My teenager loves them. Good gift idea for students.", 5.0, "2025-11-05", 3, True),
    ("Average. They work but nothing stands out as great.", 3.0, "2025-10-20", 4, True),
    ("Returned them — too heavy compared to my AirPods Max.", 2.0, "2025-09-09", 11, True),
]

_KEYBOARD_ASIN = "B09HKF3M2W"
_KEYBOARD: list[tuple[str, float, str, int, bool]] = [
    (
        "Cherry MX Brown switches feel great — perfect tactile feedback.",
        5.0,
        "2025-11-03",
        28,
        True,
    ),
    ("RGB lighting is gorgeous and fully customizable per key.", 5.0, "2025-10-20", 19, True),
    ("Build is solid aluminum. No flex at all. Feels very premium.", 5.0, "2025-09-15", 14, True),
    ("Typing on this for 8 hours a day with zero fatigue.", 5.0, "2025-08-28", 10, True),
    ("Software is intuitive. Macros are easy to set up.", 4.0, "2025-10-10", 7, True),
    ("Good keyboard but the spacebar rattles a bit. Minor annoyance.", 4.0, "2025-09-22", 9, True),
    ("Detachable USB-C cable is a great feature for portability.", 4.0, "2025-08-14", 5, True),
    ("Keycaps feel smooth and haven't shown shine after 6 months.", 4.0, "2025-07-30", 6, True),
    (
        "Wrist rest could be more cushioned, but it's included so no complaints.",
        4.0,
        "2025-11-08",
        4,
        True,
    ),
    ("Media keys are convenient. Volume wheel is a nice touch.", 5.0, "2025-10-02", 8, True),
    ("A bit loud for an office. Coworkers notice the clicking.", 3.0, "2025-09-18", 12, True),
    ("Function row feels mushy compared to the letter keys.", 3.0, "2025-08-05", 7, True),
    ("No wireless option. Would love Bluetooth for a clean desk.", 3.0, "2025-07-22", 11, True),
    ("Paint on the frame started chipping after two months.", 2.0, "2025-10-15", 15, True),
    ("The G and H keys stopped registering after a few weeks.", 1.0, "2025-09-28", 22, True),
    ("Software requires an account to use. Annoying and unnecessary.", 2.0, "2025-08-20", 18, True),
    ("LEDs on the 'S' and 'D' keys died within a month.", 1.0, "2025-07-12", 20, True),
    ("Arrived with a sticky Enter key. Had to RMA it.", 1.0, "2025-10-25", 16, True),
    ("For the price, you can't beat this keyboard. Excellent value.", 5.0, "2025-11-01", 13, True),
    ("N-key rollover works flawlessly in games. No ghosting at all.", 5.0, "2025-09-08", 9, True),
    ("Typing sound is satisfying. ASMR-level clicky goodness.", 5.0, "2025-08-24", 6, True),
    ("Not Mac-friendly out of the box. Had to remap keys manually.", 3.0, "2025-10-18", 8, True),
    ("Great for gaming but I wouldn't recommend it for pure typing.", 3.0, "2025-09-12", 5, True),
    (
        "Feet broke off the bottom after a month. Keyboard slides around now.",
        2.0,
        "2025-08-01",
        14,
        True,
    ),
    ("USB passthrough port is handy for charging my mouse.", 4.0, "2025-07-18", 3, True),
    ("Upgraded from a membrane keyboard — night and day difference.", 5.0, "2025-10-30", 11, True),
    ("Stabilizers rattle on larger keys. Needs lube out of the box.", 3.0, "2025-09-25", 10, True),
    (
        "Num pad is essential for my accounting work. Glad it's full-size.",
        4.0,
        "2025-08-16",
        4,
        True,
    ),
    ("Spilled coffee on it and it still works perfectly. Durable!", 5.0, "2025-11-06", 7, True),
    ("Cable is too short. Had to buy an extension for my setup.", 3.0, "2025-10-08", 6, True),
]

_MOUSE_ASIN = "B0DLKFJ7M3"
_MOUSE: list[tuple[str, float, str, int, bool]] = [
    (
        "Lightest mouse I've ever used — 58g and it glides effortlessly.",
        5.0,
        "2025-11-04",
        30,
        True,
    ),
    ("Sensor tracking is flawless on every surface, even glass.", 5.0, "2025-10-22", 20, True),
    ("Battery lasts 70+ hours on a single charge. Incredible.", 5.0, "2025-09-17", 16, True),
    (
        "Perfect shape for claw grip. My aim improved noticeably in games.",
        5.0,
        "2025-08-29",
        12,
        True,
    ),
    ("Low-latency wireless. Can't tell the difference from wired.", 5.0, "2025-10-06", 9, True),
    ("Side buttons are well-placed and have a satisfying click.", 4.0, "2025-09-20", 7, True),
    ("Scroll wheel is smooth but I wish it had a free-spin mode.", 4.0, "2025-08-12", 5, True),
    ("DPI switch on the bottom is inconvenient during gameplay.", 4.0, "2025-07-25", 8, True),
    ("USB-C charging is great. No more micro-USB dongles.", 4.0, "2025-11-09", 4, True),
    (
        "Software lets you save profiles to onboard memory. Useful feature.",
        4.0,
        "2025-10-15",
        6,
        True,
    ),
    ("Shape is too flat for palm grip users. Know your grip style.", 3.0, "2025-09-08", 10, True),
    ("Right click developed a double-click issue after 4 months.", 2.0, "2025-08-22", 18, True),
    ("Feet wore down fast. Had to replace them after 3 months.", 3.0, "2025-07-14", 11, True),
    ("Coating gets greasy quickly. Need to wipe it down constantly.", 3.0, "2025-10-28", 9, True),
    ("Dongle receiver is tiny — I've already lost one.", 3.0, "2025-09-30", 7, True),
    ("Left click started squeaking after two months of use.", 2.0, "2025-08-18", 15, True),
    (
        "Wireless drops for a split second every few minutes. Frustrating.",
        2.0,
        "2025-07-08",
        19,
        True,
    ),
    ("Build feels cheap and hollow. Creaks when I squeeze it.", 1.0, "2025-10-12", 22, True),
    ("Scroll wheel broke completely after six weeks. Unacceptable.", 1.0, "2025-09-03", 25, True),
    ("Mouse wheel click requires way too much force. Uncomfortable.", 2.0, "2025-08-06", 13, True),
    ("Best gaming mouse under $80. Highly recommend for FPS players.", 5.0, "2025-11-02", 14, True),
    ("Pairs instantly with the 2.4GHz dongle. Zero setup needed.", 5.0, "2025-10-19", 8, True),
    ("Very quiet clicks. Great for late-night gaming sessions.", 5.0, "2025-09-14", 6, True),
    ("Good mouse but software is Windows-only. No Mac support.", 3.0, "2025-08-26", 12, True),
    ("Rubber grips on the side peel off after heavy use.", 2.0, "2025-07-20", 16, True),
    (
        "Returned it. My hand cramped after an hour due to the small size.",
        1.0,
        "2025-10-24",
        20,
        True,
    ),
    ("DPI range of 100-25600 is overkill but nice to have options.", 4.0, "2025-09-26", 5, True),
    ("Wish it came in more colors. Only black is boring.", 4.0, "2025-08-10", 3, True),
    ("Replaced my Logitech G Pro and haven't looked back.", 5.0, "2025-11-07", 10, True),
    (
        "Middle ground mouse. Not the best, not the worst. Gets the job done.",
        3.0,
        "2025-10-01",
        4,
        True,
    ),
]

# Mapping from ASIN to its review pool
_CATALOG: dict[str, list[tuple[str, float, str, int, bool]]] = {
    _HEADPHONES_ASIN: _HEADPHONES,
    _KEYBOARD_ASIN: _KEYBOARD,
    _MOUSE_ASIN: _MOUSE,
}

# Public lookup for product metadata used by other modules
PRODUCT_META: dict[str, dict[str, str]] = {
    _HEADPHONES_ASIN: {
        "title": "ProSound ANC-700 Wireless Headphones",
        "image_url": "https://m.media-amazon.com/images/I/mock-headphones.jpg",
        "price": "$79.99",
        "total_review_count": "1552",
    },
    _KEYBOARD_ASIN: {
        "title": "MechForce K1 Mechanical Gaming Keyboard",
        "image_url": "https://m.media-amazon.com/images/I/mock-keyboard.jpg",
        "price": "$109.99",
        "total_review_count": "1552",
    },
    _MOUSE_ASIN: {
        "title": "SwiftClick Ultra Wireless Gaming Mouse",
        "image_url": "https://m.media-amazon.com/images/I/mock-mouse.jpg",
        "price": "$69.99",
        "total_review_count": "1552",
    },
}


def _expand_pool(
    pool: list[tuple[str, float, str, int, bool]],
    target: int,
    rng: random.Random,
) -> list[tuple[str, float, str, int, bool]]:
    """Repeat and shuffle a template pool until it reaches *target* size."""
    full = pool * ((target // len(pool)) + 1)
    rng.shuffle(full)
    return full[:target]


def get_mock_reviews(asin: str, max_reviews: int = 200) -> list[Review]:
    """Return mock reviews for a given ASIN.

    Args:
        asin: Amazon product identifier (e.g. "B08N5WRWNW").
        max_reviews: Desired number of reviews, clamped to 25-250.

    Returns:
        List of Review dataclass instances, length == clamped max_reviews.

    Raises:
        ValueError: If the ASIN is not in the mock catalog.
    """
    # If ASIN is unknown, pick a deterministic fallback pool by ASIN hash,
    # but keep the original ASIN key so downstream code can still resolve
    # PRODUCT_META / total_review_count for *this* product id.
    if asin not in _CATALOG:
        keys = sorted(_CATALOG.keys())
        fallback_asin = keys[sum(ord(ch) for ch in asin) % len(keys)]
        _CATALOG[asin] = _CATALOG[fallback_asin]
        if fallback_asin in PRODUCT_META:
            meta = dict(PRODUCT_META[fallback_asin])
            meta["title"] = f"Product {asin}"
            PRODUCT_META[asin] = meta

    max_reviews = max(_MIN_REVIEWS, min(max_reviews, _MAX_REVIEWS))
    rng = random.Random(42)
    pool = _expand_pool(_CATALOG[asin], max_reviews, rng)

    return [
        Review(
            text=text,
            rating=rating,
            date=date,
            helpful_votes=helpful_votes,
            verified_purchase=verified,
        )
        for text, rating, date, helpful_votes, verified in pool
    ]
