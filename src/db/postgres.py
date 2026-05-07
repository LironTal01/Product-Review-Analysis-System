"""PostgreSQL persistence for analysis results.

Stores every analysis as a row in a single ``analyses`` table. The full
result is kept in a JSONB column so the schema does not need to change as
the analysis output grows.

Graceful degradation: if ``settings.database_url`` is empty or the database
cannot be reached, all public functions log a warning and return a falsy
value instead of raising. The web layer can therefore call them without
``try/except`` and still serve requests when no database is configured
(useful in development, tests, and the demo environment before Postgres is
provisioned).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from src.utils.config import get_settings
from src.utils.logger import logger

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    asin VARCHAR(10) NOT NULL,
    max_reviews INT NOT NULL,
    result_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_analyses_asin_max_reviews
ON analyses (asin, max_reviews, created_at DESC);
"""

INSERT_SQL = """
INSERT INTO analyses (asin, max_reviews, result_json)
VALUES (%s, %s, %s);
"""

SELECT_LATEST_SQL = """
SELECT result_json
FROM analyses
WHERE asin = %s AND max_reviews = %s
ORDER BY created_at DESC
LIMIT 1;
"""


def _connect() -> psycopg.Connection | None:
    """Open a connection or return ``None`` if Postgres is not configured/reachable."""
    settings = get_settings()
    if not settings.database_url:
        return None
    try:
        return psycopg.connect(settings.database_url)
    except psycopg.OperationalError as exc:
        logger.warning("Postgres unavailable: %s", exc)
        return None


def init_db() -> bool:
    """Create the ``analyses`` table and supporting index if absent.

    Safe to call repeatedly. Returns ``True`` on success, ``False`` when the
    database is unavailable or the DDL fails.
    """
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn, conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(CREATE_INDEX_SQL)
        logger.info("Postgres schema ready (analyses table)")
        return True
    except psycopg.Error as exc:
        logger.warning("init_db failed: %s", exc)
        return False
    finally:
        conn.close()


def save_analysis(asin: str, max_reviews: int, result: dict[str, Any]) -> bool:
    """Persist one analysis row. Returns ``True`` on success, ``False`` otherwise."""
    if not asin or not isinstance(result, dict):
        return False

    conn = _connect()
    if conn is None:
        return False
    try:
        with conn, conn.cursor() as cur:
            cur.execute(INSERT_SQL, (asin, max_reviews, json.dumps(result)))
        logger.info("Saved analysis: asin=%s max_reviews=%d", asin, max_reviews)
        return True
    except psycopg.Error as exc:
        logger.warning("save_analysis failed for asin=%s: %s", asin, exc)
        return False
    finally:
        conn.close()


def get_analysis(asin: str, max_reviews: int) -> dict[str, Any] | None:
    """Return the most recent persisted analysis for ``(asin, max_reviews)`` or ``None``.

    psycopg 3 decodes ``JSONB`` columns to native Python types, so the value
    we return is already a ``dict``.
    """
    if not asin:
        return None

    conn = _connect()
    if conn is None:
        return None
    try:
        with conn, conn.cursor() as cur:
            cur.execute(SELECT_LATEST_SQL, (asin, max_reviews))
            row = cur.fetchone()
            if row is None:
                return None
            value = row[0]
            if isinstance(value, str):
                # Defensive: some drivers / configurations return raw JSON strings.
                return json.loads(value)
            return value
    except psycopg.Error as exc:
        logger.warning("get_analysis failed for asin=%s: %s", asin, exc)
        return None
    finally:
        conn.close()
