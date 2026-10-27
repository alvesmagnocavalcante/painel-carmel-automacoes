"""Reconciliation engine comparing Flash card transactions against CMFlex documents."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Sequence

from automations.cartao_flash.data import (
    STATUS_PENDING_LAUNCH,
    STATUS_PENDING_SETTLEMENT,
    STATUS_SETTLED,
    CmflexFlashDocument,
    FlashReconciliationItem,
    FlashTransaction,
    normalize_text,
)

MIN_MATCH_SCORE = 20.0


def _tokenize(text: str) -> set[str]:
    """Extract significant words (length >= 3) from normalized text."""
    words = re.findall(r"[a-z0-9]{3,}", normalize_text(text))
    # Exclude very generic stop words
    stopwords = {"bra", "fortaleza", "brasil", "ltda", "comercio", "servicos", "sao", "paulo"}
    return {w for w in words if w not in stopwords}


def _overlapping_tokens(left: set[str], right: set[str]) -> set[str]:
    """Match exact or meaningful contained merchant/supplier tokens."""
    return {
        left_token
        for left_token in left
        if any(
            left_token == right_token
            or (
                min(len(left_token), len(right_token)) >= 5
                and (left_token in right_token or right_token in left_token)
            )
            for right_token in right
        )
    }


def _match_score(
    tx: FlashTransaction,
    doc: CmflexFlashDocument,
) -> float:
    """Calculate similarity score between transaction and document."""
    score = 0.0

    # 1. Company match
    if tx.hotel and normalize_text(tx.hotel) == normalize_text(doc.company):
        score += 30.0

    # 2. Textual overlap between description and supplier/history
    tx_tokens = _tokenize(tx.description)
    doc_tokens = _tokenize(f"{doc.supplier} {doc.history}")
    if tx_tokens and doc_tokens:
        common = _overlapping_tokens(tx_tokens, doc_tokens)
        overlap_ratio = len(common) / max(len(tx_tokens), 1)
        score += overlap_ratio * 50.0

    # 3. Person/Holder overlap
    tx_person = _tokenize(tx.person)
    doc_person = _tokenize(f"{doc.holder} {doc.history}")
    if tx_person and doc_person:
        common_person = _overlapping_tokens(tx_person, doc_person)
        if common_person:
            score += 20.0

    # 4. Date proximity: transactions occur on or before CMFlex launch date
    if doc.launch_date:
        diff_days = abs((doc.launch_date - tx.purchase_date).days)
        if diff_days <= 7:
            score += 15.0 - (diff_days * 1.5)
        elif diff_days <= 30:
            score += 5.0

    return score


def reconcile_flash_statement(
    transactions: Sequence[FlashTransaction],
    documents: Sequence[CmflexFlashDocument],
    overrides: dict[str, tuple[str, str]] | None = None,
) -> tuple[FlashReconciliationItem, ...]:
    """Match Flash transactions to CMFlex documents and classify each item.

    Overrides format: {transaction_key: (status, notes)}
    """
    manual_overrides = overrides or {}
    items: list[FlashReconciliationItem] = []

    # Index candidate documents by rounded amount for fast exact-match lookup
    docs_by_amount: dict[Decimal, list[CmflexFlashDocument]] = {}
    for doc in documents:
        docs_by_amount.setdefault(doc.amount, []).append(doc)

    used_document_ids: set[int] = set()

    for tx in transactions:
        if tx.is_deposit:
            continue

        candidates = docs_by_amount.get(tx.amount, [])
        available_candidates = [d for d in candidates if d.document_id not in used_document_ids]

        best_doc: CmflexFlashDocument | None = None
        best_score = -1.0

        for cand in available_candidates:
            score = _match_score(tx, cand)
            if score > best_score:
                best_score = score
                best_doc = cand

        # Decide status
        tx_key = f"{tx.purchase_date:%Y%m%d}_{tx.amount}_{normalize_text(tx.description)}_{normalize_text(tx.person)}"
        override_status, override_notes = manual_overrides.get(tx_key, ("", ""))

        if best_doc is not None and best_score >= MIN_MATCH_SCORE:
            used_document_ids.add(best_doc.document_id)
            if override_status:
                status = override_status
            else:
                status = STATUS_SETTLED if best_doc.is_settled else STATUS_PENDING_SETTLEMENT
            matched_doc = best_doc
            effective_hotel = tx.hotel or best_doc.company
        else:
            status = override_status or STATUS_PENDING_LAUNCH
            matched_doc = None
            effective_hotel = tx.hotel

        items.append(
            FlashReconciliationItem(
                transaction=tx,
                status=status,
                matched_document=matched_doc,
                manual_notes=override_notes,
                hotel=effective_hotel,
            )
        )

    return tuple(items)
