"""Settings endpoints — manage application settings stored in SpanNILM DB."""

import logging
import os

import psycopg2
import psycopg2.extras
from fastapi import APIRouter

logger = logging.getLogger("span_nilm.api.settings")
router = APIRouter(prefix="/api")


def _get_db():
    return psycopg2.connect(os.environ["SPANNILM_DATABASE_URL"])


@router.get("/settings")
def get_settings() -> dict[str, str]:
    """Return all settings as a key-value dict."""
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT key, value FROM settings")
            return {row["key"]: row["value"] for row in cur.fetchall()}
    finally:
        conn.close()


@router.put("/settings")
def update_settings(updates: dict[str, str]) -> dict[str, str]:
    """Upsert settings. Accepts {key: value} pairs."""
    conn = _get_db()
    try:
        with conn.cursor() as cur:
            for key, value in updates.items():
                cur.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = now()
                    """,
                    (key, str(value)),
                )
        conn.commit()
    finally:
        conn.close()
    # Return full settings after update
    return get_settings()
