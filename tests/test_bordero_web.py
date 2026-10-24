"""Offline checks for the browser download; no database access."""

from datetime import date
from io import BytesIO
import base64
import xml.etree.ElementTree as ET
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from automations.bordero.database import map_document
from portal.web import Downloads, create_app
from tests.test_bordero_database import document


class WebTests(TestCase):
    def test_browser_tab_uses_carmel_symbol(self):
        with TestClient(create_app()) as client:
            html = client.get("/").text
            self.assertIn('rel="icon" type="image/svg+xml" href="favicon-carmel.svg?v=carmel-2"', html)
            self.assertNotIn('href="favicon.png"', html)
            self.assertIn('src="flutter_bootstrap.js"', html)
            self.assertNotIn("%FLET_ROUTE_URL_STRATEGY%", html)
            self.assertIn('content="/ws"', html)
            response = client.get("/favicon-carmel.svg?v=carmel-2")
            self.assertEqual(response.status_code, 200)
            self.assertIn("image/svg+xml", response.headers["content-type"])
            icon = ET.fromstring(response.content)
            ns = {"svg": "http://www.w3.org/2000/svg"}
            self.assertEqual(icon.find("svg:rect", ns).get("fill"), "#4C3427")
            embedded = icon.find(".//svg:image", ns).get("href")
            self.assertTrue(embedded.startswith("data:image/png;base64,"))
            self.assertEqual(base64.b64decode(embedded.split(",", 1)[1]), client.get("/carmel-symbol-white.png").content)
            self.assertEqual(icon.find("svg:svg", ns).get("viewBox"), "183 166 688 381")
            self.assertIn('href="favicon-carmel.svg?v=carmel-2"', client.get("/bordero").text)

    def test_original_brand_logo_is_served(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/bordero").status_code, 200)
            response = client.get("/carmel-logo.png")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "image/png")
            self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
            for asset in ("carmel-symbol-brown.png", "carmel-symbol-white.png"):
                with self.subTest(asset=asset):
                    response = client.get(f"/{asset}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["content-type"], "image/png")
                    self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_desktop_interface_is_rejected(self):
        from types import SimpleNamespace
        from automations.bordero.panel import main

        with self.assertRaisesRegex(RuntimeError, "apenas no navegador"):
            main(SimpleNamespace(web=False), web_download=lambda *args: "")

    def test_brand_fonts_are_served_locally(self):
        with TestClient(create_app()) as client:
            for name in ("PlusJakartaSans.ttf", "Cormorant-SemiBold.ttf"):
                response = client.get(f"/fonts/{name}")
                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.content), 10000)
                self.assertEqual(response.content[:4], b"\x00\x01\x00\x00")

    def test_old_command_starts_web_server(self):
        import runpy

        with patch("portal.web.serve") as serve:
            runpy.run_module("automations.bordero.panel", run_name="__main__")
        serve.assert_called_once_with()

    def test_download_is_excel_and_single_use(self):
        store = Downloads()
        path = store.issue((map_document(document()),), date(2026, 10, 1), date(2026, 10, 5), "Todos")
        with patch("portal.web.Downloads", return_value=store):
            with TestClient(create_app()) as client:
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("attachment;", response.headers["content-disposition"])
                self.assertEqual(response.headers["cache-control"], "no-store")
                workbook = load_workbook(BytesIO(response.content))
                try:
                    self.assertEqual(workbook.active["A6"].value, "Fornecedor exemplo")
                finally:
                    workbook.close()
                self.assertEqual(client.get(path).status_code, 404)
                self.assertEqual(client.get("/downloads/unknown").status_code, 404)
                self.assertEqual(client.get("/").status_code, 200)

    def test_expired_download_is_rejected(self):
        store = Downloads()
        with patch("portal.web.monotonic", return_value=0):
            path = store.issue((map_document(document()),), date(2026, 10, 1), date(2026, 10, 5), "Todos")
        with patch("portal.web.monotonic", return_value=301):
            with self.assertRaises(HTTPException) as raised:
                store.take(path.rsplit("/", 1)[1])
        self.assertEqual(raised.exception.status_code, 404)

    def test_attachment_download_preserves_bytes_and_sanitizes_name(self):
        store = Downloads()
        path = store.issue_file(b"%PDF-original", "../nota ç\r\n.pdf")
        with patch("portal.web.Downloads", return_value=store):
            with TestClient(create_app()) as client:
                response = client.get(path)
                self.assertEqual(response.content, b"%PDF-original")
                self.assertEqual(response.headers["content-disposition"], "attachment; filename*=UTF-8''nota%20%C3%A7.pdf")
                self.assertEqual(client.get(path).status_code, 404)
