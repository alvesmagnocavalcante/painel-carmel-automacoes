"""Per-hotel inventory report by day; independent of database and presentation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MAX_REPORT_DAYS = 366


@dataclass(frozen=True)
class ReportRow:
    """One warehouse counted on one day."""

    day: date
    company: str
    warehouse: str
    counted: int
    different: int
    loss: Decimal
    surplus: Decimal
    stock: Decimal

    def __post_init__(self):
        amounts = (self.loss, self.surplus, self.stock)
        if (self.counted < 0 or not 0 <= self.different <= self.counted
                or any(not value.is_finite() for value in amounts)):
            raise ValueError("O banco retornou uma contagem diária inválida.")

    @property
    def difference(self) -> Decimal:
        # Same rule as the monthly financial view: losses and surpluses never offset.
        return self.loss + self.surplus

    @property
    def percentage(self) -> Decimal | None:
        return Decimal(self.different) / Decimal(self.counted) if self.counted else None

    @property
    def financial_percentage(self) -> Decimal | None:
        return self.difference / self.stock if self.counted and self.stock > 0 else None

    @property
    def status(self) -> str:
        return "Sem base financeira" if self.stock <= 0 else "Com contagem"


@dataclass(frozen=True)
class ReportTotals:
    counted: int
    different: int
    loss: Decimal
    surplus: Decimal
    difference: Decimal
    stock: Decimal

    @property
    def percentage(self) -> Decimal | None:
        return Decimal(self.different) / Decimal(self.counted) if self.counted else None

    @property
    def financial_percentage(self) -> Decimal | None:
        return self.difference / self.stock if self.counted and self.stock > 0 else None


def validate_period(start: date, end: date) -> None:
    if start > end:
        raise ValueError("A data inicial deve ser anterior ou igual à data final.")
    if (end - start).days + 1 > MAX_REPORT_DAYS:
        raise ValueError(f"Escolha um período de até {MAX_REPORT_DAYS} dias.")


def validate_report_rows(rows):
    keys = [(item.day, item.company, item.warehouse) for item in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Mais de um resultado para o mesmo dia, empresa e almoxarifado.")
    return tuple(rows)


def report_totals(rows) -> ReportTotals:
    """Stock is a monthly snapshot: count it once per warehouse and month, even when
    the same warehouse was counted on several days of the period."""
    stock_by_warehouse = {}
    for item in rows:
        if item.counted:
            stock_by_warehouse[(item.company, item.warehouse, item.day.year, item.day.month)] = item.stock
    loss = sum((item.loss for item in rows), Decimal(0))
    surplus = sum((item.surplus for item in rows), Decimal(0))
    return ReportTotals(
        sum(item.counted for item in rows), sum(item.different for item in rows),
        loss, surplus, loss + surplus, sum(stock_by_warehouse.values(), Decimal(0)))


def companies(rows) -> tuple[str, ...]:
    return tuple(sorted({item.company for item in rows}))
