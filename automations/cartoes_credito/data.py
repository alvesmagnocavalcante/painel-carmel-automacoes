"""Dados e regras de conferência de lançamentos de cartão de crédito."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
import re
import unicodedata


STATUSES = ("A conferir", "Conferido", "Pendente")


@dataclass(frozen=True)
class CardPayment:
    document_id: int
    company_id: int
    company: str
    launch_number: str
    beneficiary: str
    tax_id: str
    launch_date: date | None
    due_date: date | None
    scheduled_date: date | None
    amount: Decimal | None
    history: str
    payment_method: str
    responsible: str
    attachment_count: int
    situation: str = "A conferir"
    pending_reason: str = ""

    @property
    def key(self) -> tuple[int, int]:
        return self.company_id, self.document_id


def validate_period(start: date, end: date) -> None:
    if start > end:
        raise ValueError("A data inicial não pode ser posterior à data final.")
    if (end - start).days > 366:
        raise ValueError("O período máximo permitido é de 366 dias.")


def classify(payment: CardPayment, status: str, reason: str = "") -> CardPayment:
    if status not in STATUSES:
        raise ValueError("Classificação inválida.")
    reason = reason.strip()
    if status == "Pendente" and not reason:
        raise ValueError("Informe o motivo da pendência.")
    return replace(payment, situation=status, pending_reason=reason if status == "Pendente" else "")


def filter_payments(rows: tuple[CardPayment, ...], company: str, search: str) -> tuple[CardPayment, ...]:
    def normalize(value: str) -> str:
        return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                       if not unicodedata.combining(char))

    term = normalize(search.strip())
    digits = re.sub(r"\D", "", term) if re.fullmatch(r"[0-9.\-/\s]+", term) else ""
    return tuple(row for row in rows if (company == "Todos" or row.company == company)
                 and (not term or any(term in normalize(value) for value in
                                      (row.company, row.beneficiary, row.tax_id, row.launch_number, row.history))
                      or bool(digits and digits in re.sub(r"\D", "", row.tax_id))))
