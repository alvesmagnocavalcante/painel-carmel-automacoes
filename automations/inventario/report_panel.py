"""Per-hotel inventory report for a chosen period of days; state is session-local."""

import asyncio
import logging
from datetime import date, timedelta

import flet as ft

from automations.inventario.action_plan import parse_date
from automations.inventario.database import SqlInventoryReportProvider
from automations.inventario.financial import currency, percentage
from automations.inventario.report import companies, report_totals, validate_period
from automations.inventario.report_export import (
    export_report_excel,
    export_report_pdf,
    report_filename,
)
from automations.inventario.view import InventoryView, TABLE_HEIGHT, inventory_header
from portal.theme import DARK, LIGHT, PRIMARY, metric_card, panel_text, style_input, surface_card


def main(page, download_file=None, *, provider=None, available_width=None):
    if not page.web:
        raise RuntimeError("O relatório do inventário funciona apenas no navegador.")
    source = provider if provider is not None else SqlInventoryReportProvider()
    rows, snapshot, dark, busy = (), None, True, False
    message, failed = "Escolha o período, consulte e selecione o hotel para ver o relatório.", False
    today = date.today()
    start_field = ft.TextField(label="Data inicial", value=(today - timedelta(days=30)).strftime("%d/%m/%Y"),
                               hint_text="DD/MM/AAAA", max_length=10, col={"xs": 12, "md": 3})
    end_field = ft.TextField(label="Data final", value=today.strftime("%d/%m/%Y"),
                             hint_text="DD/MM/AAAA", max_length=10, col={"xs": 12, "md": 3})
    hotel = ft.Dropdown(label="Hotel", options=[], col={"xs": 12, "md": 3})
    layout = ft.Column(expand=True, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def palette():
        return DARK if dark else LIGHT

    def text(value, **kwargs):
        return panel_text(value, palette(), **kwargs)

    def surface(content, **kwargs):
        return surface_card(content, palette(), **kwargs)

    def selected():
        return tuple(item for item in rows if item.company == hotel.value)

    def pick_date(field):
        def changed(event):
            field.value = event.control.value.strftime("%d/%m/%Y")
            page.update()
        page.open(ft.DatePicker(on_change=changed))

    def read_period():
        try:
            start, end = parse_date(start_field.value or ""), parse_date(end_field.value or "")
        except ValueError as error:
            raise ValueError("Informe as datas no formato DD/MM/AAAA.") from error
        if start is None or end is None:
            raise ValueError("Informe a data inicial e a data final.")
        validate_period(start, end)
        return start, end

    def table(items):
        colors = palette()
        labels = ("Data", "Almoxarifado", "Contados", "Com diferença", "% itens", "Estoque financeiro",
                  "Perdas", "Sobras", "Diferença financeira", "% financeiro")
        widths = (95, 250, 85, 105, 85, 130, 105, 105, 130, 100)
        data_rows = []
        for item in items:
            values = (f"{item.day:%d/%m/%Y}", item.warehouse, str(item.counted), str(item.different),
                      percentage(item.percentage), currency(item.stock), currency(item.loss),
                      currency(item.surplus), currency(item.difference), percentage(item.financial_percentage))
            data_rows.append(ft.DataRow(cells=[ft.DataCell(text(
                value, width=widths[index], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=value,
                color=colors["warning"] if index in (3, 8) and item.different else None,
            )) for index, value in enumerate(values)]))
        grid = ft.DataTable(columns=[ft.DataColumn(text(label, bold=True), numeric=index >= 2)
                                     for index, label in enumerate(labels)], rows=data_rows,
                            heading_row_color=colors["table"], heading_row_height=52,
                            data_row_min_height=48, data_row_max_height=60, column_spacing=14)
        return ft.Row([ft.Column([grid], height=TABLE_HEIGHT, scroll=ft.ScrollMode.ALWAYS)],
                      height=TABLE_HEIGHT, scroll=ft.ScrollMode.ALWAYS, vertical_alignment=ft.CrossAxisAlignment.START)

    def render():
        colors = palette()
        items = selected()
        totals = report_totals(items)
        for field in (start_field, end_field, hotel):
            field.disabled = busy or (field is hotel and not rows)
            style_input(field, colors)
        for field in (start_field, end_field):
            field.suffix = ft.IconButton(ft.Icons.CALENDAR_MONTH, tooltip="Selecionar data", disabled=busy,
                                         on_click=lambda _, field=field: pick_date(field))
        consult.disabled = busy
        for button in (excel_button, pdf_button):
            button.disabled = busy or not items or download_file is None
            button.color = colors["text"]
        excel_button.icon_color, pdf_button.icon_color = colors["success"], colors["danger"]
        col = {"xs": 12, "sm": 6, "lg": 4, "xl": 2}
        metrics = ft.ResponsiveRow([
            metric_card("Itens contados", str(totals.counted), ft.Icons.INVENTORY_2_OUTLINED, "info", colors, col=col, value_size=22),
            metric_card("Com diferença", str(totals.different), ft.Icons.WARNING_AMBER_ROUNDED, "warning", colors, col=col, value_size=22),
            metric_card("% itens com diferença", percentage(totals.percentage), ft.Icons.PERCENT, "money", colors, col=col, value_size=22),
            metric_card("Perdas", currency(totals.loss), ft.Icons.TRENDING_DOWN, "warning", colors, col=col, value_size=18),
            metric_card("Sobras", currency(totals.surplus), ft.Icons.TRENDING_UP, "info", colors, col=col, value_size=18),
            metric_card("% financeiro", percentage(totals.financial_percentage), ft.Icons.PERCENT, "money", colors, col=col, value_size=22),
        ], spacing=10, run_spacing=10)
        period = f"{snapshot[0]:%d/%m/%Y} a {snapshot[1]:%d/%m/%Y}" if snapshot else "Nenhuma consulta realizada"
        results = table(items) if items else ft.Container(
            text("Nenhuma contagem no período e hotel selecionados." if snapshot else "O relatório aparecerá aqui.", muted=True),
            height=TABLE_HEIGHT, alignment=ft.alignment.center)
        layout.controls = [
            inventory_header(page, colors, "Relatório do inventário por hotel",
                             "Contagens e impacto financeiro de um hotel em um período de dias.",
                             category="INVENTÁRIO • RELATÓRIO", report=True),
            ft.Container(ft.Column([
                surface(ft.Column([
                    ft.ResponsiveRow([start_field, end_field, hotel, ft.Container(consult, col={"xs": 12, "md": 3})],
                                     spacing=14, run_spacing=14),
                    text(message, color=colors["warning"] if failed else colors["muted"]),
                ], spacing=14)),
                metrics,
                surface(ft.Column([
                    ft.Row([ft.Column([text(f"{hotel.value or 'Relatório'} • contagens por dia", bold=True, size=18),
                                       text(period, muted=True)], spacing=3),
                            ft.Row([excel_button, pdf_button], wrap=True)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
                    text("Perdas e sobras não se compensam. O estoque é a posição do fim do mês, contada uma vez "
                         "por almoxarifado e mês. Os downloads trazem exatamente o que está na tela.", muted=True, size=12),
                    results,
                ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
            ], spacing=14, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                padding=20, expand=True),
        ]

    async def load(_):
        nonlocal rows, snapshot, busy, message, failed
        if busy:
            return
        busy, failed, message = True, False, "Consultando relatório…"
        render()
        page.update()
        try:
            start, end = read_period()
            received = await asyncio.to_thread(source.fetch, start, end)
            names = companies(received)
            rows, snapshot = received, (start, end)
            hotel.options = [ft.dropdown.Option(name) for name in names]
            if hotel.value not in names:
                hotel.value = names[0] if names else None
            message = (f"{len(rows)} contagens em {len(names)} hotel(is). Selecione o hotel para ver ou baixar o relatório."
                       if rows else "Nenhuma contagem encontrada no período escolhido.")
        except Exception as error:
            logging.getLogger(__name__).exception("Falha ao consultar relatório do inventário")
            failed = True
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Não foi possível consultar o relatório. Tente novamente."
        finally:
            busy = False
            render()
            page.update()

    async def download(kind):
        nonlocal busy, failed, message
        items = selected()
        if busy or not items or snapshot is None or download_file is None:
            return
        busy = True
        render()
        page.update()
        try:
            exporter = export_report_excel if kind == "xlsx" else export_report_pdf
            content = await asyncio.to_thread(exporter, items, *snapshot)
            page.launch_url(download_file(content, report_filename(hotel.value, *snapshot, kind)),
                            web_window_name="_self")
        except Exception:
            logging.getLogger(__name__).exception("Falha ao exportar relatório do inventário")
            failed, message = True, "Não foi possível gerar o arquivo. Tente novamente."
        finally:
            busy = False
            render()
            page.update()

    async def excel(_):
        await download("xlsx")

    async def pdf(_):
        await download("pdf")

    def hotel_changed(_):
        render()
        page.update()

    def apply_theme(is_dark):
        nonlocal dark
        dark = is_dark
        render()

    consult = ft.ElevatedButton("Consultar relatório", icon=ft.Icons.SEARCH, bgcolor=PRIMARY,
                                color="#FFFFFF", height=52, on_click=load)
    excel_button = ft.OutlinedButton("Baixar Excel", icon=ft.Icons.DOWNLOAD, on_click=excel)
    pdf_button = ft.OutlinedButton("Baixar PDF", icon=ft.Icons.PICTURE_AS_PDF_OUTLINED, on_click=pdf)
    hotel.on_change = hotel_changed
    render()
    return InventoryView(layout, apply_theme, lambda: False)
