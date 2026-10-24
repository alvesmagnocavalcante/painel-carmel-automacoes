"""In-memory export of the selected monthly financial snapshot."""

from openpyxl import Workbook

from automations.inventario.export import (
    _safe_text,
    apply_column_widths,
    style_header_cells,
    workbook_bytes,
)
from automations.inventario.financial import financial_totals

COLUMN_WIDTHS = {
    "A": 14, "B": 28, "C": 55, "D": 22, "E": 20, "F": 20,
    "G": 22, "H": 20, "I": 18, "J": 22, "K": 25,
}


def export_financial(rows) -> bytes:
    stock, difference, fraction = financial_totals(rows)
    workbook = Workbook()
    try:
        sheet = workbook.active
        sheet.title = "Impacto financeiro"
        sheet.append(["Impacto financeiro do inventário • Carmel Hotéis"])
        sheet.append(["Totais e percentual incluem apenas almoxarifados com contagem. Não há compensação entre perdas e sobras."])
        sheet.append(["Mês", "Empresa", "Almoxarifado", "Estoque financeiro", "Perdas", "Sobras",
                      "Diferença", "% financeiro", "Itens contados", "Itens com diferença", "Situação"])
        for item in rows:
            sheet.append([item.month, _safe_text(item.company), _safe_text(item.warehouse),
                          item.stock, item.loss, item.surplus, item.difference,
                          item.percentage, item.counted, item.different, item.status])
        sheet.append([None, "Total com contagem", None, stock,
                      sum(item.loss for item in rows if item.counted),
                      sum(item.surplus for item in rows if item.counted), difference, fraction])
        style_header_cells(sheet[3])
        for row in sheet.iter_rows(min_row=4):
            row[0].number_format = "mmm/yy"
            for cell in row[3:7]:
                cell.number_format = '"R$" #,##0.00'
            row[7].number_format = "0.00%"
        apply_column_widths(sheet, COLUMN_WIDTHS)
        sheet.freeze_panes = "D4"
        sheet.auto_filter.ref = f"A3:K{3 + len(rows)}"
        sheet.sheet_view.showGridLines = False
        return workbook_bytes(workbook)
    finally:
        workbook.close()
