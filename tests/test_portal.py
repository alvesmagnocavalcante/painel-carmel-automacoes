"""Portal navigation regressions, with no database access."""

import asyncio
from unittest import TestCase
from unittest.mock import MagicMock, patch

import flet as ft

from automations.bordero.database import map_document
from tests.test_bordero_database import document
from portal.app import main


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


class PortalTests(TestCase):
    def test_official_fonts_and_responsive_home_are_serializable(self):
        from portal.theme import FONT_BODY, FONT_DISPLAY, FONTS
        page = MagicMock(web=True, route="/", width=1600)
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        main(page, MagicMock(), MagicMock())
        self.assertEqual(page.theme.font_family, FONT_BODY)
        self.assertEqual(page.dark_theme.font_family, FONT_BODY)
        self.assertEqual(page.fonts, FONTS)
        for role in ("body_large", "body_medium", "body_small", "label_large", "label_medium", "label_small"):
            self.assertEqual(getattr(page.theme.text_theme, role).weight,
                             getattr(page.dark_theme.text_theme, role).weight)
        body = roots[0].controls[1]
        title = next(c for c in walk(body) if isinstance(c, ft.Text) and c.value == "Central de automações financeiras")
        self.assertEqual(title.font_family, FONT_DISPLAY)
        self.assertTrue(body._build_add_commands())
        page.width = 600
        page.on_resized(None)
        self.assertTrue(body._build_add_commands())

    def test_inventory_text_weights_do_not_change_with_theme(self):
        from automations.inventario.panel import main as counts
        from automations.inventario.financial_panel import main as financial
        from automations.inventario.action_panel import main as actions

        def typography(view):
            return [(item.value, item.weight, item.size, item.font_family)
                    for item in walk(view.control) if isinstance(item, ft.Text)]

        for builder in (counts, financial, actions):
            view = builder(MagicMock(web=True), provider=MagicMock())
            dark_text = typography(view)
            view.apply_theme(False)
            self.assertEqual(typography(view), dark_text)
            view.apply_theme(True)
            self.assertEqual(typography(view), dark_text)
    def test_inventory_width_follows_window_and_sidebar(self):
        from datetime import date
        from automations.inventario.data import InventoryCount

        page = MagicMock(web=True, route="/inventario", width=1600)
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.inventario.panel.SqlInventoryProvider") as source:
            source.return_value.fetch.return_value = (InventoryCount(date(2026, 1, 1), "TAÍBA", "BAR", 10, 2),)
            main(page, MagicMock(), MagicMock())
            sidebar, body = roots[0].controls
            fields = [item for item in walk(body) if isinstance(item, ft.TextField)]
            fields[0].value, fields[1].value = "01/01/2026", "28/02/2026"
            consult = next(item for item in walk(body) if isinstance(item, ft.ElevatedButton))
            asyncio.run(consult.on_click(None))
            table = next(item for item in walk(body) if isinstance(item, ft.DataTable))
            self.assertEqual(table.width, 1286)
            toggle = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Recolher menu")
            toggle.on_click(None)
            self.assertEqual(table.width, 1434)
            page.width = 1800
            page.on_resized(None)
            self.assertEqual(table.width, 1634)
            source.return_value.fetch.assert_called_once()
    def test_brand_adapts_to_theme_and_collapsed_menu(self):
        page = MagicMock(web=True, route="/")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.bordero.panel.SqlConferenceProvider") as source:
            main(page, MagicMock())
            sidebar = roots[0].controls[0]

            def images():
                return [item.src for item in walk(sidebar) if isinstance(item, ft.Image)]

            self.assertEqual(images(), ["/carmel-logo.png"])
            logo = next(item for item in walk(sidebar) if isinstance(item, ft.Image))
            self.assertEqual(logo.color, "#FFFFFF")
            self.assertEqual(logo.color_blend_mode, ft.BlendMode.SRC_IN)
            self.assertEqual((logo.width, logo.height), (188, 90))
            self.assertEqual(logo.fit, ft.ImageFit.CONTAIN)
            self.assertFalse(any(isinstance(item, ft.Text) and item.value in ("Carmel", "HOTÉIS") for item in walk(sidebar)))
            toggle = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Recolher menu")
            toggle.on_click(None)
            self.assertEqual(images(), ["/carmel-symbol-white.png"])
            theme = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Modo claro")
            theme.on_click(None)
            self.assertEqual(images(), ["/carmel-symbol-brown.png"])
            toggle = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Expandir menu")
            toggle.on_click(None)
            self.assertEqual(images(), ["/carmel-logo.png"])
            logo = next(item for item in walk(sidebar) if isinstance(item, ft.Image))
            self.assertIsNone(logo.color)
            self.assertIsNone(logo.color_blend_mode)
            brand = next(item for item in walk(sidebar) if isinstance(item, ft.Container) and item.tooltip == "Carmel Hotéis • Início")
            brand.on_click(None)
            page.go.assert_called_once_with("/")
            source.return_value.fetch.assert_not_called()

    def test_home_shows_bordero_and_inventory_without_querying_database(self):
        page = MagicMock(web=True, route="/")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.bordero.panel.SqlConferenceProvider") as source, patch("automations.inventario.panel.SqlInventoryProvider") as inventory:
            main(page, MagicMock())
            source.return_value.fetch.assert_not_called()
            inventory.return_value.fetch.assert_not_called()
        texts = [item.value for root in roots for item in walk(root) if isinstance(item, ft.Text)]
        self.assertIn("Borderô", texts)
        self.assertIn("Inventário", texts)
        self.assertIn("Central de automações financeiras", texts)
        self.assertIn("FINANCEIRO • CARMEL HOTÉIS", texts)
        self.assertFalse(any("booking" in str(text).lower() or "recebimentos" in str(text).lower() for text in texts))

    def test_inventory_navigation_theme_and_results_are_preserved(self):
        from datetime import date
        from automations.inventario.data import InventoryCount

        page = MagicMock(web=True, route="/inventario")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.bordero.panel.SqlConferenceProvider") as bordero, patch("automations.inventario.panel.SqlInventoryProvider") as source:
            source.return_value.fetch.return_value = (InventoryCount(date(2026, 1, 1), "TAÍBA", "BAR", 10, 2),)
            main(page, MagicMock(), MagicMock())
            sidebar, body = roots[0].controls
            original = body.content
            fields = [item for item in walk(body) if isinstance(item, ft.TextField)]
            fields[0].value, fields[1].value = "01/01/2026", "31/01/2026"
            consult = next(item for item in walk(body) if isinstance(item, ft.ElevatedButton))
            asyncio.run(consult.on_click(None))
            theme = next(item for item in walk(sidebar) if isinstance(item, ft.TextButton) and item.text == "Modo claro")
            theme.on_click(None)
            self.assertIs(body.content, original)
            self.assertTrue(any(isinstance(item, ft.DataTable) for item in walk(body)))
            page.route = "/bordero"
            page.on_route_change(None)
            page.route = "/inventario"
            page.on_route_change(None)
            self.assertIs(body.content, original)
            source.return_value.fetch.assert_called_once()
            bordero.return_value.fetch.assert_not_called()

    def test_navigation_preserves_conference_and_theme(self):
        page = MagicMock(web=True, route="/")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.bordero.panel.SqlConferenceProvider") as source:
            source.return_value.fetch.return_value = (map_document(document(fkempresa=4)),)
            main(page, MagicMock())
            page.route = "/bordero"
            page.on_route_change(None)
            body = roots[0].controls[1]
            bordero_layout = body.content
            consult = next(item for item in walk(body) if isinstance(item, ft.ElevatedButton) and item.text.startswith("Consultar"))
            asyncio.run(consult.on_click(None))
            table = next(item for item in walk(body) if isinstance(item, ft.DataTable))
            edit = next(cell.content for cell in table.rows[0].cells if isinstance(cell.content, ft.IconButton))
            edit.on_click(None)
            dialog = page.open.call_args.args[0]
            decision = next(item for item in walk(dialog) if isinstance(item, ft.Dropdown) and item.label == "Classificação")
            decision.value = "Conferido"
            dialog.actions[-1].on_click(None)
            page.route = "/"
            page.on_route_change(None)
            theme = next(item for root in roots for item in walk(root) if isinstance(item, ft.TextButton) and item.text == "Modo claro")
            theme.on_click(None)
            self.assertEqual(page.bgcolor, "#D8D2C8")
            page.route = "/bordero"
            page.on_route_change(None)
            self.assertIs(body.content, bordero_layout)
            table = next(item for item in walk(body) if isinstance(item, ft.DataTable))
            self.assertTrue(any(cell.content.value == "Conferido" for cell in table.rows[0].cells if isinstance(cell.content, ft.Text)))
            source.return_value.fetch.assert_called_once()

    def test_unknown_route_redirects_to_home(self):
        page = MagicMock(web=True, route="/booking")
        with patch("automations.bordero.panel.SqlConferenceProvider"):
            main(page, MagicMock())
        page.go.assert_called_once_with("/")

    def test_sidebar_collapses_without_recreating_conference(self):
        page = MagicMock(web=True, route="/bordero")
        roots = []
        page.add.side_effect = lambda *items: roots.extend(items)
        with patch("automations.bordero.panel.SqlConferenceProvider") as source:
            main(page, MagicMock())
            sidebar, body = roots[0].controls
            original = body.content
            toggle = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Recolher menu")
            toggle.on_click(None)
            self.assertEqual(sidebar.width, 76)
            self.assertIs(body.content, original)
            theme = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Modo claro")
            theme.on_click(None)
            self.assertEqual(sidebar.width, 76)
            self.assertEqual(page.bgcolor, "#D8D2C8")
            toggle = next(item for item in walk(sidebar) if isinstance(item, ft.IconButton) and item.tooltip == "Expandir menu")
            toggle.on_click(None)
            self.assertEqual(sidebar.width, 224)
            self.assertIs(body.content, original)
            source.return_value.fetch.assert_not_called()
