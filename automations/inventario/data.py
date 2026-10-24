"""Monthly counts and matrix totals; no database or UI dependencies."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class InventoryCount:
    month: date
    company: str
    warehouse: str
    counted: int
    different: int

    def __post_init__(self):
        if self.month.day != 1 or not 0 <= self.different <= self.counted:
            raise ValueError("A consulta retornou uma contagem mensal inválida.")

    @property
    def percentage(self) -> Decimal | None:
        return Decimal(self.different) / Decimal(self.counted) if self.counted else None


@dataclass(frozen=True)
class MatrixLine:
    label: str
    kind: str
    values: tuple[InventoryCount | None, ...]


def months_between(start: date, end: date) -> tuple[date, ...]:
    if start > end:
        raise ValueError("A data inicial deve ser anterior ou igual à data final.")
    count = (end.year - start.year) * 12 + end.month - start.month + 1
    if count > 5461:
        raise ValueError("O período excede a quantidade de meses suportada na exportação Excel.")
    first = start.year * 12 + start.month - 1
    return tuple(date((first + offset) // 12, (first + offset) % 12 + 1, 1) for offset in range(count))


def _totals(rows, months, label):
    totals = {}
    for item in rows:
        counted, different = totals.get(item.month, (0, 0))
        totals[item.month] = counted + item.counted, different + item.different
    return tuple(InventoryCount(month, label, "", *totals[month]) if month in totals else None for month in months)


def build_matrix(rows: tuple[InventoryCount, ...], months: tuple[date, ...]) -> tuple[MatrixLine, ...]:
    indexed = {}
    for item in rows:
        key = item.company, item.warehouse, item.month
        if key in indexed:
            raise ValueError("A consulta retornou mais de um resultado para o mesmo almoxarifado e mês.")
        indexed[key] = item
    lines = []
    for company in sorted({item.company for item in rows}):
        selected = tuple(item for item in rows if item.company == company)
        lines.append(MatrixLine(company, "company", _totals(selected, months, company)))
        for warehouse in sorted({item.warehouse for item in selected}):
            lines.append(MatrixLine(warehouse, "warehouse", tuple(indexed.get((company, warehouse, month)) for month in months)))
    if rows:
        lines.append(MatrixLine("Total geral", "total", _totals(rows, months, "Total geral")))
    return tuple(lines)


def month_label(month: date) -> str:
    names = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
    return f"{names[month.month - 1]}/{month.year % 100:02d}"
