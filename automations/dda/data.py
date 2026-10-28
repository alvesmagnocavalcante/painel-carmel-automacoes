"""Data structures and Excel parsers for DDA reconciliation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Sequence

from openpyxl import load_workbook


STATUS_LANC = "LANÇ"
STATUS_NAO_LANC = "NÃO LANÇ."
STATUS_LANC_OC = "LANÇ OC"

ALL_STATUSES = (STATUS_LANC, STATUS_NAO_LANC, STATUS_LANC_OC)

OBS_SEM_BOLETO_E_DADOS_BAN = "SEM BOLETO E DADOS BAN."
OBS_SEM_ANEXO_E_FORMA = "SEM ANEXO E SEM FORMA DE PAGAMENTO"
OBS_SEM_BOLETO = "SEM BOLETO"
OBS_SEM_DADOS_BAN = "SEM DADOS BANCARIOS"
OBS_VALOR_DIVERGENTE = "VALOR DIVERGENTE"
OBS_SEM_ALTERACAO = "SEM ALTERAÇÃO"
OBS_OK = "OK"
OBS_NAO_LOCALIZADO = "NÃO LOCALIZADO NO ERP"


def normalize_text(value: object) -> str:
    """Normalize text removing accents, multiple spaces, and case differences."""
    if value is None:
        return ""
    text = str(value)
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def clean_tax_id(value: object) -> str:
    """Extract only digits from a CPF or CNPJ string."""
    if value is None:
        return ""
    return re.sub(r"[^0-9]", "", str(value))


def format_tax_id(value: object) -> str:
    """Format numeric CPF/CNPJ with punctuation."""
    digits = clean_tax_id(value)
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return str(value or "").strip()


def parse_date(value: object) -> date | None:
    """Parse Excel cell date which may be datetime, date, or formatted string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Try common Brazilian formats
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    # Extract date pattern if embedded in text
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


def parse_amount(value: object) -> Decimal:
    """Convert spreadsheet cell value to Decimal amount."""
    if value is None:
        return Decimal("0.00")
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))

    text = str(value).strip()
    if not text:
        return Decimal("0.00")

    # Remove currency symbol, spaces, quotes, non-breaking spaces (\xa0)
    cleaned = re.sub(r'["\'R$\s\xa0]', '', text)
    if not cleaned:
        return Decimal("0.00")

    # Check Brazilian formatting 1.234,56 vs English 1,234.56
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        val = Decimal(cleaned)
        return abs(val).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


@dataclass(frozen=True)
class DdaTransaction:
    """Single collection slip line from the bank's DDA spreadsheet."""
    sheet_name: str
    row_index: int
    company: str
    bank_code: str
    tax_id: str
    supplier: str
    document_number: str
    charge_type: str
    situation: str
    issue_date: date | None
    due_date: date | None
    amount: Decimal
    raw_amount: str = ""

    @property
    def clean_cnpj(self) -> str:
        return clean_tax_id(self.tax_id)

    @property
    def formatted_cnpj(self) -> str:
        return format_tax_id(self.tax_id)


@dataclass(frozen=True)
class CmflexOpenDocument:
    """Open payable document from CMFlex ERP (documentos_em_aberto)."""
    document_id: int
    company_id: int
    company: str
    launch_number: str
    installment: str
    supplier: str
    tax_id: str
    reference: str
    amount: Decimal
    balance: Decimal
    launch_date: date | None
    due_date: date | None
    scheduled_date: date | None
    payment_method: str
    document_type: str
    responsible: str
    history: str = ""
    digitable_line: str = ""
    barcode: str = ""
    attachments: str = ""
    attachment_count: int = 0

    @property
    def clean_cnpj(self) -> str:
        return clean_tax_id(self.tax_id)

    @property
    def formatted_cnpj(self) -> str:
        return format_tax_id(self.tax_id)

    @property
    def has_boleto_attachment(self) -> bool:
        """True if any attached filename contains 'boleto'."""
        if not self.attachments:
            return False
        return "boleto" in self.attachments.lower()


@dataclass
class DdaReconciliationItem:
    """A reconciled pair of DDA transaction and ERP document."""
    transaction: DdaTransaction
    matched_document: CmflexOpenDocument | None = None
    status: str = STATUS_NAO_LANC
    observation: str = ""
    responsible: str = ""
    custom_status: str | None = None
    custom_observation: str | None = None
    custom_responsible: str | None = None

    @property
    def effective_status(self) -> str:
        return self.custom_status if self.custom_status is not None else self.status

    @property
    def effective_observation(self) -> str:
        return self.custom_observation if self.custom_observation is not None else self.observation

    @property
    def effective_responsible(self) -> str:
        return self.custom_responsible if self.custom_responsible is not None else self.responsible

    @property
    def is_reviewed(self) -> bool:
        return any(
            x is not None for x in (self.custom_status, self.custom_observation, self.custom_responsible)
        )

    @property
    def review_key(self) -> str:
        """Unique key for storing overrides."""
        tx = self.transaction
        return f"{tx.sheet_name}:{tx.clean_cnpj}:{tx.document_number}:{tx.amount}:{tx.due_date}"


def detect_unit_name(company: str, default: str = "DDA") -> str:
    """Infer Carmel hotel unit name from company / pagador string."""
    norm = normalize_text(company)
    if "taiba" in norm:
        return "TAIBA"
    if "wind" in norm:
        return "WIND"
    if "cumbuco" in norm:
        return "CUMBUCO"
    if "magna" in norm:
        return "MAGNA"
    if "charme" in norm or "carmel resort" in norm:
        return "CHARME"
    if "cm central" in norm or "servicos administrativos" in norm or "cm servicos" in norm:
        return "CM"
    return default or "DDA"


def match_header_columns(row_values: Sequence[object]) -> dict[str, int]:
    """Identify column index mapping from a list of header values."""
    col_map: dict[str, int] = {}
    for col_idx, raw_val in enumerate(row_values):
        val = normalize_text(raw_val)
        if not val:
            continue
        if any(kw in val for kw in ("pagador", "agregado", "empresa", "sacado")):
            col_map["empresa"] = col_idx
        elif any(kw in val for kw in ("beneficiario", "favorecido", "fornecedor", "cedente")):
            col_map["fornecedor"] = col_idx
        elif any(kw in val for kw in ("cnpj", "cpf")):
            col_map["cnpj"] = col_idx
        elif any(kw in val for kw in ("venc", "vencimento")) and "ate" not in val:
            col_map["dt_vencimento"] = col_idx
        elif any(kw in val for kw in ("doc", "numero", "seu numero", "titulo")) and "banco" not in val and "beneficiario" not in val:
            col_map["documento"] = col_idx
        elif any(kw in val for kw in ("tipo", "modalidade", "especie")):
            col_map["tipo"] = col_idx
        elif any(kw in val for kw in ("situacao", "status")):
            col_map["situacao"] = col_idx
        elif any(kw in val for kw in ("emissao", "processamento")):
            col_map["dt_emissao"] = col_idx
        elif any(kw in val for kw in ("a pagar", "ate venc", "valor", "saldo", "cobrado")):
            if "valor" not in col_map or "a pagar" in val:
                col_map["valor"] = col_idx
        elif "banco" in val:
            col_map["banco"] = col_idx
        elif any(kw in val for kw in ("codigo de barras", "linha digitavel", "cod barras")):
            col_map["codigo_barras"] = col_idx
    return col_map


def parse_dda_workbook(data: bytes | BinaryIO, file_name: str = "") -> tuple[DdaTransaction, ...]:
    """Parse all sheets from a bank DDA spreadsheet (Itaú DDA export)."""
    buf = BytesIO(data) if isinstance(data, bytes) else data
    wb = load_workbook(buf, data_only=True)
    transactions: list[DdaTransaction] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if ws.max_row < 2:
            continue

        header_row_idx = None
        col_map: dict[str, int] = {}

        for r_idx in range(1, min(25, ws.max_row + 1)):
            row_vals = [cell.value for cell in ws[r_idx]]
            temp_map = match_header_columns(row_vals)
            if ("fornecedor" in temp_map or "cnpj" in temp_map) and "valor" in temp_map:
                header_row_idx = r_idx
                # openpyxl 1-based index conversion
                col_map = {k: v + 1 for k, v in temp_map.items()}
                break

        if not header_row_idx:
            # Fallback for standard layout
            header_row_idx = 1
            col_map = {
                "empresa": 1,
                "banco": 2,
                "cnpj": 3,
                "fornecedor": 4,
                "documento": 5,
                "tipo": 6,
                "situacao": 7,
                "dt_emissao": 8,
                "dt_vencimento": 9,
                "valor": 10,
            }

        banco_col = col_map.get("banco", 2)

        for r_idx in range(header_row_idx + 1, ws.max_row + 1):
            val_col_idx = col_map.get("valor", 10)
            val_cell = ws.cell(row=r_idx, column=val_col_idx).value
            if val_cell is None:
                continue

            amt = parse_amount(val_cell)
            if amt <= Decimal("0.00"):
                continue

            empresa_val = str(ws.cell(row=r_idx, column=col_map.get("empresa", 1)).value or "").strip()
            banco_val = str(ws.cell(row=r_idx, column=banco_col).value or "").strip()
            cnpj_val = str(ws.cell(row=r_idx, column=col_map.get("cnpj", 3)).value or "").strip()
            fornec_val = str(ws.cell(row=r_idx, column=col_map.get("fornecedor", 4)).value or "").strip()
            doc_val = str(ws.cell(row=r_idx, column=col_map.get("documento", 5)).value or "").strip()
            tipo_val = str(ws.cell(row=r_idx, column=col_map.get("tipo", 6)).value or "Cobrança").strip()
            sit_val = str(ws.cell(row=r_idx, column=col_map.get("situacao", 7)).value or "A pagar").strip()

            dt_emissao_cell = ws.cell(row=r_idx, column=col_map.get("dt_emissao", 8)).value if "dt_emissao" in col_map else None
            dt_venc_cell = ws.cell(row=r_idx, column=col_map.get("dt_vencimento", 9)).value if "dt_vencimento" in col_map else None

            dt_emissao = parse_date(dt_emissao_cell)
            dt_venc = parse_date(dt_venc_cell)

            if not fornec_val and not cnpj_val:
                continue

            unit = detect_unit_name(empresa_val, default=sheet_name)

            tx = DdaTransaction(
                sheet_name=unit,
                row_index=r_idx,
                company=empresa_val,
                bank_code=banco_val,
                tax_id=cnpj_val,
                supplier=fornec_val,
                document_number=doc_val,
                charge_type=tipo_val,
                situation=sit_val,
                issue_date=dt_emissao,
                due_date=dt_venc,
                amount=amt,
                raw_amount=str(val_cell),
            )
            transactions.append(tx)

    return tuple(transactions)


def parse_dda_csv(data: bytes | str, file_name: str = "") -> tuple[DdaTransaction, ...]:
    """Parse CSV text exported from Banco Itaú DDA."""
    import csv
    import io

    if isinstance(data, bytes):
        text = None
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("latin-1", errors="replace")
    else:
        text = str(data)

    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    if "\t" in sample and sample.count("\t") > sample.count(delimiter):
        delimiter = "\t"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return ()

    header_idx = None
    col_map: dict[str, int] = {}
    for idx, row in enumerate(rows[:30]):
        temp_map = match_header_columns(row)
        if ("fornecedor" in temp_map or "cnpj" in temp_map) and "valor" in temp_map:
            header_idx = idx
            col_map = temp_map
            break

    if header_idx is None:
        return ()

    transactions: list[DdaTransaction] = []
    base_sheet = Path(file_name).stem if file_name else "DDA"

    for r_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not row or all(not str(c).strip() for c in row):
            continue

        val_col = col_map.get("valor", 6)
        val_raw = row[val_col] if val_col < len(row) else None
        amt = parse_amount(val_raw)
        if amt <= Decimal("0.00"):
            continue

        empresa_val = row[col_map["empresa"]].strip() if "empresa" in col_map and col_map["empresa"] < len(row) else ""
        banco_val = row[col_map["banco"]].strip() if "banco" in col_map and col_map["banco"] < len(row) else ""
        cnpj_val = row[col_map["cnpj"]].strip() if "cnpj" in col_map and col_map["cnpj"] < len(row) else ""
        fornec_val = row[col_map["fornecedor"]].strip() if "fornecedor" in col_map and col_map["fornecedor"] < len(row) else ""
        doc_val = row[col_map["documento"]].strip() if "documento" in col_map and col_map["documento"] < len(row) else ""
        tipo_val = row[col_map["tipo"]].strip() if "tipo" in col_map and col_map["tipo"] < len(row) else "Cobrança"
        sit_val = row[col_map["situacao"]].strip() if "situacao" in col_map and col_map["situacao"] < len(row) else "A pagar"

        dt_emissao = parse_date(row[col_map["dt_emissao"]]) if "dt_emissao" in col_map and col_map["dt_emissao"] < len(row) else None
        dt_venc = parse_date(row[col_map["dt_vencimento"]]) if "dt_vencimento" in col_map and col_map["dt_vencimento"] < len(row) else None

        if not fornec_val and not cnpj_val:
            continue

        unit = detect_unit_name(empresa_val, default=base_sheet)

        tx = DdaTransaction(
            sheet_name=unit,
            row_index=r_idx,
            company=empresa_val,
            bank_code=banco_val,
            tax_id=cnpj_val,
            supplier=fornec_val,
            document_number=doc_val,
            charge_type=tipo_val,
            situation=sit_val,
            issue_date=dt_emissao,
            due_date=dt_venc,
            amount=amt,
            raw_amount=str(val_raw),
        )
        transactions.append(tx)

    return tuple(transactions)


def parse_dda_file(data: bytes | BinaryIO, file_name: str = "") -> tuple[DdaTransaction, ...]:
    """Parse DDA data from file bytes (supporting XLSX, XLS, and CSV)."""
    raw_bytes = data if isinstance(data, bytes) else data.read()
    if raw_bytes.startswith(b"PK"):
        try:
            txs = parse_dda_workbook(raw_bytes, file_name=file_name)
            if txs:
                return txs
        except Exception:
            pass

    # Fallback to CSV
    return parse_dda_csv(raw_bytes, file_name=file_name)


def parse_cmflex_export_workbook(data: bytes | BinaryIO) -> tuple[CmflexOpenDocument, ...]:
    """Parse open payables exported from CMFlex report (PagamentosEmAbertoDTO)."""
    buf = BytesIO(data) if isinstance(data, bytes) else data
    wb = load_workbook(buf, data_only=True)
    ws = wb.active
    if ws.max_row < 2:
        return ()

    header_row = [normalize_text(cell.value) for cell in ws[1]]
    col_map: dict[str, int] = {}
    for idx, col_name in enumerate(header_row, start=1):
        if not col_name:
            continue
        if "fornecedordocumento" in col_name or "cnpj" in col_name or "cpf" in col_name:
            col_map["cnpj"] = idx
        elif "fornecedornomefantasia" in col_name or "fornecedor" in col_name:
            if "fornecedor" not in col_map:
                col_map["fornecedor"] = idx
        elif "numero" in col_name and "banco" not in col_name:
            col_map["numero"] = idx
        elif "complemento" in col_name or "parcela" in col_name:
            col_map["complemento"] = idx
        elif "empresa" in col_name:
            col_map["empresa"] = idx
        elif "saldo" in col_name:
            if "saldo" not in col_map:
                col_map["saldo"] = idx
        elif "datavenc" in col_name or "vencimento" in col_name:
            col_map["dt_venc"] = idx
        elif "dataprog" in col_name or "programada" in col_name:
            col_map["dt_prog"] = idx
        elif "datalanc" in col_name or "lancamento" in col_name:
            col_map["dt_lanc"] = idx
        elif "historico" in col_name:
            col_map["historico"] = idx
        elif "formadef" in col_name or "portador" in col_name or "forma" in col_name:
            if "forma" not in col_map:
                col_map["forma"] = idx
        elif "responsavel" in col_name or "usuariolancamento" in col_name or "usuario" in col_name:
            col_map["responsavel"] = idx

    docs: list[CmflexOpenDocument] = []
    for r_idx in range(2, ws.max_row + 1):
        saldo_cell = ws.cell(row=r_idx, column=col_map.get("saldo", 14)).value
        if saldo_cell is None:
            continue
        saldo = parse_amount(saldo_cell)

        doc = CmflexOpenDocument(
            document_id=r_idx,
            company_id=0,
            company=str(ws.cell(row=r_idx, column=col_map.get("empresa", 13)).value or "").strip(),
            launch_number=str(ws.cell(row=r_idx, column=col_map.get("numero", 10)).value or "").strip(),
            installment=str(ws.cell(row=r_idx, column=col_map.get("complemento", 11)).value or "").strip(),
            supplier=str(ws.cell(row=r_idx, column=col_map.get("fornecedor", 4)).value or "").strip(),
            tax_id=str(ws.cell(row=r_idx, column=col_map.get("cnpj", 6)).value or "").strip(),
            reference="",
            amount=saldo,
            balance=saldo,
            launch_date=parse_date(ws.cell(row=r_idx, column=col_map.get("dt_lanc", 16)).value),
            due_date=parse_date(ws.cell(row=r_idx, column=col_map.get("dt_venc", 17)).value),
            scheduled_date=parse_date(ws.cell(row=r_idx, column=col_map.get("dt_prog", 18)).value),
            payment_method=str(ws.cell(row=r_idx, column=col_map.get("forma", 8)).value or "").strip(),
            document_type="",
            responsible=str(ws.cell(row=r_idx, column=col_map.get("responsavel", 32)).value or "").strip(),
            history=str(ws.cell(row=r_idx, column=col_map.get("historico", 20)).value or "").strip(),
            digitable_line="",
            barcode="",
            attachments="",
            attachment_count=0,
        )
        docs.append(doc)

    return tuple(docs)
