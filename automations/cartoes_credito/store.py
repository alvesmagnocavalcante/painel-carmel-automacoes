"""Persistent SQLite storage for credit card statement reconciliation reviews."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from automations.cartoes_credito.reconciliation import BankReview
from automations.cartoes_credito.statement import BankStatement, BankTransaction


def load_environment() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class CardStore:
    """Store credit card reconciliation reviews in a local SQLite database."""

    def __init__(self, path: Path | str | None = None) -> None:
        load_environment()
        configured = os.getenv("CARTOES_ACTION_DB") or os.getenv("CARTOES_DB_PATH")
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = (
            Path(path)
            if path is not None
            else Path(configured)
            if configured
            else root / "Carmel" / "portal" / "cartoes.sqlite3"
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
                    CREATE TABLE IF NOT EXISTS card_reviews (
                        statement_due_date TEXT NOT NULL,
                        statement_company TEXT NOT NULL,
                        row_number INTEGER NOT NULL,
                        card_last_four TEXT NOT NULL DEFAULT '',
                        purchase_date TEXT NOT NULL,
                        amount TEXT NOT NULL,
                        description TEXT NOT NULL,
                        status TEXT NOT NULL,
                        pending_reason TEXT NOT NULL DEFAULT '',
                        matched_company_id INTEGER,
                        matched_document_id INTEGER,
                        reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (statement_due_date, statement_company, row_number)
                    )
                """)
                yield conn
        finally:
            conn.close()

    def save_review(
        self,
        statement: BankStatement,
        transaction: BankTransaction,
        review: BankReview,
    ) -> None:
        """Save or remove a transaction review."""
        with self.connection() as conn:
            if review.status == "A conferir":
                conn.execute(
                    """DELETE FROM card_reviews
                       WHERE statement_due_date = ? AND statement_company = ? AND row_number = ?""",
                    (statement.due_date.isoformat(), statement.company, transaction.row_number),
                )
            else:
                matched_company = review.payment_key[0] if review.payment_key else None
                matched_doc = review.payment_key[1] if review.payment_key else None
                conn.execute(
                    """
                    INSERT INTO card_reviews (
                        statement_due_date, statement_company, row_number,
                        card_last_four, purchase_date, amount, description,
                        status, pending_reason, matched_company_id, matched_document_id, reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(statement_due_date, statement_company, row_number) DO UPDATE SET
                        card_last_four = excluded.card_last_four,
                        purchase_date = excluded.purchase_date,
                        amount = excluded.amount,
                        description = excluded.description,
                        status = excluded.status,
                        pending_reason = excluded.pending_reason,
                        matched_company_id = excluded.matched_company_id,
                        matched_document_id = excluded.matched_document_id,
                        reviewed_at = CURRENT_TIMESTAMP
                    """,
                    (
                        statement.due_date.isoformat(),
                        statement.company,
                        transaction.row_number,
                        transaction.card_last_four,
                        transaction.purchase_date.isoformat(),
                        str(transaction.amount),
                        transaction.description,
                        review.status,
                        review.reason,
                        matched_company,
                        matched_doc,
                    ),
                )

    def load_reviews(self, statement: BankStatement) -> dict[int, BankReview]:
        """Load previously saved reviews for a specific statement."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT row_number, card_last_four, purchase_date, amount, status, pending_reason,
                       matched_company_id, matched_document_id
                FROM card_reviews
                WHERE statement_due_date = ? AND statement_company = ?
                """,
                (statement.due_date.isoformat(), statement.company),
            )
            saved = {row["row_number"]: row for row in cursor.fetchall()}

        result: dict[int, BankReview] = {}
        for tx in statement.transactions:
            if tx.row_number in saved:
                row = saved[tx.row_number]
                if str(tx.amount) == row["amount"]:
                    key = (
                        (int(row["matched_company_id"]), int(row["matched_document_id"]))
                        if row["matched_company_id"] is not None and row["matched_document_id"] is not None
                        else None
                    )
                    result[tx.row_number] = BankReview(
                        status=str(row["status"]),
                        reason=str(row["pending_reason"]),
                        payment_key=key,
                    )
        return result
