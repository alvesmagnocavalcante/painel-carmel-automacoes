"""Unit tests for the SQLite persistence in Bordero."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from automations.bordero.panel_data import ConferenceRow, classify_conference
from automations.bordero.store import BorderoStore


def sample_row(doc_id: int = 100, company_id: int = 1, situation: str = "A conferir") -> ConferenceRow:
    return ConferenceRow(
        supplier="Fornecedor Teste",
        tax_id="00.000.000/0001-91",
        launch_number="12345",
        company="CARMEL CHARME",
        balance=Decimal("1500.00"),
        scheduled_date=date(2026, 10, 20),
        due_date=date(2026, 10, 25),
        payment_method="Boleto",
        history="Serviços",
        situation=situation,
        responsible="Financeiro",
        document_id=doc_id,
        company_id=company_id,
        review_key=f"key_{doc_id}_{company_id}",
    )


class BorderoStoreTests(TestCase):
    def test_save_and_apply_reviews(self):
        with TemporaryDirectory() as folder:
            db_path = Path(folder) / "test_bordero.sqlite3"
            store = BorderoStore(db_path)

            row1 = sample_row(101, 1)
            row2 = sample_row(102, 1)
            rows = (row1, row2)

            # Initially no saved reviews
            applied = store.apply_reviews(rows)
            self.assertEqual(applied[0].situation, "A conferir")
            self.assertEqual(applied[1].situation, "A conferir")

            # Review row1 as Conferido and row2 as Pendente
            reviewed1 = classify_conference(row1, "Conferido")
            reviewed2 = classify_conference(row2, "Pendente", "Comprovante ilegível")
            store.save_review(reviewed1)
            store.save_review(reviewed2)

            # Apply onto fresh rows
            applied = store.apply_reviews(rows)
            self.assertEqual(applied[0].situation, "Conferido")
            self.assertEqual(applied[0].pending_reason, "")
            self.assertEqual(applied[1].situation, "Pendente")
            self.assertEqual(applied[1].pending_reason, "Comprovante ilegível")

    def test_persistence_survives_restart_and_unreview(self):
        with TemporaryDirectory() as folder:
            db_path = Path(folder) / "test_bordero.sqlite3"
            store1 = BorderoStore(db_path)
            row = sample_row(201, 2)
            store1.save_review(classify_conference(row, "Conferido"))

            # Simulate new session with fresh store instance pointing to same file
            store2 = BorderoStore(db_path)
            reviews = store2.load_reviews()
            self.assertIn((201, 2), reviews)
            self.assertEqual(reviews[(201, 2)], ("Conferido", ""))

            # Reset back to "A conferir" removes from store
            store2.save_review(classify_conference(row, "A conferir"))
            self.assertNotIn((201, 2), store2.load_reviews())
