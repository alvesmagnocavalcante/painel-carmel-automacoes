"""Attachment linking, lazy loading, and PDF preview regressions."""

import asyncio
import base64
from io import BytesIO
from unittest import TestCase
from unittest.mock import MagicMock, PropertyMock, patch

import flet as ft
import pypdfium2 as pdfium
from PIL import Image

from automations.bordero.attachments import Attachment, AttachmentSource, render_pdf_page
from automations.bordero.attachment_view import attachment_view
from automations.bordero.database import map_document
from tests.test_bordero_database import document


def sample_pdf():
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(2):
            pdf.new_page(595, 842).close()
        output = BytesIO()
        pdf.save(output)
        return output.getvalue()


class AttachmentTests(TestCase):
    def test_mapping_keeps_document_and_company_ids(self):
        row = map_document(document(fkempresa=4))
        self.assertEqual((row.document_id, row.company_id), (123, 4))

    def test_queries_are_read_only_and_include_company_and_document(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [dict(id=7, annomedoarquivo="nota.pdf", size=100)]
        row = map_document(document(fkempresa=4))
        with patch("automations.bordero.attachments.connection_settings", return_value={}), patch("automations.bordero.attachments.psycopg.connect", return_value=connection):
            source = AttachmentSource()
            items = source.list(row)
            query, params = cursor.execute.call_args.args
            self.assertNotIn("SELECT conteudo", query)
            self.assertEqual(params, (123, 4))
            cursor.fetchall.return_value = [{"conteudo": b"file"}]
            self.assertEqual(source.read(row, items[0]), b"file")
            self.assertEqual(cursor.execute.call_args.args[1][:3], (7, 123, 4))
            self.assertTrue(connection.__enter__.return_value.read_only)

    def test_missing_or_oversized_file_is_rejected(self):
        row = map_document(document(fkempresa=4))
        source = AttachmentSource()
        with patch.object(source, "_query", return_value=[]):
            with self.assertRaises(ValueError):
                source.read(row, Attachment(1, "missing.pdf", 100))
            with self.assertRaises(ValueError):
                source.read(row, Attachment(1, "big.pdf", 21 * 1024 * 1024))

    def test_renderer_generates_png_and_checks_page_bounds(self):
        content = sample_pdf()
        encoded, count = render_pdf_page(content, 1)
        self.assertEqual(count, 2)
        with Image.open(BytesIO(base64.b64decode(encoded))) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.height, image.width)
            self.assertLessEqual(max(image.size), 2400)
            self.assertGreater(image.width, 1600)
        with self.assertRaises(ValueError):
            render_pdf_page(content, 2)
        with self.assertRaises(ValueError):
            render_pdf_page(b"not a PDF", 0)

    def test_preview_loads_only_selected_attachment_and_navigates(self):
        page = MagicMock()
        row = map_document(document(fkempresa=4))
        with patch("automations.bordero.attachment_view.AttachmentSource") as factory:
            source = factory.return_value
            source.list.return_value = (Attachment(1, "first.pdf", 100), Attachment(2, "second.pdf", 100))
            source.read.return_value = sample_pdf()
            panel, load, clear = attachment_view(page, row)
            source.list.assert_not_called()
            asyncio.run(load())
            source.read.assert_called_once_with(row, source.list.return_value[0])
            selector = panel.controls[1].controls[0]
            self.assertEqual(len(selector.options), 2)
            navigator = panel.controls[2]
            asyncio.run(navigator.controls[2].on_click(None))
            self.assertEqual(navigator.controls[1].value, "Página 2 de 2")
            selector.value = "2"
            asyncio.run(selector.on_change(None))
            self.assertEqual(source.read.call_args.args[1].id, 2)
            clear()

    def test_zoom_enlarges_preview_without_reading_database_again(self):
        with patch("automations.bordero.attachment_view.AttachmentSource") as factory:
            source = factory.return_value
            source.list.return_value = (Attachment(1, "nota.pdf", 100),)
            source.read.return_value = sample_pdf()
            panel, load, clear = attachment_view(MagicMock(), map_document(document(fkempresa=4)))
            asyncio.run(load())
            toolbar = panel.controls[2]
            viewer = panel.controls[-1].controls[1]
            self.assertIsInstance(viewer, ft.InteractiveViewer)
            self.assertTrue(viewer.pan_enabled)
            self.assertFalse(viewer.constrained)
            self.assertFalse(viewer.scale_enabled)
            self.assertEqual(viewer.clip_behavior, ft.ClipBehavior.HARD_EDGE)
            self.assertTrue(viewer.visible)
            image = viewer.content.content
            self.assertEqual(image.width, 800)
            zoom_in = toolbar.controls[6]
            for _ in range(8):
                zoom_in.on_click(None)
            self.assertEqual(image.width, 1600)
            self.assertEqual(toolbar.controls[5].value, "200%")
            self.assertTrue(zoom_in.disabled)
            for _ in range(10):
                toolbar.controls[4].on_click(None)
            self.assertEqual(image.width, 400)
            self.assertTrue(toolbar.controls[4].disabled)
            with patch.object(ft.InteractiveViewer, "uid", new_callable=PropertyMock, return_value="preview"), patch.object(viewer, "reset") as reset:
                toolbar.controls[7].on_click(None)
                reset.assert_called_once_with(animation_duration=150)
            self.assertEqual(image.width, 800)
            source.read.assert_called_once()
            source.list.assert_called_once()
            clear()
            zoom_in.on_click(None)
            self.assertEqual(image.width, 800)
            self.assertFalse(image.src_base64)
            self.assertFalse(viewer.visible)

    def test_flet_can_build_preview_before_loading_on_error_and_after_close(self):
        page = MagicMock()
        with patch("automations.bordero.attachment_view.AttachmentSource") as factory:
            source = factory.return_value
            source.list.return_value = (Attachment(1, "nota.pdf", 100),)
            source.read.return_value = sample_pdf()
            panel, load, clear = attachment_view(page, map_document(document(fkempresa=4)))
            # Exercise the same Flet serialization used by page.open/update;
            # a mocked Page alone would not catch before_update assertions.
            page.update.side_effect = lambda: panel._build_add_commands()
            self.assertTrue(panel._build_add_commands())
            viewer = panel.controls[-1].controls[1]
            self.assertTrue(viewer.content.visible)
            self.assertFalse(viewer.content.content.visible)
            asyncio.run(load())
            self.assertTrue(viewer.visible)
            source.read.return_value = b"not a PDF"
            with patch("automations.bordero.attachment_view.logging.getLogger"):
                asyncio.run(panel.controls[1].controls[0].on_change(None))
            self.assertFalse(viewer.visible)
            self.assertTrue(panel._build_add_commands())
            clear()
            self.assertTrue(panel._build_add_commands())

    def test_no_attachment_shows_clear_message(self):
        with patch("automations.bordero.attachment_view.AttachmentSource") as factory:
            factory.return_value.list.return_value = ()
            panel, load, clear = attachment_view(MagicMock(), map_document(document(fkempresa=4)))
            asyncio.run(load())
            self.assertIn("Nenhum anexo", panel.controls[-1].controls[0].value)
            factory.return_value.read.assert_not_called()
            clear()
