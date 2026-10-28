"""Monthly financial inventory screen; state and filters are session-local."""

import asyncio
import logging
from decimal import Decimal
from math import ceil
from textwrap import fill

import flet as ft

from automations.inventario.data import month_label
from automations.inventario.database import SqlFinancialInventoryProvider
from automations.inventario.financial import currency, financial_totals, percentage
from automations.inventario.financial_export import export_financial
from automations.inventario.view import InventoryView, TABLE_HEIGHT, inventory_header
from portal.theme import DARK, LIGHT, PRIMARY, metric_card, panel_text, style_input, surface_card


def impact_chart(rows, colors):
    """Compare companies or warehouses; never average percentages."""
    single = len({item.company for item in rows}) == 1
    groups = {}
    for item in rows:
        if not item.counted:
            continue
        name = item.warehouse if single else item.company
        stock, difference = groups.get(name, (Decimal(0), Decimal(0)))
        groups[name] = stock + item.stock, difference + item.difference
    values = [(name, stock, diff, diff / stock * 100)
              for name, (stock, diff) in groups.items() if stock > 0]
    values.sort(key=lambda item: (-item[3], item[0]))
    values = values[:8]
    if not values:
        return ft.Container(ft.Text("Sem contagem com base financeira para comparar.", color=colors["muted"]),
                            height=280, alignment=ft.alignment.center)
    maximum = max(1, ceil(float(max(item[3] for item in values)) * 1.2))
    rods, labels, tops = [], [], []
    for index, (name, stock, difference, percent) in enumerate(values):
        formatted = percentage(percent / 100)
        rods.append(ft.BarChartGroup(x=index, bar_rods=[ft.BarChartRod(
            from_y=0, to_y=float(percent), width=32, color=colors["warning"],
            border_radius=ft.border_radius.only(top_left=6, top_right=6),
            tooltip=f"{name}\n{formatted}\nDiferença: {currency(difference)}\nEstoque: {currency(stock)}",
            tooltip_style=ft.TextStyle(color=colors["text"]),
        )]))
        labels.append(ft.ChartAxisLabel(value=index, label=ft.Container(
            ft.Text(fill(name, width=18), color=colors["text"], size=11,
                    max_lines=5, no_wrap=False, overflow=ft.TextOverflow.ELLIPSIS,
                    text_align=ft.TextAlign.CENTER, tooltip=name),
            width=140, height=82, padding=ft.padding.only(top=6),
            alignment=ft.alignment.top_center, tooltip=name,
        )))
        tops.append(ft.ChartAxisLabel(value=index, label=ft.Text(formatted, color=colors["warning"],
            size=13, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER)))
    chart = ft.BarChart(bar_groups=rods, min_y=0, max_y=maximum, height=330,
        width=max(650, len(values) * 180 + 96), interactive=True,
        bottom_axis=ft.ChartAxis(labels=labels, labels_size=90),
        top_axis=ft.ChartAxis(labels=tops, labels_size=30),
        left_axis=ft.ChartAxis(labels=[ft.ChartAxisLabel(value=maximum * i / 4,
            label=ft.Text(f"{maximum * i / 4:g}%".replace(".", ","), color=colors["muted"], size=11))
            for i in range(5)], labels_size=48, labels_interval=maximum / 4),
        horizontal_grid_lines=ft.ChartGridLines(color=colors["border"], dash_pattern=[4, 4]),
        tooltip_bgcolor=colors["surface"])
    return ft.Row([chart], scroll=ft.ScrollMode.AUTO)


def main(page, download_file=None, *, provider=None, available_width=None):
    if not page.web:
        raise RuntimeError("O impacto financeiro funciona apenas no navegador.")
    source = provider if provider is not None else SqlFinancialInventoryProvider()
    rows, dark, busy = (), True, False
    message, failed = "Consulte o banco para carregar os meses disponíveis.", False
    table_body = None
    company = ft.Dropdown(label="Empresa", value="Todos", options=[ft.dropdown.Option("Todos")], col={"xs": 12, "md": 4})
    month = ft.Dropdown(label="Mês de referência", options=[], col={"xs": 12, "md": 4})
    layout = ft.Column(expand=True, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def colors():
        return DARK if dark else LIGHT

    def text(value, **kwargs):
        return panel_text(value, colors(), **kwargs)

    def surface(content, **kwargs):
        return surface_card(content, colors(), **kwargs)

    def selected():
        return tuple(item for item in rows if item.month.isoformat() == month.value
                     and (company.value == "Todos" or item.company == company.value))

    def width():
        available = available_width() if available_width else page.width
        return max(1550, available if isinstance(available, (int, float)) else 0)

    def resize():
        new_width = width()
        if table_body is None or table_body.width == new_width:
            return False
        table_body.width = table_body.controls[0].width = new_width
        return True

    def table(items):
        nonlocal table_body
        palette = colors()
        labels = ("Empresa", "Almoxarifado", "Estoque financeiro", "Perdas", "Sobras",
                  "Diferença financeira", "% financeiro", "Situação")
        data_rows = []
        for item in items:
            values = (item.company, item.warehouse, currency(item.stock), currency(item.loss),
                      currency(item.surplus), currency(item.difference), percentage(item.percentage), item.status)
            data_rows.append(ft.DataRow(cells=[ft.DataCell(text(value,
                color=palette["warning"] if index in (3, 5, 6) and item.counted and item.difference else None))
                for index, value in enumerate(values)]))
        data_table = ft.DataTable(columns=[ft.DataColumn(text(label, bold=True), numeric=2 <= index <= 6)
            for index, label in enumerate(labels)], rows=data_rows, width=width(),
            heading_row_color=palette["table"], heading_row_height=56,
            data_row_min_height=52, data_row_max_height=52, column_spacing=24)
        table_body = ft.Column([data_table], width=width(), height=TABLE_HEIGHT, scroll=ft.ScrollMode.ALWAYS,
                               horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        return ft.Row([table_body], height=TABLE_HEIGHT, scroll=ft.ScrollMode.ALWAYS,
                      vertical_alignment=ft.CrossAxisAlignment.START)

    def render():
        nonlocal table_body
        table_body = None
        palette = colors()
        items = selected()
        stock, difference, fraction = financial_totals(items)
        for field in (company, month):
            field.disabled = busy or not rows
            style_input(field, palette, weight=ft.FontWeight.W_600)
        consult.disabled = busy
        export.disabled = busy or not items or download_file is None
        export.icon_color = palette["success"]
        col = {"xs": 12, "lg": 4}
        metrics = [
            metric_card("Estoque com contagem", currency(stock), ft.Icons.INVENTORY_2_OUTLINED, "info", palette, col=col),
            metric_card("Diferença financeira", currency(difference), ft.Icons.WARNING_AMBER_ROUNDED, "warning", palette, col=col),
            metric_card("Impacto sobre o estoque contado", percentage(fraction), ft.Icons.PERCENT, "money", palette, col=col),
        ]
        results = table(items) if items else ft.Container(text("Nenhum resultado para a seleção.", muted=True),
            height=TABLE_HEIGHT, alignment=ft.alignment.center)
        layout.controls = [
            inventory_header(
                page,
                palette,
                "Impacto financeiro do inventário",
                "Perdas e sobras por empresa e almoxarifado, com dados do CMFlex.",
                category="INVENTÁRIO • IMPACTO FINANCEIRO",
                financial=True,
            ),
            ft.Container(ft.Column([
                surface(ft.Column([
                    ft.ResponsiveRow([company, month, ft.Container(consult, col={"xs": 12, "md": 4})], spacing=14, run_spacing=14),
                    text(message, color=palette["warning"] if failed else palette["muted"]),
                ], spacing=14)),
                ft.ResponsiveRow(metrics, spacing=14, run_spacing=14),
                surface(ft.Column([
                    text("Impacto financeiro por almoxarifado" if len({item.company for item in items}) == 1
                         else "Impacto financeiro por empresa", bold=True, size=18),
                    text("Até 8 maiores percentuais. Valores acima das colunas; detalhes ao passar o mouse.", muted=True, size=12),
                    impact_chart(items, palette),
                ], spacing=12)),
                surface(ft.Column([
                    ft.Row([text("Resumo financeiro mensal", bold=True, size=18), export],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
                    text("Valores das perdas e sobras identificadas no inventário do mês.", muted=True, size=12),
                    text("Almoxarifados sem contagem ficam fora dos totais e do gráfico.", muted=True, size=12),
                    results,
                ], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
            ], spacing=20, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), padding=24, expand=True),
        ]

    async def load(_):
        nonlocal rows, busy, message, failed
        if busy:
            return
        busy, failed, message = True, False, "Consultando impacto financeiro…"
        render()
        page.update()
        try:
            received = await asyncio.to_thread(source.fetch)
            companies = sorted({item.company for item in received})
            months = sorted({item.month for item in received}, reverse=True)
            preferred = max((item.month for item in received if item.counted), default=months[0] if months else None)
            rows = received
            company.options = [ft.dropdown.Option(value) for value in ("Todos", *companies)]
            month.options = [ft.dropdown.Option(item.isoformat(), month_label(item)) for item in months]
            if company.value not in companies:
                company.value = "Todos"
            if month.value not in {item.isoformat() for item in months}:
                month.value = preferred.isoformat() if preferred else None
            message = f"{len(rows)} registros carregados. Selecione o mês e a empresa para visualizar."
        except Exception as error:
            logging.getLogger(__name__).exception("Falha ao consultar impacto financeiro")
            failed = True
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Não foi possível consultar o impacto financeiro. Tente novamente."
        finally:
            busy = False
            render()
            page.update()

    def filter_changed(_):
        render()
        page.update()

    def download(_):
        if busy or not selected() or download_file is None:
            return
        try:
            payload = export_financial(selected())
            page.launch_url(download_file(payload, f"impacto-financeiro-{month.value}.xlsx"), web_window_name="_self")
        except Exception:
            logging.getLogger(__name__).exception("Falha ao exportar impacto financeiro")
            page.open(ft.SnackBar(ft.Text("Não foi possível baixar o Excel. Tente novamente.")))

    def apply_theme(is_dark):
        nonlocal dark
        dark = is_dark
        render()

    consult = ft.ElevatedButton("Consultar impacto financeiro", icon=ft.Icons.SEARCH, bgcolor=PRIMARY,
                                color="#FFFFFF", height=52, on_click=load)
    export = ft.OutlinedButton("Baixar Excel", icon=ft.Icons.DOWNLOAD, on_click=download)
    company.on_change = month.on_change = filter_changed
    render()
    return InventoryView(layout, apply_theme, resize)
