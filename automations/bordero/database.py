"""Read-only source for open payments; no CMFlex writes."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from automations.bordero.panel_data import ConferenceRow, format_tax_id, validate_filters


QUERY = """
SELECT fkempresa, empresa, iddocumentocapcarbase, annumero, ancomplemento,
       favorecido, cpfcnpj, anhistorico, formadepagamento, fkformadepagamento,
       dtdatadelancamento::date AS dtlancamento,
       dtdataprogramada::date AS dtprogramada,
       dtdatadevencimento::date AS dtvencimento,
       tipodedocumento, referencia, segmento, situacaobpm, saldo,
       numerodeanexos, usuariolancamento, anexos,
       anlinhadigitavel, ancodigodebarras, nmsegmentoarquivobancario,
       vlvalormoedacorrente, vlvalororiginalmoedacorrente, vlvaloroutramoeda, saldoom
FROM cmflex.documentos_em_aberto
WHERE dtdatadevencimento >= %s AND dtdatadevencimento < %s
"""


def connection_settings() -> dict[str, object]:
    default_env = Path("/opt/prefect/.env")
    if not default_env.exists():
        default_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(os.environ.get("BORDERO_ENV_FILE", str(default_env)))
    settings: dict[str, object] = {}
    for key in ("host", "port", "dbname", "user", "password"):
        shared = "DB_NAME" if key == "dbname" else f"DB_{key.upper()}"
        dedicated = "BORDERO_DB_NAME" if key == "dbname" else f"BORDERO_DB_{key.upper()}"
        value = os.environ.get(dedicated) or os.environ.get(shared)
        if key == "password" and not value:
            value = os.environ.get("DB_PASS")
        if value:
            settings[key] = value
    missing = [key for key in ("host", "dbname", "user", "password") if key not in settings]
    if missing:
        raise ValueError("Configure a conexão do borderô: " + ", ".join(missing))
    settings.update(connect_timeout=10, application_name="bordero-panel")
    return settings


def _date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("A consulta retornou uma data inválida.")


def map_document(record: dict[str, object]) -> ConferenceRow:
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    labels = (
        ("dtlancamento", "Data do lançamento"),
        ("tipodedocumento", "Tipo de documento"),
        ("ancomplemento", "Complemento"),
        ("referencia", "Referência"),
        ("segmento", "Segmento"),
        ("anlinhadigitavel", "Linha digitável"),
        ("ancodigodebarras", "Código de barras"),
    )
    details_parts = []
    for key, label in labels:
        value = record.get(key)
        if isinstance(value, (date, datetime)):
            value = value.strftime("%d/%m/%Y")
        if value is not None and str(value).strip():
            details_parts.append(f"{label}: {value}")
    details = "\n".join(details_parts)
    return ConferenceRow(
        supplier=str(record.get("favorecido") or "Não informado"),
        tax_id=format_tax_id(record.get("cpfcnpj")),
        launch_number=str(record.get("annumero") or ""),
        company=str(record.get("empresa") or ""),
        balance=Decimal(str(record["saldo"])),
        scheduled_date=_date(record.get("dtprogramada")),
        due_date=_date(record.get("dtvencimento")),
        payment_method=str(record.get("formadepagamento") or "").strip(),
        history=str(record.get("anhistorico") or ""),
        situation="A conferir",
        responsible=str(record.get("usuariolancamento") or ""),
        attachment_count=int(record["numerodeanexos"]) if record.get("numerodeanexos") is not None else None,
        source_situation=str(record.get("situacaobpm") or "").strip(),
        attachment_names=str(record.get("anexos") or "").strip(),
        document_id=int(record["iddocumentocapcarbase"]) if record.get("iddocumentocapcarbase") is not None else None,
        company_id=int(record["fkempresa"]) if record.get("fkempresa") is not None else None,
        details=details,
        review_key=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )


class SqlConferenceProvider:
    def fetch(self, start_date: date, end_date: date, hotel: str) -> tuple[ConferenceRow, ...]:
        validate_filters(start_date, end_date, hotel)
        query = QUERY
        params: list[object] = [start_date, end_date + timedelta(days=1)]
        if hotel != "Todos":
            query += " AND empresa::text = %s"
            params.append(hotel)
        query += " ORDER BY dtdatadevencimento, empresa, annumero"
        try:
            with psycopg.connect(**connection_settings(), row_factory=dict_row) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '30s'")
                    cursor.execute(query, params)
                    return tuple(map_document(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise RuntimeError("Não foi possível consultar o PostgreSQL. Verifique conexão, permissões e disponibilidade da tabela.") from error
