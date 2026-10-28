"""Persistent SQLite storage for DDA reconciliation overrides, notes and responsibles."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from automations.dda.data import DdaReconciliationItem, DdaTransaction


def load_environment() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def make_transaction_key(tx: DdaTransaction) -> str:
    """Stable key to identify a DDA transaction."""
    dt_str = tx.due_date.strftime("%Y%m%d") if tx.due_date else "nodate"
    return f"{tx.sheet_name}_{tx.clean_cnpj}_{tx.document_number}_{tx.amount}_{dt_str}"


class DdaStore:
    """Store human review notes and classification overrides in SQLite."""

    def __init__(self, path: Path | str | None = None) -> None:
        load_environment()
        configured = os.getenv("DDA_ACTION_DB") or os.getenv("DDA_DB_PATH")
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = (
            Path(path)
            if path is not None
            else Path(configured)
            if configured
            else root / "Carmel" / "portal" / "dda.sqlite3"
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
                    CREATE TABLE IF NOT EXISTS dda_reviews (
                        review_key TEXT PRIMARY KEY,
                        sheet_name TEXT NOT NULL,
                        tax_id TEXT NOT NULL,
                        supplier TEXT NOT NULL,
                        amount TEXT NOT NULL,
                        due_date TEXT NOT NULL,
                        custom_status TEXT,
                        custom_observation TEXT,
                        custom_responsible TEXT,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                yield conn
        finally:
            conn.close()

    def save_review(
        self,
        tx: DdaTransaction,
        custom_status: str | None,
        custom_observation: str | None,
        custom_responsible: str | None,
    ) -> None:
        """Persist or update an override note for a transaction."""
        key = make_transaction_key(tx)
        dt_str = tx.due_date.strftime("%Y-%m-%d") if tx.due_date else ""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO dda_reviews (
                    review_key, sheet_name, tax_id, supplier, amount, due_date,
                    custom_status, custom_observation, custom_responsible, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(review_key) DO UPDATE SET
                    custom_status = excluded.custom_status,
                    custom_observation = excluded.custom_observation,
                    custom_responsible = excluded.custom_responsible,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    key,
                    tx.sheet_name,
                    tx.clean_cnpj,
                    tx.supplier,
                    str(tx.amount),
                    dt_str,
                    custom_status,
                    custom_observation,
                    custom_responsible,
                ),
            )

    def load_reviews(self) -> dict[str, tuple[str | None, str | None, str | None]]:
        """Load all reviews keyed by make_transaction_key."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT review_key, custom_status, custom_observation, custom_responsible FROM dda_reviews"
            ).fetchall()
            return {
                r["review_key"]: (
                    r["custom_status"],
                    r["custom_observation"],
                    r["custom_responsible"],
                )
                for r in rows
            }

    def apply_reviews(self, items: Sequence[DdaReconciliationItem]) -> None:
        """Apply stored reviews to in-memory reconciliation items."""
        reviews = self.load_reviews()
        for item in items:
            key = make_transaction_key(item.transaction)
            if key in reviews:
                status, obs, resp = reviews[key]
                if status is not None:
                    item.custom_status = status
                if obs is not None:
                    item.custom_observation = obs
                if resp is not None:
                    item.custom_responsible = resp
