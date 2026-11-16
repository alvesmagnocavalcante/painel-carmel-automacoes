"""Per-hotel daily report: rules, exports, screen and route."""

import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest import TestCase
from unittest.mock import MagicMock, patch

import flet as ft
from openpyxl import load_workbook

from automations.inventario.report import (
    ReportRow, companies, report_totals, validate_period, validate_report_rows,
)
from automations.inventario.report_export import export_report_excel, export_report_pdf, report_filename
from automations.inventario.report_panel import main
from tests.test_inventario import walk


def row(day=date(2026, 10, 29), company="CARMEL TAÍBA", warehouse="BAR", counted=100, different=10,
        loss="60", surplus="40", stock="1000"):
    return ReportRow(day, company, warehouse, counted, different, Decimal(loss), Decimal(surplus), Decimal(stock))


def rows():
    return (row(), row(day=date(2026, 10, 30), warehouse="COZINHA", counted=50, different=0, loss="0", surplus="0", stock="500"),
            row(company="MAGNA PRAIA", warehouse="CENTRAL", stock="2000"))


class ReportRulesTests(TestCase):
    def test_difference_does_not_offset_loss_and_surplus_and_percentages(self):
        item = row()
        self.assertEqual(item.difference, Decimal(100))
        self.assertEqual(item.percentage, Decimal("0.1"))
        self.assertEqual(item.financial_percentage, Decimal("0.1"))
        self.assertIsNone(replace(item, stock=Decimal(0)).financial_percentage)
        self.assertEqual(replace(item, stock=Decimal(0)).status, "Sem base financeira")

    def test_invalid_rows_period_and_duplicates_are_rejected(self):
        with self.assertRaises(ValueError):
            row(counted=1, different=2)
        with self.assertRaises(ValueError):
            validate_period(date(2026, 11, 2), date(2026, 11, 1))
        with self.assertRaises(ValueError):
            validate_period(date(2020, 1, 1), date(2026, 1, 1))
        validate_period(date(2026, 11, 1), date(2026, 11, 1))
        with self.assertRaises(ValueError):
            validate_report_rows((row(), row()))

    def test_stock_counts_once_per_warehouse_and_month(self):
        same_warehouse_two_days = (row(), row(day=date(2026, 10, 30)), row(day=date(2026, 11, 2)))
        totals = report_totals(same_warehouse_two_days)
        self.assertEqual(totals.stock, Decimal(2000))  # Oct once + Nov once
        self.assertEqual(totals.counted, 300)
        self.assertEqual(totals.difference, Decimal(300))
        self.assertEqual(totals.financial_percentage, Decimal("0.15"))
        self.assertEqual(companies(rows()), ("CARMEL TAÍBA", "MAGNA PRAIA"))


class ReportExportTests(TestCase):
    start, end = date(2026, 10, 29), date(2026, 10, 30)

    def hotel_rows(self):
        return tuple(item for item in rows() if item.company == "CARMEL TAÍBA")

    def test_excel_has_hotel_period_rows_totals_and_no_formulas(self):
        book = load_workbook(BytesIO(export_report_excel(self.hotel_rows(), self.start, self.end)))
        try:
            sheet = book.active
            self.assertIn("CARMEL TAÍBA", sheet["A1"].value)
            self.assertIn("29/10/2026 a 30/10/2026", sheet["A2"].value)
            self.assertEqual(sheet["A10"].value.date(), date(2026, 10, 29))
            self.assertEqual(sheet["B10"].value, "BAR")
            self.assertEqual(sheet["I10"].value, 100)
            self.assertEqual(sheet["B12"].value, "Total do período")
            self.assertEqual(sheet["C12"].value, 150)
            self.assertEqual(sheet["F12"].value, 1500)
            self.assertAlmostEqual(sheet["J12"].value, 100 / 1500)
            self.assertFalse(any(cell.data_type == "f" for line in sheet for cell in line))
        finally:
            book.close()

    def test_pdf_and_filename_and_single_hotel_rule(self):
        self.assertTrue(export_report_pdf(self.hotel_rows(), self.start, self.end).startswith(b"%PDF-"))
        self.assertEqual(report_filename("CARMEL TAÍBA", self.start, self.end, "pdf"),
                         "relatorio-inventario-carmel-taiba-20261029-20261030.pdf")
        for exporter in (export_report_excel, export_report_pdf):
            with self.assertRaises(ValueError):
                exporter((), self.start, self.end)
            with self.assertRaisesRegex(ValueError, "individual"):
                exporter(rows(), self.start, self.end)

    def test_spreadsheet_text_is_not_executed_as_formula(self):
        book = load_workbook(BytesIO(export_report_excel((row(warehouse="=HYPERLINK(1)"),), self.start, self.end)))
        try:
            self.assertEqual(book.active["B10"].value, "'=HYPERLINK(1)")
        finally:
            book.close()


class ReportPanelTests(TestCase):
    def test_consult_filters_by_hotel_downloads_both_formats_and_reports_errors(self):
        page, provider = MagicMock(web=True), MagicMock()
        provider.fetch.return_value = rows()
        download = MagicMock(return_value="/downloads/test")
        view = main(page, download_file=download, provider=provider)
        page.update.side_effect = lambda: view.control._build_add_commands()
        provider.fetch.assert_not_called()
        fields = {item.label: item for item in walk(view.control) if isinstance(item, (ft.TextField, ft.Dropdown))}
        fields["Data inicial"].value, fields["Data final"].value = "29/10/2026", "30/10/2026"
        consult = next(c for c in walk(view.control) if isinstance(c, ft.ElevatedButton))
        asyncio.run(consult.on_click(None))
        self.assertEqual(provider.fetch.call_args.args, (date(2026, 10, 29), date(2026, 10, 30)))
        self.assertEqual(fields["Hotel"].value, "CARMEL TAÍBA")
        self.assertEqual(len(next(c for c in walk(view.control) if isinstance(c, ft.DataTable)).rows), 2)
        fields["Hotel"].value = "MAGNA PRAIA"
        fields["Hotel"].on_change(None)
        self.assertEqual(len(next(c for c in walk(view.control) if isinstance(c, ft.DataTable)).rows), 1)
        for label, suffix in (("Baixar Excel", ".xlsx"), ("Baixar PDF", ".pdf")):
            button = next(c for c in walk(view.control) if isinstance(c, ft.OutlinedButton) and c.text == label)
            asyncio.run(button.on_click(None))
            self.assertIn("magna-praia", download.call_args.args[1])
            self.assertTrue(download.call_args.args[1].endswith(suffix))
        view.apply_theme(False)
        fields["Data inicial"].value = "31/10/2026"
        with patch("automations.inventario.report_panel.logging.getLogger"):
            asyncio.run(consult.on_click(None))
        self.assertEqual(provider.fetch.call_count, 1)  # invalid period never reaches the database
        provider.fetch.side_effect = RuntimeError("Falha de teste")
        fields["Data inicial"].value = "29/10/2026"
        with patch("automations.inventario.report_panel.logging.getLogger"):
            asyncio.run(consult.on_click(None))
        self.assertFalse(consult.disabled)

    def test_browser_only_and_portal_route(self):
        with self.assertRaises(RuntimeError):
            main(MagicMock(web=False))
        from portal.app import main as portal
        page = MagicMock(web=True, route="/inventario/relatorio")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        portal(page, MagicMock(), MagicMock())
        body = roots[0].controls[1]
        self.assertTrue(any(isinstance(c, ft.TextField) and c.label == "Data inicial" for c in walk(body)))
