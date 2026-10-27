"""Attachment handling and in-memory PDF rendering for Flash card documents."""

from __future__ import annotations

import base64
from contextlib import closing
from io import BytesIO
from threading import Lock

MAX_FILE_BYTES = 20 * 1024 * 1024
_render_lock = Lock()


def render_pdf_page(content: bytes, index: int) -> tuple[str, int]:
    """Render a single PDF page into base64 PNG in memory without touching disk."""
    import pypdfium2 as pdfium

    if len(content) > MAX_FILE_BYTES or not content.lstrip().startswith(b"%PDF-"):
        raise ValueError("Este anexo não é um PDF válido para visualização.")
    with _render_lock:
        try:
            with pdfium.PdfDocument(content) as document:
                count = len(document)
                if not 0 <= index < count:
                    raise ValueError("Página não disponível.")
                with closing(document[index]) as page:
                    width, height = page.get_size()
                    scale = min(3, 2400 / max(width, height))
                    with closing(page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            buffer = BytesIO()
                            image.save(buffer, format="PNG")
                return base64.b64encode(buffer.getvalue()).decode("ascii"), count
        except pdfium.PdfiumError as error:
            raise ValueError("PDF inválido ou protegido por senha. Confira no CMFlex.") from error
