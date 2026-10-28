"""Reconciliation algorithm between bank DDA transactions and CMFlex documents."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

from automations.dda.data import (
    OBS_NAO_LOCALIZADO,
    OBS_SEM_ALTERACAO,
    OBS_SEM_ANEXO_E_FORMA,
    OBS_SEM_BOLETO,
    OBS_SEM_BOLETO_E_DADOS_BAN,
    OBS_SEM_DADOS_BAN,
    OBS_VALOR_DIVERGENTE,
    STATUS_LANC,
    STATUS_LANC_OC,
    STATUS_NAO_LANC,
    CmflexOpenDocument,
    DdaReconciliationItem,
    DdaTransaction,
    clean_tax_id,
    normalize_text,
)


def _token_overlap(str1: str, str2: str) -> float:
    """Compute token Jaccard similarity between two strings."""
    tokens1 = set(normalize_text(str1).split())
    tokens2 = set(normalize_text(str2).split())
    if not tokens1 or not tokens2:
        return 0.0
    common = tokens1.intersection(tokens2)
    # Exclude common corporate stopwords
    stopwords = {"ltda", "sa", "s/a", "me", "eireli", "epp", "comercio", "servicos", "de", "e", "do", "da"}
    meaningful_common = common - stopwords
    meaningful_union = (tokens1 | tokens2) - stopwords
    if not meaningful_union:
        return len(common) / len(tokens1 | tokens2)
    return len(meaningful_common) / len(meaningful_union)


def _score_candidate(tx: DdaTransaction, doc: CmflexOpenDocument) -> float:
    """Calculate matching score between a DDA transaction and a CMFlex document."""
    score = 0.0

    # 1. Tax ID (CNPJ) match
    tx_cnpj = tx.clean_cnpj
    doc_cnpj = doc.clean_cnpj
    if tx_cnpj and doc_cnpj:
        if tx_cnpj == doc_cnpj:
            score += 100.0
        elif len(tx_cnpj) >= 8 and len(doc_cnpj) >= 8 and tx_cnpj[:8] == doc_cnpj[:8]:
            # Same CNPJ root (matriz/filial)
            score += 70.0

    # 2. Supplier name match
    name_sim = _token_overlap(tx.supplier, doc.supplier)
    if name_sim >= 0.5:
        score += 50.0 * name_sim
    elif name_sim > 0.0:
        score += 20.0 * name_sim

    # Substring check
    tx_sup_norm = normalize_text(tx.supplier)
    doc_sup_norm = normalize_text(doc.supplier)
    if tx_sup_norm and doc_sup_norm:
        if tx_sup_norm in doc_sup_norm or doc_sup_norm in tx_sup_norm:
            score += 30.0

    # 3. Document / Invoice number match
    if tx.document_number and tx.document_number != "NULL":
        doc_num_clean = tx.document_number.strip().lstrip("0")
        if doc_num_clean:
            if doc_num_clean == doc.launch_number.lstrip("0"):
                score += 40.0
            elif doc_num_clean in doc.reference or doc.launch_number in tx.document_number:
                score += 25.0

    # 4. Due date proximity
    if tx.due_date and doc.due_date:
        diff_days = abs((tx.due_date - doc.due_date).days)
        if diff_days == 0:
            score += 30.0
        elif diff_days <= 5:
            score += 20.0
        elif diff_days <= 15:
            score += 10.0
        elif diff_days <= 35:
            score += 5.0
    elif tx.due_date and doc.scheduled_date:
        diff_days = abs((tx.due_date - doc.scheduled_date).days)
        if diff_days == 0:
            score += 25.0
        elif diff_days <= 5:
            score += 15.0

    return score


def _evaluate_observation(doc: CmflexOpenDocument) -> str:
    """Determine the automatic observation/pendency for a matched document."""
    has_boleto = doc.has_boleto_attachment
    payment_method_lower = normalize_text(doc.payment_method)

    # No attachments and no payment method
    if doc.attachment_count == 0 and not doc.payment_method:
        return OBS_SEM_ANEXO_E_FORMA

    is_bank_transfer = any(
        kw in payment_method_lower
        for kw in ("transferencia", "ted", "doc", "debito em conta", "pix")
    )
    is_boleto_method = "boleto" in payment_method_lower

    if not has_boleto:
        if is_bank_transfer or not doc.payment_method:
            return OBS_SEM_BOLETO_E_DADOS_BAN
        if is_boleto_method:
            return OBS_SEM_BOLETO
        return OBS_SEM_BOLETO

    return OBS_SEM_ALTERACAO


def _evaluate_status(doc: CmflexOpenDocument) -> str:
    """Determine whether the matched document is normal or purchase order (OC)."""
    type_and_history = normalize_text(f"{doc.document_type} {doc.history}").lower()
    if "ordem de compra" in type_and_history or " oc " in type_and_history:
        return STATUS_LANC_OC
    return STATUS_LANC


def reconcile_dda(
    transactions: Sequence[DdaTransaction],
    documents: Sequence[CmflexOpenDocument],
) -> tuple[DdaReconciliationItem, ...]:
    """Reconcile a sequence of DDA transactions against CMFlex documents."""
    # Index documents by exact amounts for high performance
    by_amount: dict[Decimal, list[CmflexOpenDocument]] = {}
    by_balance: dict[Decimal, list[CmflexOpenDocument]] = {}

    for doc in documents:
        by_amount.setdefault(doc.amount, []).append(doc)
        if doc.balance != doc.amount:
            by_balance.setdefault(doc.balance, []).append(doc)

    used_docs: set[int] = set()
    reconciled: list[DdaReconciliationItem] = []

    for tx in transactions:
        candidates = by_amount.get(tx.amount, []) + by_balance.get(tx.amount, [])
        # Filter available candidates
        available_candidates = [d for d in candidates if d.document_id not in used_docs]

        best_doc: CmflexOpenDocument | None = None
        best_score = 0.0

        for cand in available_candidates:
            score = _score_candidate(tx, cand)
            if score > best_score:
                best_score = score
                best_doc = cand

        # Threshold for considering it a match:
        # A match requires at least some confirmation beyond mere value (CNPJ, name overlap, or doc num)
        # Minimum score is 15.0
        if best_doc is not None and best_score >= 15.0:
            used_docs.add(best_doc.document_id)
            status = _evaluate_status(best_doc)
            observation = _evaluate_observation(best_doc)
            responsible = best_doc.responsible or ""

            item = DdaReconciliationItem(
                transaction=tx,
                matched_document=best_doc,
                status=status,
                observation=observation,
                responsible=responsible,
            )
        else:
            # Check for divergent amount if same CNPJ and document number exists
            divergent_doc = None
            if tx.clean_cnpj and tx.document_number:
                for doc in documents:
                    if doc.document_id not in used_docs:
                        if doc.clean_cnpj == tx.clean_cnpj and doc.launch_number == tx.document_number:
                            divergent_doc = doc
                            break

            if divergent_doc is not None:
                used_docs.add(divergent_doc.document_id)
                item = DdaReconciliationItem(
                    transaction=tx,
                    matched_document=divergent_doc,
                    status=STATUS_LANC,
                    observation=OBS_VALOR_DIVERGENTE,
                    responsible=divergent_doc.responsible or "",
                )
            else:
                # Not launched in ERP
                item = DdaReconciliationItem(
                    transaction=tx,
                    matched_document=None,
                    status=STATUS_NAO_LANC,
                    observation=OBS_NAO_LOCALIZADO,
                    responsible="",
                )

        reconciled.append(item)

    return tuple(reconciled)
