"""Read attachments on demand and render a single PDF page in memory."""

import base64
from contextlib import closing
from dataclasses import dataclass
from io import BytesIO
from threading import Lock

import psycopg
from psycopg.rows import dict_row

from automations.bordero.database import connection_settings
from automations.bordero.panel_data import ConferenceRow


MAX_FILE_BYTES = 20 * 1024 * 1024
_render_lock = Lock()  # PDFium is not thread-safe.


@dataclass(frozen=True)
class Attachment:
    id: int
    name: str
    size: int


class AttachmentSource:
    def _query(self, sql: str, params: tuple) -> list[dict]:
        try:
            with psycopg.connect(**connection_settings(), row_factory=dict_row) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '15s'")
                    cursor.execute(sql, params)
                    return cursor.fetchall()
        except psycopg.Error as error:
            raise RuntimeError("Não foi possível carregar os anexos. Tente novamente.") from error

    def list(self, row: ConferenceRow) -> tuple[Attachment, ...]:
        if row.document_id is None or row.company_id is None:
            raise ValueError("O pagamento não possui identificadores para consultar anexos.")
        records = self._query(
            "SELECT id, annomedoarquivo, octet_length(conteudo) AS size "
            "FROM cmflex.documentos_anexos "
            "WHERE iddocumentocapcarbase = %s AND fkempresa = %s ORDER BY id",
            (row.document_id, row.company_id),
        )
        return tuple(Attachment(int(item["id"]), item["annomedoarquivo"] or "Anexo", item["size"] or 0) for item in records)

    def read(self, row: ConferenceRow, attachment: Attachment) -> bytes:
        if not 0 < attachment.size <= MAX_FILE_BYTES:
            raise ValueError("Anexo vazio ou maior que 20 MB. Confira o arquivo no CMFlex.")
        records = self._query(
            "SELECT conteudo FROM cmflex.documentos_anexos "
            "WHERE id = %s AND iddocumentocapcarbase = %s AND fkempresa = %s "
            "AND octet_length(conteudo) BETWEEN 1 AND %s",
            (attachment.id, row.document_id, row.company_id, MAX_FILE_BYTES),
        )
        if not records:
            raise ValueError("O anexo não está disponível para este pagamento.")
        return bytes(records[0]["conteudo"])


def render_pdf_page(content: bytes, index: int) -> tuple[str, int]:
    import pypdfium2 as pdfium

    if len(content) > MAX_FILE_BYTES or not content.lstrip().startswith(b"%PDF-"):
        raise ValueError("Este anexo não é um PDF disponível para visualização.")
    with _render_lock:
        try:
            with pdfium.PdfDocument(content) as document:
                count = len(document)
                if not 0 <= index < count:
                    raise ValueError("Página não disponível.")
                with closing(document[index]) as page:
                    width, height = page.get_size()
                    # Bound pixel allocation even for unusually large page dimensions.
                    scale = min(3, 2400 / max(width, height))
                    with closing(page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            buffer = BytesIO()
                            image.save(buffer, format="PNG")
                return base64.b64encode(buffer.getvalue()).decode("ascii"), count
        except pdfium.PdfiumError as error:
            raise ValueError("PDF inválido ou protegido por senha. Confira no CMFlex.") from error
