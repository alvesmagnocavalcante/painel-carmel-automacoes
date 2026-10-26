"""Persistent SQLite storage for Bordero payment review status."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from automations.bordero.panel_data import ConferenceRow, classify_conference


def load_environment() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class BorderoStore:
    """Store human review classifications in a local SQLite database."""

    def __init__(self, path: Path | str | None = None) -> None:
        load_environment()
        configured = os.getenv("BORDERO_ACTION_DB") or os.getenv("BORDERO_DB_PATH")
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = (
            Path(path)
            if path is not None
            else Path(configured)
            if configured
            else root / "Carmel" / "portal" / "bordero.sqlite3"
        )

    @contextmanager
    def connection(self):
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS bordero_reviews (
                        document_id INTEGER NOT NULL,
                        company_id INTEGER NOT NULL,
                        review_key TEXT NOT NULL,
                        situation TEXT NOT NULL,
                        pending_reason TEXT NOT NULL DEFAULT '',
                        reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (document_id, company_id)
                    )
                """)
                yield conn
        finally:
            conn.close()

    def save_review(self, row: ConferenceRow) -> None:
        """Persist a review classification for an open payment."""
        if row.document_id is None or row.company_id is None:
            return
        with self.connection() as conn:
            if row.situation == "A conferir":
                conn.execute(
                    "DELETE FROM bordero_reviews WHERE document_id = ? AND company_id = ?",
                    (row.document_id, row.company_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO bordero_reviews (document_id, company_id, review_key, situation, pending_reason, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(document_id, company_id) DO UPDATE SET
                        situation = excluded.situation,
                        pending_reason = excluded.pending_reason,
                        review_key = excluded.review_key,
                        reviewed_at = CURRENT_TIMESTAMP
                    """,
                    (row.document_id, row.company_id, row.review_key, row.situation, row.pending_reason),
                )

    def load_reviews(self) -> dict[tuple[int, int], tuple[str, str]]:
        """Return a mapping of (document_id, company_id) -> (situation, pending_reason)."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT document_id, company_id, situation, pending_reason FROM bordero_reviews")
            return {
                (int(row["document_id"]), int(row["company_id"])): (str(row["situation"]), str(row["pending_reason"]))
                for row in cursor.fetchall()
            }

    def apply_reviews(self, rows: tuple[ConferenceRow, ...]) -> tuple[ConferenceRow, ...]:
        """Apply previously saved reviews onto freshly fetched conference rows."""
        saved = self.load_reviews()
        if not saved:
            return rows
        updated: list[ConferenceRow] = []
        for row in rows:
            if row.document_id is not None and row.company_id is not None:
                key = (row.document_id, row.company_id)
                if key in saved:
                    situation, reason = saved[key]
                    try:
                        updated.append(classify_conference(row, situation, reason))
                        continue
                    except ValueError:
                        pass
            updated.append(row)
        return tuple(updated)
