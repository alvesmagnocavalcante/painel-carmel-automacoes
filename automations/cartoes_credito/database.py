"""Consulta somente leitura dos lançamentos e da contagem real de anexos."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from automations.bordero.database import connection_settings
from automations.bordero.panel_data import format_tax_id
from automations.cartoes_credito.data import CardPayment, validate_period


QUERY = """
SELECT p.iddocumentocapcarbase, p.fkempresa, p.empresa, p.annumero,
       p.favorecido, p.cpfcnpj, p.dtdatadelancamento::date AS lancamento,
       p.dtdatadevencimento::date AS vencimento,
       p.dtdataprogramada::date AS programada,
       p.vlvalormoedacorrente AS valor, p.anhistorico, p.formadepagamento,
       p.usuariolancamento, COALESCE(a.total, 0) AS contagem_anexos
FROM cmflex.pagamentos_cartao_credito p
LEFT JOIN LATERAL (
    SELECT count(d.id) AS total
    FROM cmflex.documentos_anexos d
    WHERE d.iddocumentocapcarbase = p.iddocumentocapcarbase
      AND d.fkempresa = p.fkempresa
) a ON TRUE
WHERE p.dtdatadelancamento >= %s AND p.dtdatadelancamento < %s
ORDER BY p.dtdatadelancamento DESC, p.empresa, p.annumero
"""


def _date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def map_payment(row: dict) -> CardPayment:
    return CardPayment(
        document_id=int(row["iddocumentocapcarbase"]),
        company_id=int(row["fkempresa"]),
        company=str(row.get("empresa") or "Não informada"),
        launch_number=str(row.get("annumero") or ""),
        beneficiary=str(row.get("favorecido") or "Não informado"),
        tax_id=format_tax_id(row.get("cpfcnpj")),
        launch_date=_date(row.get("lancamento")),
        due_date=_date(row.get("vencimento")),
        scheduled_date=_date(row.get("programada")),
        amount=Decimal(str(row["valor"])) if row.get("valor") is not None else None,
        history=str(row.get("anhistorico") or ""),
        payment_method=str(row.get("formadepagamento") or ""),
        responsible=str(row.get("usuariolancamento") or ""),
        attachment_count=int(row["contagem_anexos"]),
    )


class SqlCardPaymentProvider:
    def fetch(self, start: date, end: date) -> tuple[CardPayment, ...]:
        validate_period(start, end)
        try:
            with psycopg.connect(**connection_settings(), row_factory=dict_row) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '30s'")
                    cursor.execute(QUERY, (start, end + timedelta(days=1)))
                    return tuple(map_payment(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise RuntimeError("Não foi possível consultar os cartões de crédito no PostgreSQL.") from error
