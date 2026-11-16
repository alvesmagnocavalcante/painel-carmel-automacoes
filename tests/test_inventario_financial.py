"""Financial domain, SQL lifecycle, Excel and real Flet control regressions."""

import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest import TestCase
from unittest.mock import MagicMock, patch

import flet as ft
import psycopg
from openpyxl import load_workbook

from automations.inventario.database import SqlFinancialInventoryProvider
from automations.inventario.financial import FinancialInventory, financial_totals, validate_financial_rows
from automations.inventario.financial_export import export_financial
from automations.inventario.financial_panel import main, impact_chart
from tests.test_inventario import walk
from portal.theme import DARK, LIGHT


def sample():
    return FinancialInventory(date(2026, 9, 1), "TAÍBA", "EVENTOS",
                              Decimal("1000"), Decimal("20"), Decimal("10"), Decimal("30"), 10, 3)


def records():
    first = sample()
    return (first, replace(first, company="CHARME", stock=Decimal("100")),
            replace(first, warehouse="SEM CONTAGEM", counted=0, different=0,
                    stock=Decimal("9000"), loss=Decimal(0), surplus=Decimal(0), difference=Decimal(0)),
            replace(first, month=date(2026, 10, 1), counted=0, different=0,
                    loss=Decimal(0), surplus=Decimal(0), difference=Decimal(0)))


class FinancialTests(TestCase):
    def test_weighted_monthly_totals_exclude_uncounted_warehouses(self):
        rows = records()[:3]
        stock, difference, fraction = financial_totals(rows)
        self.assertEqual(stock, Decimal(1100))
        self.assertEqual(difference, Decimal(60))
        self.assertEqual(fraction, Decimal(60) / 1100)
        self.assertIsNone(rows[2].percentage)
        self.assertEqual(rows[2].status, "Sem contagem")
        self.assertIsNone(financial_totals((rows[2],))[2])
        self.assertIsNone(replace(sample(), stock=Decimal(0)).percentage)
        self.assertEqual(replace(sample(), stock=Decimal(0)).status, "Sem base financeira")
        self.assertEqual(replace(sample(), difference=Decimal(0)).percentage, 0)
        with self.assertRaises(ValueError):
            financial_totals(records())

    def test_company_scopes_warehouse_names_and_duplicates_are_rejected(self):
        self.assertEqual(len(validate_financial_rows(records())), 4)
        with self.assertRaises(ValueError):
            validate_financial_rows((sample(), sample()))
        for changes in ({"stock": Decimal("NaN")}, {"counted": -1}, {"month": date(2026, 9, 2)}):
            with self.assertRaises(ValueError):
                replace(sample(), **changes)

    def test_sql_reads_company_from_view_is_read_only_and_closes_on_success(self):
        connection = MagicMock()
        session = connection.__enter__.return_value
        cursor = session.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [dict(mes=sample().month, fkempresa=1, empresa="TAÍBA",
            fkalmoxarifado=1, almox="EVENTOS", estoque=1000, perda=20, sobra=10, diferenca=30,
            contados=10, diferentes=3)]
        with patch("automations.inventario.database.connection_settings", return_value={}), \
             patch("automations.inventario.database.psycopg.connect", return_value=connection):
            self.assertEqual(SqlFinancialInventoryProvider().fetch(), (sample(),))
        query = cursor.execute.call_args.args[0]
        self.assertIn("FROM cmflex.v_inventario_resumo_mensal", query)
        self.assertIn("ano_mes AS mes, empresa, almoxarifado AS almox", query)
        self.assertNotIn("JOIN", query)
        self.assertTrue(session.read_only)
        cursor.execute.assert_any_call("SET LOCAL statement_timeout = '30s'")
        connection.__exit__.assert_called_once()
        session.cursor.return_value.__exit__.assert_called_once()

    def test_sql_failure_closes_and_returns_safe_message(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = psycopg.OperationalError("private connection details")
        with patch("automations.inventario.database.connection_settings", return_value={}), \
             patch("automations.inventario.database.psycopg.connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "Não foi possível") as raised:
                SqlFinancialInventoryProvider().fetch()
        self.assertNotIn("private", str(raised.exception))
        connection.__exit__.assert_called_once()

    def test_excel_preserves_numbers_percentages_and_prevents_formulas(self):
        rows = (sample(), replace(records()[2], company="=1+1", warehouse="@test"))
        book = load_workbook(BytesIO(export_financial(rows)))
        try:
            sheet = book.active
            self.assertEqual(sheet["D4"].value, 1000)
            self.assertEqual(sheet["G4"].value, 30)
            self.assertAlmostEqual(sheet["H4"].value, .03)
            self.assertEqual(sheet["H4"].number_format, "0.00%")
            self.assertIsNone(sheet["H5"].value)
            self.assertEqual(sheet["K5"].value, "Sem contagem")
            self.assertEqual(sheet["D6"].value, 1000)
            self.assertEqual(sheet.freeze_panes, "D4")
            self.assertFalse(any(cell.data_type == "f" for row in sheet for cell in row))
        finally:
            book.close()

    def test_chart_is_weighted_and_handles_missing_zero_and_above_100_percent(self):
        for palette in (DARK, LIGHT):
            rows = (sample(), replace(sample(), warehouse="BAR", stock=Decimal(100), difference=Decimal(300)))
            chart = next(item for item in walk(impact_chart(rows, palette)) if isinstance(item, ft.BarChart))
            self.assertEqual(chart.bar_groups[0].bar_rods[0].to_y, 300)
            self.assertGreater(chart.max_y, 300)
            self.assertEqual(chart.top_axis.labels[0].label.value, "300,00%")
            self.assertTrue(chart._build_add_commands())
            empty = impact_chart((records()[2],), palette)
            self.assertFalse(any(isinstance(item, ft.BarChart) for item in walk(empty)))

    def test_panel_filters_snapshot_export_themes_resize_and_failure(self):
        page, provider = MagicMock(web=True), MagicMock()
        provider.fetch.return_value = records()
        download, width = MagicMock(return_value="/downloads/test"), MagicMock(return_value=1700)
        view = main(page, download_file=download, provider=provider, available_width=width)
        page.update.side_effect = lambda: view.control._build_add_commands()
        provider.fetch.assert_not_called()
        consult = next(item for item in walk(view.control) if isinstance(item, ft.ElevatedButton))
        asyncio.run(consult.on_click(None))
        fields = {item.label: item for item in walk(view.control) if isinstance(item, ft.Dropdown)}
        self.assertEqual(fields["Mês de referência"].value, "2026-09-01")
        fields["Empresa"].value = "CHARME"
        fields["Empresa"].on_change(None)
        table = next(item for item in walk(view.control) if isinstance(item, ft.DataTable))
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.rows[0].cells[0].content.value, "CHARME")
        export = next(item for item in walk(view.control) if isinstance(item, ft.OutlinedButton))
        export.on_click(None)
        self.assertEqual(download.call_args.args[1], "impacto-financeiro-2026-09-01.xlsx")
        width.return_value = 1900
        self.assertTrue(view.resize())
        self.assertEqual(table.width, 1900)
        self.assertFalse(view.resize())
        view.apply_theme(False)
        self.assertTrue(view.control._build_add_commands())
        provider.fetch.side_effect = RuntimeError("Falha de teste")
        with patch("automations.inventario.financial_panel.logging.getLogger"):
            asyncio.run(consult.on_click(None))
        table = next(item for item in walk(view.control) if isinstance(item, ft.DataTable))
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.rows[0].cells[0].content.color, LIGHT["text"])
        self.assertFalse(consult.disabled)

    def test_long_chart_labels_have_bounded_width_and_explicit_line_breaks(self):
        name = "CENTRAL DE EXPEDIENTE E MANUTENCAO - TAÍBA"
        rows = tuple(replace(sample(), warehouse=f"{name} {index}")
                     for index in range(8))
        for palette in (DARK, LIGHT):
            view = impact_chart(rows, palette)
            chart = next(item for item in walk(view) if isinstance(item, ft.BarChart))
            self.assertEqual(chart.bottom_axis.labels_size, 90)
            self.assertEqual(chart.height, 330)
            self.assertGreaterEqual((chart.width - 96) / len(rows), 180)
            for label in chart.bottom_axis.labels:
                box = label.label
                self.assertEqual(box.width, 140)
                self.assertEqual(box.height, 82)
                self.assertIn("\n", box.content.value)
                self.assertTrue(all(len(line) <= 18 for line in box.content.value.splitlines()))
                self.assertEqual(" ".join(box.content.value.split()), box.tooltip)
                self.assertEqual(box.content.tooltip, box.tooltip)
            self.assertTrue(view._build_add_commands())

    def test_empty_panel_and_desktop(self):
        provider = MagicMock()
        provider.fetch.return_value = ()
        view = main(MagicMock(web=True), provider=provider)
        consult = next(item for item in walk(view.control) if isinstance(item, ft.ElevatedButton))
        asyncio.run(consult.on_click(None))
        self.assertTrue(next(item for item in walk(view.control) if isinstance(item, ft.OutlinedButton)).disabled)
        self.assertTrue(view.control._build_add_commands())
        with self.assertRaises(RuntimeError):
            main(MagicMock(web=False))

    def test_navigation_is_in_header_not_inside_query_filters(self):
        from automations.inventario.panel import main as counts_panel

        for builder, financial in ((counts_panel, False), (main, True)):
            page = MagicMock(web=True)
            view = builder(page, provider=MagicMock())
            for is_dark, palette in ((True, DARK), (False, LIGHT)):
                view.apply_theme(is_dark)
                header, body = view.control.controls
                tabs = [item for item in walk(header) if isinstance(item, ft.TextButton)]
                self.assertEqual([tab.text for tab in tabs], ["Contagem de itens", "Impacto financeiro", "Plano de ação"])
                self.assertEqual(tabs[1 if financial else 0].style.bgcolor, palette["soft"])
                self.assertFalse(any(isinstance(item, ft.TextButton) and item.text == "Impacto financeiro"
                                     for item in walk(body)))
                tabs[0].on_click(None)
                page.go.assert_called_with("/inventario")
                tabs[1].on_click(None)
                page.go.assert_called_with("/inventario/financeiro")
                self.assertTrue(view.control._build_add_commands())

    def test_portal_financial_route_preserves_results_and_theme(self):
        from portal.app import main as portal
        page = MagicMock(web=True, width=1800, route="/inventario/financeiro")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.inventario.financial_panel.SqlFinancialInventoryProvider") as source:
            source.return_value.fetch.return_value = records()
            portal(page, MagicMock(), MagicMock())
            sidebar, body = roots[0].controls
            original = body.content
            consult = next(item for item in walk(body) if isinstance(item, ft.ElevatedButton))
            asyncio.run(consult.on_click(None))
            theme = next(item for item in walk(sidebar) if isinstance(item, ft.TextButton) and item.text == "Modo claro")
            theme.on_click(None)
            page.route = "/inventario"
            page.on_route_change(None)
            link = next(item for item in walk(body) if isinstance(item, ft.TextButton) and item.text == "Impacto financeiro")
            link.on_click(None)
            page.go.assert_called_with("/inventario/financeiro")
            page.route = "/inventario/financeiro"
            page.on_route_change(None)
            self.assertIs(body.content, original)
            self.assertTrue(any(isinstance(item, ft.DataTable) for item in walk(body)))
            source.return_value.fetch.assert_called_once()

    def test_financial_route_and_export_use_existing_single_use_download(self):
        from fastapi.testclient import TestClient
        from portal.web import Downloads, create_app

        store = Downloads()
        payload = export_financial((sample(),))
        path = store.issue_file(payload, "impacto-financeiro.xlsx")
        with patch("portal.web.Downloads", return_value=store), TestClient(create_app()) as client:
            self.assertEqual(client.get("/inventario/financeiro").status_code, 200)
            response = client.get(path)
            self.assertEqual(response.content, payload)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(client.get(path).status_code, 404)
