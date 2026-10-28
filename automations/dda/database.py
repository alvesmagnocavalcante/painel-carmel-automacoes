"""Database queries for CMFlex open payables and attachments."""

from __future__ import annotations

import logging
import os
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from automations.dda.data import CmflexOpenDocument


logger = logging.getLogger(__name__)


def get_db_settings() -> dict[str, object]:
    """Load database settings from environment."""
    default_env = Path("/opt/prefect/.env")
    if not default_env.exists():
        default_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(os.environ.get("DDA_ENV_FILE", str(default_env)))

    settings: dict[str, object] = {}
    for key in ("host", "port", "dbname", "user", "password"):
        shared = "DB_NAME" if key == "dbname" else f"DB_{key.upper()}"
        dedicated = "DDA_DB_NAME" if key == "dbname" else f"DDA_DB_{key.upper()}"
        value = os.environ.get(dedicated) or os.environ.get(shared)
        if key == "password" and not value:
            value = os.environ.get("DB_PASS")
        if value:
            settings[key] = value

    missing = [k for k in ("host", "dbname", "user", "password") if k not in settings]
    if missing:
        raise ValueError(f"Configuração de banco incompleta para DDA: {', '.join(missing)}")

    settings.update(connect_timeout=10, application_name="dda-panel")
    return settings


class SqlDdaProvider:
    """Provedor de dados CMFlex para conciliação do DDA."""

    def __init__(self, db_settings: dict[str, object] | None = None):
        self._db_settings = db_settings

    def _connect(self):
        settings = self._db_settings or get_db_settings()
        return psycopg.connect(**settings, row_factory=dict_row)

    def fetch_open_documents(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        hotel: str | None = None,
    ) -> tuple[CmflexOpenDocument, ...]:
        """Consulta títulos em aberto no CMFlex com contagem de anexos."""
        clauses: list[str] = []
        params: list[object] = []

        if start_date:
            clauses.append("d.dtdatadevencimento >= %s")
            params.append(start_date)
        if end_date:
            clauses.append("d.dtdatadevencimento <= %s")
            params.append(end_date)
        if hotel and hotel != "Todas":
            clauses.append("d.empresa ILIKE %s")
            params.append(f"%{hotel}%")

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
        SELECT 
            d.iddocumentocapcarbase,
            d.fkempresa,
            d.empresa,
            d.annumero,
            d.ancomplemento,
            d.favorecido,
            d.cpfcnpj,
            d.referencia,
            d.vlvalormoedacorrente,
            d.saldo,
            d.dtdatadelancamento::date as dtlancamento,
            d.dtdatadevencimento::date as dtvencimento,
            d.dtdataprogramada::date as dtprogramada,
            d.formadepagamento,
            d.tipodedocumento,
            d.usuariolancamento as responsavel,
            d.anhistorico,
            d.anlinhadigitavel,
            d.ancodigodebarras,
            d.anexos,
            count(a.id) as contagem_anexos
        FROM cmflex.documentos_em_aberto d
        LEFT JOIN cmflex.documentos_anexos a 
          ON d.iddocumentocapcarbase = a.iddocumentocapcarbase 
         AND d.fkempresa = a.fkempresa
        {where_sql}
        GROUP BY 
            d.iddocumentocapcarbase, d.fkempresa, d.empresa, d.annumero, d.ancomplemento,
            d.favorecido, d.cpfcnpj, d.referencia, d.vlvalormoedacorrente, d.saldo,
            d.dtdatadelancamento, d.dtdatadevencimento, d.dtdataprogramada, d.formadepagamento,
            d.tipodedocumento, d.usuariolancamento, d.anhistorico, d.anlinhadigitavel,
            d.ancodigodebarras, d.anexos
        ORDER BY d.dtdatadevencimento ASC, d.annumero ASC
        """

        try:
            with closing(self._connect()) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute(query, params)
                    rows = cur.fetchall()

            documents: list[CmflexOpenDocument] = []
            for r in rows:
                doc = CmflexOpenDocument(
                    document_id=int(r["iddocumentocapcarbase"]),
                    company_id=int(r["fkempresa"]),
                    company=str(r.get("empresa") or "").strip(),
                    launch_number=str(r.get("annumero") or "").strip(),
                    installment=str(r.get("ancomplemento") or "").strip(),
                    supplier=str(r.get("favorecido") or "").strip(),
                    tax_id=str(r.get("cpfcnpj") or "").strip(),
                    reference=str(r.get("referencia") or "").strip(),
                    amount=Decimal(str(r["vlvalormoedacorrente"] or "0.00")),
                    balance=Decimal(str(r["saldo"] or "0.00")),
                    launch_date=r.get("dtlancamento"),
                    due_date=r.get("dtvencimento"),
                    scheduled_date=r.get("dtprogramada"),
                    payment_method=str(r.get("formadepagamento") or "").strip(),
                    document_type=str(r.get("tipodedocumento") or "").strip(),
                    responsible=str(r.get("responsavel") or "").strip(),
                    history=str(r.get("anhistorico") or "").strip(),
                    digitable_line=str(r.get("anlinhadigitavel") or "").strip(),
                    barcode=str(r.get("ancodigodebarras") or "").strip(),
                    attachments=str(r.get("anexos") or "").strip(),
                    attachment_count=int(r.get("contagem_anexos") or 0),
                )
                documents.append(doc)

            return tuple(documents)
        except Exception as ex:
            logger.error("Erro ao consultar CMFlex para DDA: %s", ex)
            raise RuntimeError(f"Não foi possível carregar os títulos do CMFlex: {ex}") from ex

    def fetch_attachments_for_document(
        self,
        document_id: int,
        company_id: int,
    ) -> list[dict[str, object]]:
        """Consulta os anexos binários de um documento sob demanda (Consulta DDA com anexos)."""
        query = """
        SELECT id, annomedoarquivo, octet_length(conteudo) as size, conteudo
        FROM cmflex.documentos_anexos
        WHERE iddocumentocapcarbase = %s AND fkempresa = %s
        ORDER BY id
        """
        try:
            with closing(self._connect()) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute(query, (document_id, company_id))
                    return cur.fetchall()
        except Exception as ex:
            logger.error("Erro ao carregar anexo do documento %s: %s", document_id, ex)
            return []
