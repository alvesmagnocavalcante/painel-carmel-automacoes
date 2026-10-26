"""Unit tests for the SQLite persistence in Cartões de Crédito."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from automations.cartoes_credito.reconciliation import BankReview
from automations.cartoes_credito.statement import BankStatement, BankTransaction
from automations.cartoes_credito.store import CardStore


def sample_statement() -> tuple[BankStatement, BankTransaction, BankTransaction]:
    tx1 = BankTransaction(
        row_number=1,
        purchase_date=date(2026, 9, 15),
        description="HOTELARIA TESTE",
        amount=Decimal("350.00"),
        cardholder="DIRETORIA",
        card_last_four="1234",
        category="Nacional",
    )
    tx2 = BankTransaction(
        row_number=2,
        purchase_date=date(2026, 9, 16),
        description="ANUIDADE DIFERENCIADA",
        amount=Decimal("45.00"),
        cardholder="DIRETORIA",
        card_last_four="1234",
        category="Encargo",
    )
    stmt = BankStatement(
        company="CARMEL TAÍBA",
        due_date=date(2026, 10, 10),
        total=Decimal("395.00"),
        transactions=(tx1, tx2),
    )
    return stmt, tx1, tx2


class CardStoreTests(TestCase):
    def test_save_and_load_reviews(self):
        with TemporaryDirectory() as folder:
            db_path = Path(folder) / "test_cartoes.sqlite3"
            store = CardStore(db_path)
            stmt, tx1, tx2 = sample_statement()

            # Initially empty
            self.assertEqual(store.load_reviews(stmt), {})

            # Save reviews for transactions
            review1 = BankReview(status="Conferido", payment_key=(2, 501))
            review2 = BankReview(status="Encargo conferido", payment_key=None)
            store.save_review(stmt, tx1, review1)
            store.save_review(stmt, tx2, review2)

            loaded = store.load_reviews(stmt)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[1].status, "Conferido")
            self.assertEqual(loaded[1].payment_key, (2, 501))
            self.assertEqual(loaded[2].status, "Encargo conferido")
            self.assertIsNone(loaded[2].payment_key)

    def test_persistence_survives_restart_and_unreview(self):
        with TemporaryDirectory() as folder:
            db_path = Path(folder) / "test_cartoes.sqlite3"
            store1 = CardStore(db_path)
            stmt, tx1, _ = sample_statement()

            pending_review = BankReview(status="Pendente", reason="Falta recibo")
            store1.save_review(stmt, tx1, pending_review)

            # Reopen in fresh store instance
            store2 = CardStore(db_path)
            loaded = store2.load_reviews(stmt)
            self.assertIn(1, loaded)
            self.assertEqual(loaded[1].status, "Pendente")
            self.assertEqual(loaded[1].reason, "Falta recibo")

            # Resetting to "A conferir" removes from SQLite
            store2.save_review(stmt, tx1, BankReview(status="A conferir"))
            self.assertEqual(store2.load_reviews(stmt), {})
