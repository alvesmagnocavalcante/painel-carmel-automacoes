"""Regressões da consulta e da conferência de cartões."""

import asyncio
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

import flet as ft
from openpyxl import load_workbook

from automations.cartoes_credito.data import CardPayment, classify, filter_payments, validate_period
from automations.cartoes_credito.database import map_payment
from automations.cartoes_credito.export import export_payments
from automations.cartoes_credito.panel import main
from automations.cartoes_credito.statement import BankStatement, BankTransaction
from automations.cartoes_credito.store import CardStore


def payment(**changes):
    values = dict(document_id=10, company_id=2, company="CARMEL TAÍBA", launch_number="203532",
                  beneficiary="LATAM AIRLINES BRASIL", tax_id="12345678000190",
                  launch_date=date(2026, 10, 1), due_date=date(2026, 10, 20),
                  scheduled_date=date(2026, 10, 19), amount=Decimal("2035.32"),
                  history="Passagem aérea", payment_method="Cartão de Crédito",
                  responsible="Equipe", attachment_count=2)
    values.update(changes)
    return CardPayment(**values)


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


class CardPaymentTests(TestCase):
    def test_period_and_pending_reason_are_validated(self):
        with self.assertRaises(ValueError):
            validate_period(date(2026, 10, 2), date(2026, 10, 1))
        with self.assertRaises(ValueError):
            classify(payment(), "Pendente", " ")
        checked = classify(payment(), "Pendente", "sem nota fiscal")
        self.assertEqual(checked.pending_reason, "sem nota fiscal")
        self.assertEqual(classify(checked, "Conferido").pending_reason, "")

    def test_filter_accepts_company_and_accent_insensitive_search(self):
        rows = (payment(), payment(document_id=11, company="MAGNA PRAIA", beneficiary="Outro"))
        self.assertEqual(filter_payments(rows, "CARMEL TAÍBA", "LATAM"), rows[:1])
        self.assertEqual(filter_payments(rows, "Todos", "taiba"), rows[:1])
        self.assertEqual(filter_payments(rows, "Todos", "203532"), rows)
        self.assertEqual(filter_payments(rows, "Todos", "12345678000190"), rows)

    def test_mapping_preserves_missing_amount_and_attachment_count(self):
        row = dict(iddocumentocapcarbase=10, fkempresa=2, empresa="CARMEL TAÍBA",
                   annumero="203532", favorecido="LATAM AIRLINES BRASIL", cpfcnpj="12345678000190",
                   lancamento=date(2026, 10, 1), vencimento=None, programada=None,
                   valor=None, anhistorico="", formadepagamento="", usuariolancamento="",
                   contagem_anexos=0)
        mapped = map_payment(row)
        self.assertIsNone(mapped.amount)
        self.assertEqual(mapped.attachment_count, 0)
        self.assertEqual(mapped.tax_id, "12.345.678/0001-90")

    def test_excel_highlights_review_and_escapes_formula_text(self):
        rows = (classify(payment(beneficiary="=HYPERLINK(\"unsafe\")"), "Pendente", "sem nota"),)
        workbook = load_workbook(BytesIO(export_payments(rows)))
        sheet = workbook.active
        self.assertEqual(sheet["C2"].data_type, "s")
        self.assertTrue(sheet["C2"].value.startswith("'="))
        self.assertEqual(sheet["K2"].value, "Pendente")
        self.assertEqual(sheet["L2"].value, "sem nota")
        self.assertAlmostEqual(sheet["E2"].value, 2035.32)
        self.assertEqual(sheet["K2"].fill.fgColor.rgb[-6:], "F4CCCC")

    def test_panel_has_one_review_flow_and_queries_after_invoice_import(self):
        page = MagicMock(web=True)
        page.overlay = []
        page.get_upload_url.return_value = "/upload?signature=test"
        source = MagicMock()
        beneficiary = "STOCK COMERCIO DE EQUIPAMENTOS INDUSTRIAIS E DE SEGURANCA LTDA"
        source.fetch.return_value = (payment(beneficiary=beneficiary),)
        statement = BankStatement("CARMEL TAÍBA HOSPEDAGEM LTDA", date(2026, 10, 20), Decimal("2035.32"),
                                  (BankTransaction(24, date(2026, 10, 1), "PASSAGEM AÉREA", Decimal("2035.32"),
                                                   "TITULAR", "1528", "Nacional"),))
        with TemporaryDirectory() as folder, patch("automations.cartoes_credito.bank_panel.parse_statement",
                                                   return_value=statement):
            view = main(page, download_file=MagicMock(), provider=source, upload_dir=folder,
                        store=CardStore(Path(folder) / "cartoes.sqlite3"))
            source.fetch.assert_not_called()
            self.assertFalse(any(isinstance(item, ft.Text) and "Consulta avulsa" in item.value
                                 for item in walk(view.control)))
            picker = page.overlay[0]
            picker.upload = MagicMock()
            picker.on_result(MagicMock(files=[MagicMock(name="fatura.xlsx", size=1234)]))
            path = Path(folder) / page.get_upload_url.call_args.args[0]
            path.write_bytes(b"temporary workbook")
            picker.on_upload(MagicMock(error=None, progress=1.0))
            task, event = page.run_task.call_args.args
            asyncio.run(task(event))
        source.fetch.assert_called_once()
        self.assertFalse(path.exists())
        self.assertFalse(any(isinstance(item, ft.OutlinedButton) and item.text == "Baixar Excel"
                             for item in walk(view.control)))
        self.assertEqual(view.control.horizontal_alignment, ft.CrossAxisAlignment.STRETCH)
        actions = [item for item in walk(view.control) if isinstance(item, ft.OutlinedButton)
                   and item.text == "Conferir"]
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action.text, "Conferir")
        action.on_click(None)
        dialog = page.open.call_args.args[0]
        self.assertIsInstance(dialog, ft.AlertDialog)
        self.assertTrue(any(isinstance(item, ft.Text) and "mesmo valor" in item.value
                            for item in walk(dialog)))
        self.assertFalse(any(isinstance(item, ft.Text) and "Possíveis" in item.value
                             for item in walk(dialog)))
        self.assertFalse(any(isinstance(item, ft.Text) and "CMFlex" in item.value
                             for item in walk(dialog)))
        self.assertEqual(sum(isinstance(item, ft.Radio) for item in walk(dialog)), 1)
        radio = next(item for item in walk(dialog) if isinstance(item, ft.Radio))
        self.assertIsNone(radio.label)
        self.assertEqual(radio.tooltip, "Selecionar lançamento 203532")
        self.assertTrue(radio.toggleable)
        beneficiary_text = next(item for item in walk(dialog)
                                if isinstance(item, ft.Text) and item.value == beneficiary)
        self.assertEqual(beneficiary_text.max_lines, 2)
        self.assertEqual(beneficiary_text.overflow, ft.TextOverflow.ELLIPSIS)
        self.assertEqual(beneficiary_text.tooltip, beneficiary)
        self.assertEqual(dialog.content.width, 900)
        self.assertEqual(dialog.content.height, 420)
        choices = next(item for item in walk(dialog) if isinstance(item, ft.RadioGroup))
        self.assertIsInstance(choices.content.controls[0], ft.Container)
        self.assertTrue(any(isinstance(item, ft.Text) and item.value == "Lançamento 203532 • 01/10/2026"
                            for item in walk(choices)))
        choices.value = "2:10"
        choices.on_change(None)
        self.assertEqual(dialog.content.width, 1450)
        self.assertEqual(dialog.content.content.controls[0].expand, 6)
        self.assertEqual(dialog.content.content.controls[-1].expand, 5)
        self.assertTrue(dialog._build_add_commands())
        self.assertTrue(view.control._build_add_commands())
        view.apply_theme(False)
        self.assertTrue(view.control._build_add_commands())
