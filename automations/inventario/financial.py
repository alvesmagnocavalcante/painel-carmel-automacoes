"""Monthly financial inventory values, independent of database and presentation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class FinancialInventory:
    month: date
    company: str
    warehouse: str
    stock: Decimal
    loss: Decimal
    surplus: Decimal
    difference: Decimal
    counted: int
    different: int

    def __post_init__(self):
        amounts = (self.stock, self.loss, self.surplus, self.difference)
        if (self.month.day != 1 or self.counted < 0 or self.different < 0
                or any(not value.is_finite() for value in amounts)):
            raise ValueError("O banco retornou valores financeiros inválidos.")

    @property
    def percentage(self) -> Decimal | None:
        # A financial snapshot alone does not mean an inventory was performed.
        return self.difference / self.stock if self.counted and self.stock > 0 else None

    @property
    def status(self) -> str:
        if not self.counted:
            return "Sem contagem"
        return "Sem base financeira" if self.stock <= 0 else "Com contagem"


def validate_financial_rows(rows):
    keys = [(item.month, item.company, item.warehouse) for item in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Mais de um resultado para a mesma empresa, almoxarifado e mês.")
    return tuple(rows)


def financial_totals(rows):
    """Monthly weighted impact, restricted to warehouses with actual counts."""
    if len({item.month for item in rows}) > 1:
        raise ValueError("Selecione apenas um mês para totalizar o impacto financeiro.")
    counted = tuple(item for item in rows if item.counted)
    stock = sum((item.stock for item in counted), Decimal(0))
    difference = sum((item.difference for item in counted), Decimal(0))
    return stock, difference, difference / stock if counted and stock > 0 else None


def currency(value: Decimal) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def percentage(value: Decimal | None) -> str:
    return f"{value * 100:.2f}%".replace(".", ",") if value is not None else "—"
