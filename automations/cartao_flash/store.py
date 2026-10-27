"""Persistent SQLite storage for Flash corporate card reconciliation reviews and notes."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from automations.cartao_flash.data import FlashReconciliationItem, FlashTransaction, normalize_text


def load_environment() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def make_transaction_key(tx: FlashTransaction) -> str:
    """Stable key to identify a Flash card transaction."""
    return f"{tx.purchase_date:%Y%m%d}_{tx.amount}_{normalize_text(tx.description)}_{normalize_text(tx.person)}"


class FlashStore:
    """Store human review notes and classification overrides in SQLite."""

    def __init__(self, path: Path | str | None = None) -> None:
        load_environment()
        configured = os.getenv("FLASH_ACTION_DB") or os.getenv("FLASH_DB_PATH")
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = (
            Path(path)
            if path is not None
            else Path(configured)
            if configured
            else root / "Carmel" / "portal" / "flash.sqlite3"
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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS flash_reviews (
                        review_key TEXT PRIMARY KEY,
                        purchase_date TEXT NOT NULL,
                        amount TEXT NOT NULL,
                        description TEXT NOT NULL,
                        person TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                yield conn
        finally:
            conn.close()

    def save_review(self, tx: FlashTransaction, status: str, notes: str = "") -> None:
        """Persist or update a review note for a transaction."""
        key = make_transaction_key(tx)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO flash_reviews (
                    review_key, purchase_date, amount, description, person, status, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(review_key) DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    key,
                    tx.purchase_date.isoformat(),
                    str(tx.amount),
                    tx.description,
                    tx.person,
                    status.strip(),
                    notes.strip(),
                ),
            )

    def load_reviews(self) -> dict[str, tuple[str, str]]:
        """Return all persisted reviews as {review_key: (status, notes)}."""
        reviews: dict[str, tuple[str, str]] = {}
        with self.connection() as conn:
            cursor = conn.execute("SELECT review_key, status, notes FROM flash_reviews")
            for row in cursor.fetchall():
                reviews[str(row["review_key"])] = (str(row["status"] or ""), str(row["notes"] or ""))
        return reviews
