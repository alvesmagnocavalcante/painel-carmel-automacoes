"""Sugestões por valor e conferência humana das transações da fatura."""

from dataclasses import dataclass
from datetime import date
import re

from automations.cartoes_credito.data import CardPayment, STATUSES
from automations.cartoes_credito.statement import BankTransaction


PaymentKey = tuple[int, int]
CARD_CHARGE_STATUS = "Encargo conferido"
TRANSACTION_FILTERS = ("Todos", "Com lançamento na busca", "Sem lançamento na busca", "Encargos")


@dataclass(frozen=True)
class BankReview:
    status: str = "A conferir"
    reason: str = ""
    payment_key: PaymentKey | None = None


def is_card_charge(transaction: BankTransaction) -> bool:
    return transaction.category == "Encargo" or bool(
        re.match(r"^(anuidade|iof)\b", transaction.description.strip(), re.IGNORECASE)
    )


def suggest_matches(transaction: BankTransaction, payments: tuple[CardPayment, ...],
                    company: str) -> tuple[CardPayment, ...]:
    if company == "Todos":
        return ()

    def distance(launch_date: date | None) -> int:
        return abs((launch_date - transaction.purchase_date).days) if launch_date else 9999

    return tuple(sorted((payment for payment in payments
                         if payment.company == company and payment.amount == transaction.amount),
                        key=lambda payment: (distance(payment.launch_date), payment.launch_number)))


def filter_transactions(transactions: tuple[BankTransaction, ...], payments: tuple[CardPayment, ...],
                        company: str, selected_filter: str) -> tuple[BankTransaction, ...]:
    if selected_filter == "Todos":
        return transactions
    if selected_filter == "Encargos":
        return tuple(item for item in transactions if is_card_charge(item))
    if selected_filter not in TRANSACTION_FILTERS or company == "Todos":
        return ()
    amounts = {payment.amount for payment in payments if payment.company == company and payment.amount is not None}
    found = selected_filter == "Com lançamento na busca"
    return tuple(item for item in transactions if (item.amount in amounts) == found)


def classify_transaction(transaction: BankTransaction, status: str, reason: str,
                         payment_key: PaymentKey | None, payments: tuple[CardPayment, ...],
                         company: str, existing: dict[int, BankReview]) -> BankReview:
    if status not in (*STATUSES, CARD_CHARGE_STATUS):
        raise ValueError("Classificação inválida.")
    reason = reason.strip()
    if status == "Pendente" and not reason:
        raise ValueError("Informe o motivo da pendência.")
    selected = next((payment for payment in payments if payment.key == payment_key), None)
    if payment_key is not None and (selected is None or selected.company != company):
        raise ValueError("Selecione um lançamento válido da empresa consultada.")
    if status == CARD_CHARGE_STATUS:
        if not is_card_charge(transaction):
            raise ValueError("Apenas anuidades, IOF e encargos do cartão podem ser conferidos sem lançamento interno.")
        if payment_key is not None:
            raise ValueError("Desmarque o lançamento interno para conferir este encargo pela fatura.")
    if status == "Conferido":
        if selected is None:
            raise ValueError("Associe um lançamento do CMFlex antes de marcar Conferido.")
        if selected.amount is None or selected.amount != transaction.amount:
            raise ValueError("O valor do CMFlex diverge da fatura. Registre como Pendente.")
        if any(row_number != transaction.row_number and review.status == "Conferido"
               and review.payment_key == payment_key for row_number, review in existing.items()):
            raise ValueError("Este lançamento do CMFlex já foi confirmado em outra linha da fatura.")
    return BankReview(status, reason if status == "Pendente" else "", payment_key)
