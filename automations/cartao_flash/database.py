"""Database provider for CMFlex Flash corporate card transactions and attachments."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

import psycopg
from psycopg.rows import dict_row

from automations.bordero.database import connection_settings
from automations.bordero.panel_data import format_tax_id
from automations.cartao_flash.data import CmflexFlashDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlashAttachmentMeta:
    """Metadata for an attachment stored in cmflex.documentos_anexos."""

    id: int
    name: str
    size: int


class SqlFlashProvider:
    """Reads CMFlex Flash documents and attachments without writing."""

    def __init__(self, settings: dict[str, object] | None = None) -> None:
        self._settings = settings

    def _connection_params(self) -> dict[str, object]:
        if self._settings is not None:
            return self._settings
        return connection_settings()

    def fetch_documents(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        company: str | None = None,
    ) -> tuple[CmflexFlashDocument, ...]:
        """Fetch records from cmflex.historico_cartao_flash with attachment count."""
        where_clauses = ["1=1"]
        params: list[object] = []

        if start_date is not None:
            where_clauses.append("p.dtdatadelancamento >= %s")
            params.append(start_date)
        if end_date is not None:
            where_clauses.append("p.dtdatadelancamento < %s")
            params.append(end_date)
        if company and company.strip() and company.strip().casefold() != "todos":
            where_clauses.append("p.empresa ILIKE %s")
            params.append(f"%{company.strip()}%")

        where_sql = " AND ".join(where_clauses)
        sql = f"""
        SELECT p.iddocumentocapcarbase, p.fkempresa, p.empresa, p.annumero,
               p.favorecido, p.cpfcnpj, p.dtdatadelancamento::date AS dtlancamento,
               p.dtdatadevencimento::date AS dtvencimento,
               p.dtdataprogramada::date AS dtprogramada,
               p.vlvalormoedacorrente AS valor, p.saldo, p.statusdocumento,
               p.formadepagamento, p.portador_documento, p.anhistorico,
               p.idlote,
               CASE 
                   WHEN p.statusdocumento = 2 OR p.saldo = 0 THEN 'PRESTADO CONTAS'
                   WHEN p.idlote IS NOT NULL THEN 'EM LOTE / AGUARDANDO BAIXA'
                   ELSE 'PENDENTE DE PRESTAÇÃO'
               END AS situacao_cmflex,
               count(d.id) AS contagem_anexos
        FROM cmflex.historico_cartao_flash p
        LEFT JOIN cmflex.documentos_anexos d ON p.iddocumentocapcarbase = d.iddocumentocapcarbase
             AND p.fkempresa = d.fkempresa
        WHERE {where_sql}
        GROUP BY p.iddocumentocapcarbase, p.fkempresa, p.empresa, p.annumero,
                 p.favorecido, p.cpfcnpj, p.dtdatadelancamento,
                 p.dtdatadevencimento, p.dtdataprogramada,
                 p.vlvalormoedacorrente, p.saldo, p.statusdocumento,
                 p.formadepagamento, p.portador_documento, p.anhistorico, p.idlote
        ORDER BY p.dtdatadelancamento DESC, p.annumero
        """

        try:
            with psycopg.connect(**self._connection_params(), row_factory=dict_row) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute(sql, tuple(params))
                    records = cur.fetchall()
        except psycopg.Error as err:
            logger.error("Failed to query cmflex.historico_cartao_flash: %s", err)
            raise RuntimeError("Não foi possível consultar os documentos do CMFlex.") from err

        documents: list[CmflexFlashDocument] = []
        for r in records:
            doc = CmflexFlashDocument(
                document_id=int(r["iddocumentocapcarbase"]),
                company_id=int(r["fkempresa"]),
                company=str(r.get("empresa") or "").strip(),
                launch_number=str(r.get("annumero") or "").strip(),
                supplier=str(r.get("favorecido") or "").strip(),
                tax_id=format_tax_id(r.get("cpfcnpj")),
                launch_date=r.get("dtlancamento"),
                due_date=r.get("dtvencimento"),
                scheduled_date=r.get("dtprogramada"),
                amount=Decimal(str(r["valor"])) if r.get("valor") is not None else Decimal("0.00"),
                balance=Decimal(str(r["saldo"])) if r.get("saldo") is not None else Decimal("0.00"),
                document_status=int(r.get("statusdocumento") or 0),
                payment_method=str(r.get("formadepagamento") or "").strip(),
                holder=str(r.get("portador_documento") or "").strip(),
                history=str(r.get("anhistorico") or "").strip(),
                attachment_count=int(r.get("contagem_anexos") or 0),
                batch_id=str(r.get("idlote") or "").strip(),
                cmflex_situation=str(r.get("situacao_cmflex") or "").strip(),
            )
            documents.append(doc)

        return tuple(documents)

    def fetch_attachments(self, document_id: int, company_id: int) -> tuple[FlashAttachmentMeta, ...]:
        """Fetch list of attachments for a given document."""
        sql = """
        SELECT id, annomedoarquivo, octet_length(conteudo) AS size
        FROM cmflex.documentos_anexos
        WHERE iddocumentocapcarbase = %s AND fkempresa = %s
        ORDER BY id
        """
        try:
            with psycopg.connect(**self._connection_params(), row_factory=dict_row) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    cur.execute(sql, (document_id, company_id))
                    records = cur.fetchall()
        except psycopg.Error as err:
            logger.error("Failed to query attachments: %s", err)
            raise RuntimeError("Não foi possível listar os anexos do documento.") from err

        return tuple(
            FlashAttachmentMeta(
                id=int(r["id"]),
                name=str(r.get("annomedoarquivo") or "anexo.pdf"),
                size=int(r.get("size") or 0),
            )
            for r in records
        )

    def read_attachment_bytes(self, attachment_id: int) -> bytes:
        """Read the binary blob of an attachment."""
        sql = "SELECT conteudo FROM cmflex.documentos_anexos WHERE id = %s"
        try:
            with psycopg.connect(**self._connection_params(), row_factory=dict_row) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute(sql, (attachment_id,))
                    record = cur.fetchone()
        except psycopg.Error as err:
            logger.error("Failed to read attachment content: %s", err)
            raise RuntimeError("Não foi possível carregar o anexo.") from err

        if not record or not record.get("conteudo"):
            raise ValueError("O anexo selecionado está vazio ou não foi encontrado.")
        return bytes(record["conteudo"])
