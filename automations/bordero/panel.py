"""Flet panel for open-payment conferences."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

import flet as ft

from automations.bordero.attachment_view import attachment_view
from automations.bordero.database import SqlConferenceProvider
from automations.bordero.store import BorderoStore
from automations.bordero.panel_data import (
    ConferenceRow,
    classify_conference,
    filter_conferences,
    validate_filters,
)
from portal.theme import DARK, FONTS, LIGHT, PRIMARY, build_theme, style_input, surface_card

TABLE_COLUMNS = (
    ("Favorecido", False),
    ("CPF/CNPJ", False),
    ("Lançamento", False),
    ("Empresa", False),
    ("Saldo", True),
    ("Data programada", False),
    ("Vencimento", False),
    ("Forma de pagamento", False),
    ("Conferência", False),
    ("Responsável pelo lançamento", False),
    ("Anexos", False),
    ("Aprovação no CMFlex", False),
    ("Pendência", False),
    ("Conferir", False),
    ("Histórico", False),
)


@dataclass(frozen=True)
class PanelView:
    control: ft.Column
    toggle_theme: Callable


def _currency(value: Decimal) -> str:
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _date_text(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "Não informado"


def _event_date(value: object) -> date:
    if hasattr(value, "date"):
        return value.date()  # type: ignore[no-any-return, union-attr]
    if isinstance(value, date):
        return value
    raise ValueError("Data inválida.")


def main(
    page: ft.Page,
    web_download: Callable[..., str],
    attachment_download: Callable[..., str] | None = None,
    *,
    embedded: bool = False,
    on_theme_change: Callable[[bool], None] | None = None,
    store: BorderoStore | None = None,
) -> PanelView:
    if not page.web:
        raise RuntimeError(
            "O borderô funciona apenas no navegador. Inicie automations.bordero.web."
        )
    dark_mode = True

    def palette() -> dict[str, str]:
        return DARK if dark_mode else LIGHT

    page.title = "Conferência de pagamentos"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = DARK["background"]
    page.padding = 0
    page.fonts = {**(page.fonts if isinstance(page.fonts, dict) else {}), **FONTS}
    page.theme = build_theme(PRIMARY, LIGHT)
    page.dark_theme = build_theme("#9F9385", DARK)

    provider = SqlConferenceProvider()
    review_store = store if store is not None else BorderoStore()
    current_rows: tuple[ConferenceRow, ...] = ()
    loaded_filters: tuple[date, date, str] | None = None
    today = date.today()
    selected_start = today - timedelta(days=30)
    selected_end = today

    calendar_icons = [
        ft.Icon(ft.Icons.CALENDAR_MONTH, color=palette()["info"]),
        ft.Icon(ft.Icons.EVENT_AVAILABLE, color=palette()["info"]),
    ]
    start_field = ft.TextField(label="Data inicial", value=_date_text(selected_start), read_only=True, prefix=calendar_icons[0], expand=True)
    end_field = ft.TextField(label="Data final", value=_date_text(selected_end), read_only=True, prefix=calendar_icons[1], expand=True)
    hotel_field = ft.Dropdown(label="Hotel", hint_text="Selecione o hotel", options=[ft.dropdown.Option("Todos")], value="Todos", expand=True)
    style_input(hotel_field, palette())

    status_text = ft.Text("Selecione os filtros para iniciar.", color=palette()["muted"])
    result_title = ft.Text("Conferências", size=20, weight=ft.FontWeight.W_600, color=palette()["text"])
    result_subtitle = ft.Text("Nenhuma consulta realizada", color=palette()["muted"])
    empty_icon = ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=54, color=palette()["info"])
    empty_title = ft.Text("As conferências aparecerão aqui", size=17, color=palette()["text"])
    empty_subtitle = ft.Text("Informe o período e o hotel para consultar.", color=palette()["muted"])
    empty_state = ft.Container(
        content=ft.Column([empty_icon, empty_title, empty_subtitle], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        alignment=ft.alignment.center, height=280,
    )
    table_container = ft.Container(content=empty_state)

    total_value = ft.Text("0", size=25, weight=ft.FontWeight.BOLD, color=palette()["text"])
    checked_value = ft.Text("0", size=25, weight=ft.FontWeight.BOLD, color=palette()["success"])
    pending_value = ft.Text("0", size=25, weight=ft.FontWeight.BOLD, color=palette()["warning"])
    balance_value = ft.Text("R$ 0,00", size=25, weight=ft.FontWeight.BOLD, color=palette()["text"])
    download_button = ft.OutlinedButton("Baixar Excel", icon=ft.Icons.DOWNLOAD_OUTLINED, icon_color=palette()["success"], disabled=True)

    def show_message(message: str, error: bool = False) -> None:
        page.open(ft.SnackBar(ft.Text(message, color="#FFFFFF"), bgcolor="#B83A3A" if error else PRIMARY))

    def set_start(event: ft.ControlEvent) -> None:
        nonlocal selected_start
        selected_start = _event_date(event.control.value)
        start_field.value = _date_text(selected_start)
        start_field.update()

    def set_end(event: ft.ControlEvent) -> None:
        nonlocal selected_end
        selected_end = _event_date(event.control.value)
        end_field.value = _date_text(selected_end)
        end_field.update()

    start_picker = ft.DatePicker(value=selected_start, first_date=date(2020, 1, 1), last_date=date(today.year + 1, 12, 31), on_change=set_start)
    end_picker = ft.DatePicker(value=selected_end, first_date=date(2020, 1, 1), last_date=date(today.year + 1, 12, 31), on_change=set_end)
    start_field.on_click = lambda _: page.open(start_picker)
    end_field.on_click = lambda _: page.open(end_picker)

    def visible_rows() -> tuple[ConferenceRow, ...]:
        method = payment_filter.value or "all"
        return filter_conferences(
            current_rows,
            classification.value or "Todos",
            None if method == "all" else method.removeprefix("method:"),
            search_field.value or "",
        )

    def refresh_results() -> None:
        shown = visible_rows()
        total_value.value = str(len(shown))
        checked_value.value = str(sum(row.situation == "Conferido" for row in shown))
        pending_value.value = str(sum(row.situation == "Pendente" for row in shown))
        balance_value.value = _currency(sum((row.balance for row in shown), Decimal("0")))
        unreviewed = sum(row.situation == "A conferir" for row in shown)
        status_text.value = f"{len(shown)} de {len(current_rows)} pagamentos • {unreviewed} a conferir."
        download_button.disabled = not shown
        table_container.content = build_table(shown) if current_rows else empty_state
        page.update()

    classification = ft.Dropdown(
        label="Exibir", value="Todos", width=210,
        options=[ft.dropdown.Option(value) for value in ("Todos", "A conferir", "Conferido", "Pendente")],
        on_change=lambda _: refresh_results(),
    )
    payment_filter = ft.Dropdown(
        label="Forma de pagamento", value="all", width=290,
        options=[ft.dropdown.Option(key="all", text="Todas")],
        on_change=lambda _: refresh_results(),
    )
    style_input(classification, palette())
    style_input(payment_filter, palette())

    def clear_search(_: object) -> None:
        search_field.value = ""
        refresh_results()

    search_icon = ft.Icon(ft.Icons.SEARCH, color=palette()["info"])
    search_clear = ft.IconButton(ft.Icons.CLOSE, tooltip="Limpar pesquisa", on_click=clear_search, icon_color=palette()["muted"])
    search_field = ft.TextField(
        label="Pesquisar favorecido, CPF/CNPJ ou lançamento",
        hint_text="Digite parte do nome, documento ou lançamento",
        prefix=search_icon, suffix=search_clear, on_change=lambda _: refresh_results(),
    )
    style_input(search_field, palette())

    def review(item: ConferenceRow) -> None:
        colors = palette()
        preview, load_preview, clear_preview = attachment_view(page, item, attachment_download, colors=colors)

        def close(_: object = None) -> None:
            clear_preview()
            page.close(dialog)

        decision = ft.Dropdown(
            label="Classificação", value=item.situation,
            options=[ft.dropdown.Option(value) for value in ("A conferir", "Conferido", "Pendente")],
        )
        style_input(decision, colors)
        reason = ft.TextField(
            label="O que precisa ser corrigido?", value=item.pending_reason,
            hint_text="Ex.: falta comprovante ou valor diferente do documento.",
            multiline=True, min_lines=2, max_lines=4,
        )
        error_text = ft.Text(color=colors["warning"])

        def save(_: ft.ControlEvent) -> None:
            nonlocal current_rows
            try:
                updated = classify_conference(item, decision.value or "A conferir", reason.value or "")
            except ValueError as error:
                error_text.value = str(error)
                page.update()
                return
            review_store.save_review(updated)
            current_rows = tuple(updated if row.review_key == item.review_key else row for row in current_rows)
            close()
            refresh_results()

        dialog = ft.AlertDialog(
            bgcolor=colors["surface"], modal=True, title=ft.Text("Conferir pagamento"),
            on_dismiss=lambda _: clear_preview(),
            content=ft.Container(
                width=1500, height=700,
                content=ft.Row([
                    ft.Container(content=preview, expand=7, padding=12),
                    ft.VerticalDivider(width=1),
                    ft.Container(
                        expand=4, padding=12,
                        content=ft.Column([
                            ft.Text(item.supplier, size=18, weight=ft.FontWeight.W_600, selectable=True),
                            ft.Text(f"CPF/CNPJ: {item.tax_id}", selectable=True),
                            ft.Text(f"Lançamento {item.launch_number} • {item.company}", color=colors["muted"]),
                            ft.Row([
                                ft.Column([ft.Text("Valor a pagar", color=colors["muted"]), ft.Text(_currency(item.balance), size=22, weight=ft.FontWeight.BOLD)], spacing=4),
                                ft.Column([ft.Text("Forma de pagamento", color=colors["muted"]), ft.Text(item.payment_method or "Não informada")], spacing=4),
                            ], spacing=32, wrap=True),
                            ft.Text(f"Responsável pelo lançamento: {item.responsible or 'Não informado'}"),
                            ft.Text(f"Aprovação no CMFlex: {item.source_situation or 'Não informada'}"),
                            ft.Text(f"Anexos: {item.attachment_summary}", color=colors["warning"] if item.attachment_count == 0 else colors["text"]),
                            ft.Text(item.attachment_names or "Nenhum nome de arquivo informado.", selectable=True, color=colors["muted"]),
                            ft.Divider(),
                            ft.Text("Resultado da sua conferência", weight=ft.FontWeight.W_600),
                            decision, reason, error_text,
                            ft.Text("A classificação vale nesta tela e será incluída no Excel. Ela não aprova o pagamento no CMFlex.", size=12, color=colors["muted"]),
                            ft.ExpansionTile(
                                title=ft.Text("Mais informações do pagamento"),
                                controls=[ft.Container(padding=12, content=ft.Column([
                                    ft.Text(f"Data programada: {_date_text(item.scheduled_date)}"),
                                    ft.Text(f"Vencimento: {_date_text(item.due_date)}"),
                                    ft.Text(item.details or "Nenhuma informação adicional.", selectable=True),
                                    ft.Text("Dados bancários e outras parcelas não foram fornecidos. Confira no CMFlex se precisar.", size=12, color=colors["muted"]),
                                    ft.Text("Histórico", weight=ft.FontWeight.W_600),
                                    ft.Text(item.history or "Não informado", selectable=True),
                                ], spacing=10))],
                            ),
                        ], scroll=ft.ScrollMode.AUTO),
                    ),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ),
            actions=[ft.TextButton("Cancelar", on_click=close), ft.ElevatedButton("Salvar conferência", on_click=save)],
        )
        page.open(dialog)
        page.run_task(load_preview)

    def table_cell(text: str, *, color: str | None = None, bold: bool = False) -> ft.DataCell:
        return ft.DataCell(ft.Text(text, color=color or palette()["text"], weight=ft.FontWeight.W_600 if bold else ft.FontWeight.W_500, no_wrap=True))

    def build_table(rows: tuple[ConferenceRow, ...]) -> ft.Control:
        colors = palette()
        data_rows = [
            ft.DataRow(cells=[
                table_cell(item.supplier),
                table_cell(item.tax_id),
                table_cell(item.launch_number, bold=True),
                table_cell(item.company),
                table_cell(_currency(item.balance)),
                table_cell(_date_text(item.scheduled_date)),
                table_cell(_date_text(item.due_date)),
                table_cell(item.payment_method or "Não informado"),
                table_cell(item.situation, color=colors["success"] if item.situation == "Conferido" else colors["warning"], bold=True),
                table_cell(item.responsible or "Não informado"),
                table_cell(item.attachment_summary, color=colors["warning"] if item.attachment_count == 0 else colors["text"]),
                table_cell(item.source_situation or "Não informada"),
                table_cell(item.pending_reason),
                ft.DataCell(ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_color=colors["info"], tooltip="Conferir lançamento", on_click=lambda _, row=item: review(row))),
                table_cell(item.history),
            ])
            for item in rows
        ]
        viewport_height = min(420, 56 + len(data_rows) * 60 + 20)
        table = ft.DataTable(
            heading_text_style=ft.TextStyle(color=colors["text"], weight=ft.FontWeight.W_600),
            columns=[ft.DataColumn(ft.Text(label), numeric=numeric) for label, numeric in TABLE_COLUMNS],
            rows=data_rows, heading_row_color=colors["table"], column_spacing=28,
            data_row_min_height=52, data_row_max_height=60,
        )
        return ft.Row(
            [ft.Column([table], height=viewport_height, scroll=ft.ScrollMode.ALWAYS)],
            height=viewport_height, vertical_alignment=ft.CrossAxisAlignment.START, scroll=ft.ScrollMode.ALWAYS,
        )

    async def consult(_: ft.ControlEvent) -> None:
        nonlocal current_rows, loaded_filters
        consult_button.disabled = True
        status_text.value = "Consultando pagamentos em aberto..."
        page.update()
        try:
            hotel = hotel_field.value or ""
            snapshot = (selected_start, selected_end, hotel)
            validate_filters(*snapshot)
            rows = await asyncio.to_thread(provider.fetch, *snapshot)
            current_rows = review_store.apply_reviews(rows)
            loaded_filters = snapshot
        except Exception as error:
            logging.getLogger(__name__).exception("Falha na consulta do borderô")
            status_text.value = "A consulta falhou. Os resultados anteriores foram mantidos."
            show_message(str(error) if isinstance(error, (ValueError, RuntimeError)) else "Não foi possível carregar os pagamentos.", error=True)
            return
        finally:
            consult_button.disabled = False
            page.update()

        result_subtitle.value = f"{hotel}  •  vencimento de {_date_text(snapshot[0])} a {_date_text(snapshot[1])}"
        if hotel == "Todos":
            hotel_field.options = [ft.dropdown.Option(value) for value in ["Todos", *sorted({row.company for row in rows if row.company})]]
        payment_filter.options = [ft.dropdown.Option(key="all", text="Todas")] + [
            ft.dropdown.Option(key=f"method:{method}", text=method or "Não informado")
            for method in sorted({row.payment_method for row in rows})
        ]
        if payment_filter.value not in {option.key for option in payment_filter.options}:
            payment_filter.value = "all"
        refresh_results()

    def download(_: ft.ControlEvent) -> None:
        shown = visible_rows()
        if not shown or not loaded_filters:
            return
        try:
            page.launch_url(web_download(shown, *loaded_filters), web_window_name="_self")
        except Exception:
            logging.getLogger(__name__).exception("Falha ao entregar Excel no navegador")
            show_message("Não foi possível baixar o Excel. Tente novamente.", error=True)

    download_button.on_click = download
    consult_button = ft.ElevatedButton("Consultar conferências", icon=ft.Icons.SEARCH, bgcolor=PRIMARY, color="#FFFFFF", height=52, on_click=consult)

    metric_cards: list[ft.Container] = []
    metric_labels: list[ft.Text] = []
    metric_icons: list[tuple[ft.Icon, str]] = []
    metric_icon_backgrounds: list[tuple[ft.Container, str]] = []

    def metric(label: str, value: ft.Text, icon: str, *, semantic: str) -> ft.Container:
        colors = palette()
        label_control = ft.Text(label, color=colors["muted"], size=13)
        icon_control = ft.Icon(icon, color=colors[semantic], size=20)
        icon_bg = ft.Container(icon_control, bgcolor=colors[f"{semantic}_soft"], border_radius=12, padding=10)
        card = surface_card(
            ft.Row([icon_bg, ft.Column([label_control, value], spacing=2, tight=True)], spacing=12),
            colors, radius=14, padding=14, height=84, col={"xs": 12, "sm": 6, "lg": 3},
        )
        metric_cards.append(card)
        metric_labels.append(label_control)
        metric_icons.append((icon_control, semantic))
        metric_icon_backgrounds.append((icon_bg, semantic))
        return card

    metrics = ft.ResponsiveRow([
        metric("Pagamentos", total_value, ft.Icons.RECEIPT_OUTLINED, semantic="info"),
        metric("Conferidos", checked_value, ft.Icons.CHECK_CIRCLE_OUTLINE, semantic="success"),
        metric("Pendências", pending_value, ft.Icons.WARNING_AMBER_ROUNDED, semantic="warning"),
        metric("Saldo total", balance_value, ft.Icons.PAYMENTS_OUTLINED, semantic="money"),
    ], spacing=14, run_spacing=14)

    header_category = ft.Text("BORDERÔ • CONFERÊNCIA DE PAGAMENTOS", size=11, weight=ft.FontWeight.W_600, color=palette()["accent"])
    header_title = ft.Text("Conferência de pagamentos em aberto", size=24, weight=ft.FontWeight.W_600, color=palette()["text"])
    header_subtitle = ft.Text("Consulte o período, confira os anexos e classifique os pagamentos do CMFlex.", size=13, color=palette()["muted"])
    theme_button = ft.IconButton(icon=ft.Icons.LIGHT_MODE_OUTLINED, icon_color=palette()["warning"], tooltip="Usar modo claro")
    header = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Container(
                    ft.Image(src="/carmel-logo.png", width=164, height=70, fit=ft.ImageFit.CONTAIN, semantics_label="Carmel Hotéis"),
                    bgcolor="#FFFFFF", border_radius=10, padding=8, visible=not embedded,
                ),
                ft.Column([header_category, header_title, header_subtitle], spacing=4, expand=True),
            ], spacing=24, expand=True),
            theme_button,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        bgcolor=palette()["surface"], padding=ft.padding.symmetric(horizontal=32, vertical=20),
        border=ft.border.only(bottom=ft.BorderSide(1, palette()["border"])),
    )

    filters_title = ft.Text("Filtros da consulta", size=18, weight=ft.FontWeight.W_600, color=palette()["text"])
    filters = surface_card(
        ft.Column([
            filters_title,
            ft.ResponsiveRow([
                ft.Container(start_field, col={"sm": 12, "md": 3}),
                ft.Container(end_field, col={"sm": 12, "md": 3}),
                ft.Container(hotel_field, col={"sm": 12, "md": 3}),
                ft.Container(consult_button, col={"sm": 12, "md": 3}),
            ], spacing=14, run_spacing=14),
            status_text,
        ], spacing=16),
        palette(), padding=22,
    )

    results_divider = ft.Divider(height=1, color=palette()["border"])
    results = surface_card(
        ft.Column([
            ft.Row([ft.Column([result_title, result_subtitle], spacing=2), download_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            results_divider,
            ft.Row([classification, payment_filter], wrap=True),
            search_field,
            table_container,
        ], spacing=18),
        palette(), padding=22,
    )

    primary_texts = (result_title, empty_title, total_value, balance_value, header_title, filters_title)
    muted_texts = (status_text, result_subtitle, empty_subtitle, header_subtitle, *metric_labels)
    surfaces = (filters, results, *metric_cards)

    def toggle_theme(_: ft.ControlEvent) -> None:
        nonlocal dark_mode
        dark_mode = not dark_mode
        colors = palette()
        page.theme_mode = ft.ThemeMode.DARK if dark_mode else ft.ThemeMode.LIGHT
        page.bgcolor, header.bgcolor = colors["background"], colors["surface"]
        header.border = ft.border.only(bottom=ft.BorderSide(1, colors["border"]))
        header_category.color = colors["accent"]
        for surface in surfaces:
            surface.bgcolor, surface.border = colors["surface"], ft.border.all(1, colors["border"])
        for control in primary_texts:
            control.color = colors["text"]
        for control in muted_texts:
            control.color = colors["muted"]
        for bg, semantic in metric_icon_backgrounds:
            bg.bgcolor = colors[f"{semantic}_soft"]
        for icon_ctrl, semantic in metric_icons:
            icon_ctrl.color = colors[semantic]
        for icon_ctrl in calendar_icons:
            icon_ctrl.color = colors["info"]
        for control in (hotel_field, classification, payment_filter, search_field):
            style_input(control, colors)
        search_icon.color, search_clear.icon_color = colors["info"], colors["muted"]
        download_button.icon_color = checked_value.color = colors["success"]
        pending_value.color, empty_icon.color, results_divider.color = colors["warning"], colors["info"], colors["border"]
        theme_button.icon = ft.Icons.LIGHT_MODE_OUTLINED if dark_mode else ft.Icons.DARK_MODE_OUTLINED
        theme_button.icon_color = colors["warning"] if dark_mode else colors["info"]
        theme_button.tooltip = "Usar modo claro" if dark_mode else "Usar modo escuro"
        table_container.content = build_table(visible_rows()) if current_rows else empty_state
        if on_theme_change:
            on_theme_change(dark_mode)
        page.update()

    theme_button.on_click = toggle_theme
    layout = ft.Column([
        header,
        ft.Container(content=ft.Column([filters, metrics, results], spacing=20, scroll=ft.ScrollMode.AUTO), padding=24, expand=True),
    ], expand=True, spacing=0)
    if not embedded:
        page.add(*layout.controls)
    return PanelView(layout, toggle_theme)


if __name__ == "__main__":
    from portal.web import serve

    serve()
