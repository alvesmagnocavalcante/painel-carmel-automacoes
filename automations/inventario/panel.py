"""Monthly inventory view; keeps consultation state within the browser session."""

import asyncio
import logging
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

import flet as ft

from automations.inventario.charts import company_chart
from automations.inventario.data import build_matrix, month_label, months_between
from automations.inventario.database import SqlInventoryProvider
from automations.inventario.export import export_inventory
from automations.inventario.view import InventoryView, TABLE_HEIGHT, inventory_header
from portal.theme import DARK, LIGHT, PRIMARY, metric_card, panel_text, style_input, surface_card


def _percentage(value):
    return f"{value * 100:.2f}%".replace(".", ",") if value is not None else "—"


def main(page, download_file=None, *, provider=None, available_width=None) -> InventoryView:
    if not page.web:
        raise RuntimeError("O inventário funciona apenas no navegador.")
    source = provider if provider is not None else SqlInventoryProvider()
    dark = True
    rows = ()
    snapshot = None
    busy = False
    message = "Consulte todos os meses disponíveis ou ative o filtro de período."
    message_error = False
    table_body = None
    table_months = 0
    today = date.today()
    start_field = ft.TextField(label="Mês inicial", value=f"01/{today.year}",
                               hint_text="MM/AAAA", max_length=7, col={"xs": 12, "md": 4})
    end_field = ft.TextField(label="Mês final", value=today.strftime("%m/%Y"),
                             hint_text="MM/AAAA", max_length=7, col={"xs": 12, "md": 4})
    period_enabled = ft.Checkbox(label="Filtrar período", value=False)
    period_controls = ft.ResponsiveRow([start_field, end_field], visible=False, spacing=14, run_spacing=14)
    snapshot_all = False
    company_field = ft.Dropdown(label="Empresa", value="Todos", options=[ft.dropdown.Option("Todos")],
                                col={"xs": 12, "md": 3})
    layout = ft.Column(expand=True, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def palette():
        return DARK if dark else LIGHT

    def shown():
        return rows if company_field.value == "Todos" else tuple(item for item in rows if item.company == company_field.value)

    def text(value, **kwargs):
        return panel_text(value, palette(), **kwargs)

    def surface(content, **kwargs):
        return surface_card(content, palette(), **kwargs)

    def table_width(month_count):
        available = available_width() if available_width is not None else (page.width - 90 if isinstance(page.width, (int, float)) else 0)
        available = available if isinstance(available, (int, float)) else 0
        return max(available, 440 + month_count * 300)

    def resize():
        if table_body is None:
            return False
        width = table_width(table_months)
        if table_body.width == width:
            return False
        table_body.width = table_body.controls[0].width = width
        return True

    def table(selected, months):
        nonlocal table_body, table_months
        colors = palette()
        lines = build_matrix(selected, months)
        columns = [ft.DataColumn(text("Empresa / Almoxarifado", bold=True))]
        for month in months:
            for label in ("Contados", "Com diferença", "% diferença"):
                columns.append(ft.DataColumn(ft.Column([text(month_label(month), bold=True), text(label, size=12)],
                                                       spacing=2, tight=True), numeric=True))
        data_rows = []
        for line in lines:
            bold = line.kind != "warehouse"
            cells = [ft.DataCell(text(line.label, bold=bold))]
            for item in line.values:
                values = (str(item.counted), str(item.different), _percentage(item.percentage)) if item else ("—", "—", "—")
                for index, value in enumerate(values):
                    color = colors["warning"] if index and item and item.different else colors["text"]
                    cells.append(ft.DataCell(text(value, bold=bold, color=color)))
            row_color = colors["info_soft"] if line.kind == "company" else colors["soft"] if line.kind == "total" else None
            data_rows.append(ft.DataRow(cells=cells, color=row_color))
        data_table = ft.DataTable(columns=columns, rows=data_rows, heading_row_height=64,
                                  heading_row_color=colors["table"], column_spacing=24,
                                  data_row_min_height=52, data_row_max_height=52,
                                  width=table_width(len(months)))
        table_months = len(months)
        table_body = ft.Column([data_table], height=TABLE_HEIGHT, width=data_table.width,
                               scroll=ft.ScrollMode.ALWAYS, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        return ft.Row([table_body], height=TABLE_HEIGHT, scroll=ft.ScrollMode.ALWAYS,
                      vertical_alignment=ft.CrossAxisAlignment.START)

    def render():
        nonlocal table_body
        table_body = None
        colors = palette()
        period_controls.visible = clear_button.visible = bool(period_enabled.value)
        period_enabled.disabled = clear_button.disabled = consult_button.disabled = busy
        period_enabled.label_style = ft.TextStyle(color=colors["text"])
        period_enabled.check_color, period_enabled.active_color = "#FFFFFF", PRIMARY
        clear_button.color = colors["accent"]
        for control in (start_field, end_field, company_field):
            control.disabled = busy
            style_input(control, colors)
        start_field.prefix = ft.Icon(ft.Icons.CALENDAR_MONTH, color=colors["info"])
        end_field.prefix = ft.Icon(ft.Icons.EVENT_AVAILABLE, color=colors["info"])
        selected = shown()
        download_button.disabled = busy or not selected or snapshot is None or download_file is None
        download_button.icon_color = colors["success"]
        single_company = len({item.company for item in selected}) == 1
        total_counted = sum(item.counted for item in selected)
        total_different = sum(item.different for item in selected)
        percent = Decimal(total_different) / Decimal(total_counted) if total_counted else None
        col = {"xs": 12, "sm": 4}
        metrics = ft.ResponsiveRow([
            metric_card("Contados no período", str(total_counted), ft.Icons.INVENTORY_2_OUTLINED, "info", colors, col=col, value_size=23),
            metric_card("Com diferença", str(total_different), ft.Icons.WARNING_AMBER_ROUNDED, "warning", colors, col=col, value_size=23),
            metric_card("Percentual de diferença", _percentage(percent), ft.Icons.PERCENT, "money", colors, col=col, value_size=23),
        ], spacing=14, run_spacing=14)
        results = table(selected, months_between(*snapshot)) if selected and snapshot else ft.Container(
            text("Nenhum inventário no período e empresa selecionados." if snapshot else "Os resultados da consulta aparecerão aqui.", muted=True),
            padding=28, height=TABLE_HEIGHT, alignment=ft.alignment.center)
        period = (f"Todos os meses disponíveis • {month_label(snapshot[0])} a {month_label(snapshot[1])}"
                  if snapshot and snapshot_all else f"{snapshot[0]:%d/%m/%Y} a {snapshot[1]:%d/%m/%Y}" if snapshot else "Nenhuma consulta realizada")
        layout.controls = [
            inventory_header(page, colors, "Conferência de inventário", "Resumo mensal por empresa e almoxarifado."),
            ft.Container(ft.Column([
                surface(ft.Column([
                    text("Filtros da consulta", bold=True, size=18),
                    ft.ResponsiveRow([company_field, ft.Container(consult_button, col={"xs": 12, "md": 3})], spacing=14, run_spacing=14),
                    ft.Row([period_enabled, clear_button], wrap=True),
                    period_controls,
                    text(message, color=colors["warning"] if message_error else colors["muted"]),
                ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
                metrics,
                surface(ft.Column([
                    text("Diferenças por almoxarifado" if single_company else "Diferenças por empresa", bold=True, size=18),
                    text(f"{selected[0].company} • Percentual de itens com diferença no inventário."
                         if single_company else "Percentual ponderado no período consultado. Passe o mouse nas barras para ver os valores.",
                         muted=True, size=12),
                    company_chart(selected, colors),
                ], spacing=10, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), height=360),
                surface(ft.Column([
                    ft.Row([ft.Column([text("Inventário mensal", bold=True, size=18), text(period, muted=True)], spacing=3), download_button],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
                    text("Totais somam os almoxarifados. — indica ausência de dados; zero indica uma contagem sem diferença.", muted=True, size=12),
                    results,
                ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
            ], spacing=20, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), padding=24, expand=True),
        ]

    async def consult(_):
        nonlocal rows, snapshot, snapshot_all, busy, message, message_error
        if busy:
            return
        busy, message, message_error = True, "Consultando inventário…", False
        render()
        page.update()
        try:
            start = end = None
            all_months = not period_enabled.value
            if not all_months:
                try:
                    start = datetime.strptime(start_field.value or "", "%m/%Y").date()
                    final_month = datetime.strptime(end_field.value or "", "%m/%Y").date()
                    end = final_month.replace(day=monthrange(final_month.year, final_month.month)[1])
                except ValueError as error:
                    raise ValueError("Informe os meses no formato MM/AAAA.") from error
                months_between(start, end)
            received = await asyncio.to_thread(source.fetch, start, end, "Todos")
            if all_months and received:
                start = min(item.month for item in received)
                last = max(item.month for item in received)
                end = last.replace(day=monthrange(last.year, last.month)[1])
            if start is not None:
                build_matrix(received, months_between(start, end))
            rows, snapshot, snapshot_all = received, (start, end) if start is not None else None, all_months
            companies = ["Todos", *sorted({item.company for item in rows})]
            company_field.options = [ft.dropdown.Option(company) for company in companies]
            if company_field.value not in companies:
                company_field.value = "Todos"
            message = f"{len(rows)} resultados mensais carregados. " + ("Todos os meses disponíveis." if all_months else "Filtro aplicado a meses completos.")
        except Exception as error:
            logging.getLogger(__name__).exception("Falha na consulta de inventário")
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Não foi possível consultar o inventário. Tente novamente."
            message_error = True
        finally:
            busy = False
            render()
            page.update()

    def filter_company(_):
        render()
        page.update()

    async def clear_period(_):
        if not busy:
            period_enabled.value = False
            await consult(None)

    def download(_):
        if busy or not shown() or snapshot is None or download_file is None:
            return
        try:
            content = export_inventory(shown(), *snapshot, company_field.value)
            name = f"inventario-{snapshot[0]:%Y%m%d}-{snapshot[1]:%Y%m%d}.xlsx"
            page.launch_url(download_file(content, name), web_window_name="_self")
        except Exception:
            logging.getLogger(__name__).exception("Falha ao exportar inventário")
            page.open(ft.SnackBar(ft.Text("Não foi possível baixar o Excel. Tente novamente.")))

    def apply_theme(is_dark):
        nonlocal dark
        dark = is_dark
        render()

    consult_button = ft.ElevatedButton("Consultar inventário", icon=ft.Icons.SEARCH, bgcolor=PRIMARY,
                                       color="#FFFFFF", height=52, on_click=consult)
    download_button = ft.OutlinedButton("Baixar Excel", icon=ft.Icons.DOWNLOAD, on_click=download)
    clear_button = ft.TextButton("Limpar período", on_click=clear_period)
    period_enabled.on_change = company_field.on_change = filter_company
    render()
    return InventoryView(layout, apply_theme, resize)
