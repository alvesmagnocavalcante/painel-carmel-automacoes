"""Parameterized read-only aggregation; the existing inventory ETL is untouched."""

import os
from decimal import Decimal
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from automations.inventario.data import InventoryCount, months_between
from automations.inventario.financial import FinancialInventory, validate_financial_rows


QUERY = """
SELECT date_trunc('month', dtdata)::date AS mes,
       empresa, almox,
       COUNT(DISTINCT fkartigo) AS itens_contados,
       COUNT(DISTINCT fkartigo) FILTER (WHERE dif <> 0) AS itens_com_diferenca
FROM cmflex.inventario_fisico
WHERE dtdata IS NOT NULL
"""


def connection_settings() -> dict:
    module_root = Path(__file__).resolve().parents[2]
    candidates = (Path("/opt/prefect/.env"), module_root / ".env")
    default = next((path for path in candidates if path.is_file()), module_root / ".env")
    load_dotenv(os.getenv("INVENTARIO_ENV_FILE") or os.getenv("BORDERO_ENV_FILE") or str(default))
    settings = {}
    for key in ("host", "port", "dbname", "user", "password"):
        suffix = "NAME" if key == "dbname" else key.upper()
        value = os.getenv(f"INVENTARIO_DB_{suffix}") or os.getenv(f"DB_{suffix}") or os.getenv(f"BORDERO_DB_{suffix}")
        if key == "password" and not value:
            value = os.getenv("DB_PASS")
        if value:
            settings[key] = value
    missing = [key for key in ("host", "dbname", "user", "password") if key not in settings]
    if missing:
        raise ValueError("Configure a conexão do inventário: " + ", ".join(missing))
    settings.update(connect_timeout=10, application_name="inventario-panel")
    return settings


def _query_records(query: str, params: tuple = (), *, error_message: str) -> list[dict]:
    """Keep both inventory providers on the same read-only connection lifecycle."""
    try:
        with psycopg.connect(**connection_settings(), row_factory=dict_row) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '30s'")
                cursor.execute(query, params)
                return cursor.fetchall()
    except psycopg.Error as error:
        raise RuntimeError(error_message) from error


class SqlInventoryProvider:
    def fetch(self, start: date | None = None, end: date | None = None, company: str = "Todos") -> tuple[InventoryCount, ...]:
        if (start is None) != (end is None):
            raise ValueError("Informe os dois limites do período ou nenhum deles.")
        query, params = QUERY, []
        if start is not None:
            months_between(start, end)
            query += " AND dtdata >= %s AND dtdata < %s"
            params.extend((start, end + timedelta(days=1)))
        if company != "Todos":
            query += " AND empresa = %s"
            params.append(company)
        query += " GROUP BY date_trunc('month', dtdata)::date, empresa, almox ORDER BY empresa, almox, mes"
        records = _query_records(query, tuple(params), error_message=
            "Não foi possível consultar o inventário. Verifique a conexão e tente novamente.")
        return tuple(InventoryCount(item["mes"], str(item["empresa"] or "Não informada"),
                                    str(item["almox"] or "Não informado"),
                                    int(item["itens_contados"]), int(item["itens_com_diferenca"]))
                     for item in records)


# The view now exposes the company. Keep financial business rules in the DB.
FINANCIAL_QUERY = """
SELECT ano_mes AS mes, empresa, almoxarifado AS almox,
       valor_financeiro AS estoque, perda, sobra,
       valor_diferenca AS diferenca,
       itens_contados AS contados, itens_com_diferenca AS diferentes
FROM cmflex.v_inventario_resumo_mensal
WHERE ano_mes IS NOT NULL
"""


class SqlFinancialInventoryProvider:
    def fetch(self) -> tuple[FinancialInventory, ...]:
        records = _query_records(FINANCIAL_QUERY + " ORDER BY ano_mes, empresa, almoxarifado",
            error_message="Não foi possível consultar o impacto financeiro. Tente novamente.")
        return validate_financial_rows(tuple(FinancialInventory(
            month=item["mes"], company=str(item["empresa"] or "Não informada"),
            warehouse=str(item["almox"] or "Não informado"),
            stock=Decimal(item["estoque"]), loss=Decimal(item["perda"]),
            surplus=Decimal(item["sobra"]), difference=Decimal(item["diferenca"]),
            counted=int(item["contados"]), different=int(item["diferentes"]),
        ) for item in records))
