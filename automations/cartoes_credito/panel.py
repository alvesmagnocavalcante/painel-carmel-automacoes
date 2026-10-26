"""Conferência da fatura com busca auxiliar, sem uma segunda lista de revisão."""

import asyncio
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import flet as ft

from automations.cartoes_credito.data import CardPayment, validate_period
from automations.cartoes_credito.database import SqlCardPaymentProvider
from automations.cartoes_credito.bank_panel import main as build_bank_panel
from automations.cartoes_credito.statement import BankStatement
from portal.theme import get_palette, panel_text, style_input


@dataclass(frozen=True)
class CardPanelView:
    control: ft.Column
    apply_theme: Callable[[bool], None]


def _date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _normalize(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(char))


def main(page: ft.Page, download_file=None, *, provider=None, upload_dir: str | None = None, store=None) -> CardPanelView:
    if not page.web:
        raise RuntimeError("A conferência de cartões funciona apenas no navegador.")
    source = provider if provider is not None else SqlCardPaymentProvider()
    dark = True
    rows: tuple[CardPayment, ...] = ()
    busy = False
    today = date.today()
    selected_start = today.replace(day=1)
    selected_end = today
    layout = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=0,
                       horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def colors():
        return get_palette(dark)

    def label(value: str, *, muted=False, bold=False, size=14):
        return panel_text(value, colors(), muted=muted, bold=bold, size=size, selectable=True)

    start_field = ft.TextField(label="Lançamentos de", value=_date(selected_start), read_only=True,
                               prefix=ft.Icon(ft.Icons.CALENDAR_MONTH), expand=True)
    end_field = ft.TextField(label="Até", value=_date(selected_end), read_only=True,
                             prefix=ft.Icon(ft.Icons.EVENT_AVAILABLE), expand=True)
    company_field = ft.Dropdown(label="Empresa no CMFlex", value="Todos",
                                options=[ft.dropdown.Option("Todos")], expand=True)
    message = ft.Text("")

    def change_start(event):
        nonlocal selected_start
        selected_start = event.control.value.date() if hasattr(event.control.value, "date") else event.control.value
        start_field.value = _date(selected_start)
        start_field.update()

    def change_end(event):
        nonlocal selected_end
        selected_end = event.control.value.date() if hasattr(event.control.value, "date") else event.control.value
        end_field.value = _date(selected_end)
        end_field.update()

    start_picker = ft.DatePicker(value=selected_start, first_date=date(2020, 1, 1),
                                 last_date=date(today.year + 1, 12, 31), on_change=change_start)
    end_picker = ft.DatePicker(value=selected_end, first_date=date(2020, 1, 1),
                               last_date=date(today.year + 1, 12, 31), on_change=change_end)
    start_field.on_click = lambda _: page.open(start_picker)
    end_field.on_click = lambda _: page.open(end_picker)

    def statement_loaded(statement: BankStatement):
        nonlocal selected_start, selected_end, rows
        selected_start = min(item.purchase_date for item in statement.transactions) - timedelta(days=60)
        selected_end = max(statement.due_date, max(item.purchase_date for item in statement.transactions)) + timedelta(days=60)
        truncated = (selected_end - selected_start).days > 366
        if truncated:
            selected_end = selected_start + timedelta(days=366)
        start_field.value, end_field.value = _date(selected_start), _date(selected_end)
        start_picker.value, end_picker.value = selected_start, selected_end
        company_field.value = "Todos"
        rows = ()
        message.value = ("Ajuste o período em 'Busca no CMFlex' para localizar os lançamentos."
                         if truncated else "Buscando lançamentos no CMFlex...")
        if truncated:
            return
        page.run_task(consult, None)

    bank = build_bank_panel(page, colors=colors, payments=lambda: rows,
                            company=lambda: company_field.value or "Todos",
                            lookup_state=lambda: message.value,
                            on_loaded=statement_loaded, download_file=download_file,
                            upload_dir=upload_dir, store=store)

    def render():
        palette = colors()
        for field in (start_field, end_field, company_field):
            style_input(field, palette)
            field.disabled = busy
        consult_button.disabled = busy
        search_options.visible = bank.statement() is not None
        search_options.bgcolor = search_options.collapsed_bgcolor = palette["surface"]
        search_options.text_color = search_options.collapsed_text_color = palette["text"]
        search_options.icon_color = search_options.collapsed_icon_color = palette["muted"]
        layout.controls = [
            ft.Container(label("Conferência de cartões de crédito", bold=True, size=24),
                         padding=ft.padding.symmetric(horizontal=32, vertical=20), bgcolor=palette["surface"]),
            ft.Container(ft.Column([search_options, bank.control], spacing=14,
                                   horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                         padding=24, expand=True),
        ]
        bank.render()
        page.update()

    async def consult(_):
        nonlocal rows, busy
        try:
            validate_period(selected_start, selected_end)
        except ValueError as error:
            message.value = str(error)
            render()
            return
        busy = True
        message.value = "Buscando lançamentos no CMFlex..."
        render()
        try:
            fetched = await asyncio.to_thread(source.fetch, selected_start, selected_end)
        except Exception:
            logging.getLogger(__name__).exception("Falha na consulta de cartões")
            message.value = "Não foi possível consultar o CMFlex. Tente novamente em 'Busca no CMFlex'."
        else:
            rows = fetched
            companies = sorted({row.company for row in rows})
            current = company_field.value
            company_field.options = [ft.dropdown.Option("Todos"), *(ft.dropdown.Option(name) for name in companies)]
            if current not in companies:
                company_field.value = "Todos"
            statement = bank.statement()
            if statement is not None and company_field.value == "Todos":
                matches = {name for name in companies if _normalize(name) in _normalize(statement.company)}
                if len(matches) == 1:
                    company_field.value = matches.pop()
            if not rows:
                message.value = "Nenhum lançamento encontrado. Ajuste o período em 'Busca no CMFlex'."
            elif company_field.value == "Todos":
                message.value = "Selecione a empresa em 'Busca no CMFlex' para conferir a fatura."
            else:
                message.value = ""
        finally:
            busy = False
            render()

    consult_button = ft.ElevatedButton("Buscar novamente", icon=ft.Icons.SEARCH, on_click=consult)

    def change_company(_):
        message.value = ("" if company_field.value != "Todos" else
                         "Selecione a empresa em 'Busca no CMFlex' para conferir a fatura.")
        render()

    company_field.on_change = change_company
    search_options = ft.ExpansionTile(
        title=label("Busca no CMFlex", bold=True), initially_expanded=False,
        controls=[ft.Container(content=ft.ResponsiveRow([
            ft.Container(start_field, col={"xs": 12, "md": 3}),
            ft.Container(end_field, col={"xs": 12, "md": 3}),
            ft.Container(company_field, col={"xs": 12, "md": 3}),
            ft.Container(consult_button, col={"xs": 12, "md": 3}),
        ], spacing=12, run_spacing=12), padding=ft.padding.only(left=16, right=16, bottom=16))],
    )

    def apply_theme(is_dark: bool):
        nonlocal dark
        dark = is_dark
        render()

    render()
    return CardPanelView(control=layout, apply_theme=apply_theme)
