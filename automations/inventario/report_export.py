"""Excel and PDF downloads of the per-hotel inventory report."""

import re
import unicodedata
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from automations.inventario.action_export import LOGO
from automations.inventario.export import (
    HEADER_FILL,
    _safe_text,
    apply_column_widths,
    style_header_cells,
    workbook_bytes,
)
from automations.inventario.financial import currency, percentage
from automations.inventario.report import report_totals

HEADERS = ("Data", "Almoxarifado", "Itens contados", "Itens com diferença", "% itens com diferença",
           "Estoque financeiro", "Perdas", "Sobras", "Diferença financeira", "% financeiro", "Situação")
COLUMN_WIDTHS = {"A": 14, "B": 46, "C": 16, "D": 18, "E": 20, "F": 20, "G": 16, "H": 16, "I": 20, "J": 15, "K": 20}
NOTE = ("Perdas e sobras não se compensam. O estoque financeiro é a posição do fim do mês e entra uma "
        "vez por almoxarifado e mês. O percentual financeiro é a diferença sobre esse estoque.")


def report_filename(company: str, start: date, end: date, extension: str) -> str:
    plain = unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "hotel"
    return f"relatorio-inventario-{slug}-{start:%Y%m%d}-{end:%Y%m%d}.{extension}"


def _require(rows):
    if not rows:
        raise ValueError("Não existem contagens no período para exportar.")
    if len({item.company for item in rows}) != 1:
        raise ValueError("O relatório é individual: selecione um único hotel.")


def export_report_excel(rows, start: date, end: date) -> bytes:
    _require(rows)
    totals = report_totals(rows)
    workbook = Workbook()
    try:
        sheet = workbook.active
        sheet.title = "Relatório do inventário"
        sheet.merge_cells("A1:K1")
        sheet["A1"] = f"CARMEL HOTÉIS | RELATÓRIO DE INVENTÁRIO - {rows[0].company}"
        sheet["A1"].font = Font(name="Calibri", size=18, bold=True, color="FFFFFF")
        sheet["A1"].fill = HEADER_FILL
        sheet.row_dimensions[1].height = 34
        sheet["A2"] = f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y} • Emitido em {date.today():%d/%m/%Y}"
        sheet["A3"] = NOTE
        for column, (label, value, kind) in enumerate((
                ("Itens contados", totals.counted, "0"), ("Com diferença", totals.different, "0"),
                ("% itens com diferença", totals.percentage, "0.00%"),
                ("Perdas", totals.loss, '"R$" #,##0.00'), ("Sobras", totals.surplus, '"R$" #,##0.00'),
                ("Diferença financeira", totals.difference, '"R$" #,##0.00'),
                ("Estoque contado", totals.stock, '"R$" #,##0.00'),
                ("% financeiro", totals.financial_percentage, "0.00%")), 1):
            sheet.cell(5, column, label).font = Font(bold=True, color="4C3427")
            cell = sheet.cell(6, column, value)
            cell.font, cell.number_format = Font(size=14, bold=True, color="4C3427"), kind
        header_row = 9
        for column, label in enumerate(HEADERS, 1):
            sheet.cell(header_row, column, label)
        style_header_cells(sheet[header_row][:len(HEADERS)],
                           alignment=Alignment(wrap_text=True, vertical="center", horizontal="center"))
        sheet.row_dimensions[header_row].height = 32
        for row, item in enumerate(rows, header_row + 1):
            values = (item.day, _safe_text(item.warehouse), item.counted, item.different, item.percentage,
                      item.stock, item.loss, item.surplus, item.difference, item.financial_percentage, item.status)
            for column, value in enumerate(values, 1):
                sheet.cell(row, column, value)
            sheet.cell(row, 1).number_format = "dd/mm/yyyy"
            for column in (5, 10):
                sheet.cell(row, column).number_format = "0.00%"
            for column in (6, 7, 8, 9):
                sheet.cell(row, column).number_format = '"R$" #,##0.00'
        last = header_row + len(rows)
        total_row = last + 1
        for column, value in enumerate((None, "Total do período", totals.counted, totals.different,
                                        totals.percentage, totals.stock, totals.loss, totals.surplus,
                                        totals.difference, totals.financial_percentage, None), 1):
            cell = sheet.cell(total_row, column, value)
            cell.font, cell.fill = Font(bold=True, color="151311"), PatternFill("solid", fgColor="DBD4CA")
        for column in (5, 10):
            sheet.cell(total_row, column).number_format = "0.00%"
        for column in (6, 7, 8, 9):
            sheet.cell(total_row, column).number_format = '"R$" #,##0.00'
        apply_column_widths(sheet, COLUMN_WIDTHS)
        sheet.freeze_panes = f"C{header_row + 1}"
        sheet.auto_filter.ref = f"A{header_row}:K{last}"
        sheet.sheet_view.showGridLines = False
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.print_title_rows = f"{header_row}:{header_row}"
        return workbook_bytes(workbook)
    finally:
        workbook.close()


def export_report_pdf(rows, start: date, end: date) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    _require(rows)
    totals = report_totals(rows)
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("ReportCell", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10)
    head = ParagraphStyle("ReportHead", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    paragraph = lambda value, style=cell: Paragraph(escape(str(value)), style)
    story = [Paragraph(escape(f"Relatório de inventário - {rows[0].company}"), styles["Title"]),
             paragraph(f"Carmel Hotéis | Período: {start:%d/%m/%Y} a {end:%d/%m/%Y} | Emitido em {date.today():%d/%m/%Y}"),
             Spacer(1, 4 * mm)]
    if LOGO.is_file():
        logo = Image(str(LOGO), width=40 * mm, height=17 * mm, kind="proportional")
        logo.hAlign = "LEFT"
        story.insert(0, logo)
    summary = LongTable([[paragraph(label, head) for label in (
        "Itens contados", "Com diferença", "% itens", "Perdas", "Sobras", "Diferença", "% financeiro")],
        [paragraph(value) for value in (
            totals.counted, totals.different, percentage(totals.percentage), currency(totals.loss),
            currency(totals.surplus), currency(totals.difference), percentage(totals.financial_percentage))]],
        hAlign="LEFT")
    summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C3427")),
                                 ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F5F2ED")),
                                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    labels = ("Data", "Almoxarifado", "Contados", "Com dif.", "% itens", "Estoque", "Perdas", "Sobras", "Diferença", "% fin.")
    lines = [[paragraph(label, head) for label in labels]]
    for item in rows:
        lines.append([paragraph(value) for value in (
            f"{item.day:%d/%m/%Y}", item.warehouse, item.counted, item.different, percentage(item.percentage),
            currency(item.stock), currency(item.loss), currency(item.surplus), currency(item.difference),
            percentage(item.financial_percentage))])
    lines.append([paragraph(value, head) for value in (
        "", "Total do período", totals.counted, totals.different, percentage(totals.percentage),
        currency(totals.stock), currency(totals.loss), currency(totals.surplus), currency(totals.difference),
        percentage(totals.financial_percentage))])
    table = LongTable(lines, repeatRows=1, hAlign="LEFT", colWidths=[
        22 * mm, 66 * mm, 18 * mm, 16 * mm, 16 * mm, 28 * mm, 24 * mm, 24 * mm, 24 * mm, 16 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C3427")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#9F9385")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.HexColor("#F5F2ED"), colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#DBD4CA")),
    ]))
    story.extend([summary, Spacer(1, 5 * mm), table, Spacer(1, 4 * mm), paragraph(NOTE)])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#4C3427"))
        canvas.drawString(14 * mm, 9 * mm, "Carmel Hotéis | Relatório de inventário")
        canvas.drawRightString(283 * mm, 9 * mm, f"Página {doc.page}")
        canvas.restoreState()

    output = BytesIO()
    SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                      topMargin=14 * mm, bottomMargin=16 * mm, title="Relatório de inventário",
                      author="Carmel Hotéis").build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
