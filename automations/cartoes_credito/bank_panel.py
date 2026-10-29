"""Importação temporária da fatura e revisão humana de cada transação."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from secrets import token_urlsafe
from typing import Callable

import flet as ft

from automations.bordero.attachment_view import attachment_view
from automations.cartoes_credito.data import CardPayment, STATUSES
from automations.cartoes_credito.export import export_statement
from automations.cartoes_credito.reconciliation import (
    CARD_CHARGE_STATUS, TRANSACTION_FILTERS, BankReview, classify_transaction,
    filter_transactions, is_card_charge, suggest_matches,
)
from automations.cartoes_credito.statement import BankStatement, MAX_STATEMENT_BYTES, parse_statement
from automations.cartoes_credito.store import CardStore


@dataclass(frozen=True)
class BankPanelView:
    control: ft.Container
    render: Callable[[], None]
    statement: Callable[[], BankStatement | None]


def _money(value) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def main(page: ft.Page, *, colors: Callable[[], dict], payments: Callable[[], tuple[CardPayment, ...]],
         company: Callable[[], str], lookup_state: Callable[[], str], on_loaded: Callable[[BankStatement], None],
         download_file=None, upload_dir: str | None = None, store: CardStore | None = None) -> BankPanelView:
    card_store = store if store is not None else CardStore()
    statement: BankStatement | None = None
    reviews: dict[int, BankReview] = {}
    upload_token: str | None = None
    notice = ft.Text("Carregue o XLSX da fatura exportada do Itaú.")
    container = ft.Container()
    transaction_filter = ft.Dropdown(
        label="Filtrar itens", value="Todos", width=260,
        options=[ft.dropdown.Option(value) for value in TRANSACTION_FILTERS],
    )

    def text(value: str, *, muted=False, bold=False, size=14, color=None,
             max_lines=None, tooltip=None):
        palette = colors()
        return ft.Text(value, color=color or palette["muted" if muted else "text"], size=size,
                       weight=ft.FontWeight.W_600 if bold else ft.FontWeight.W_500,
                       max_lines=max_lines,
                       overflow=ft.TextOverflow.ELLIPSIS if max_lines else None,
                       tooltip=tooltip, selectable=True)

    def style_field(field):
        field.bgcolor = colors()["surface"]
        field.color = colors()["text"]
        field.text_style = ft.TextStyle(color=colors()["text"], weight=ft.FontWeight.W_500)
        field.label_style = ft.TextStyle(color=colors()["muted"])

    def pick(_):
        if picker is not None:
            picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM,
                              allowed_extensions=["xlsx"], allow_multiple=False)

    def picked(event):
        nonlocal upload_token
        files = event.files or ()
        if not files:
            return
        selected = files[0]
        if not selected.name.lower().endswith(".xlsx") or (selected.size and selected.size > MAX_STATEMENT_BYTES):
            notice.value = "Selecione uma planilha XLSX de até 5 MB."
            page.update()
            return
        upload_token = token_urlsafe(24) + ".xlsx"
        try:
            url = page.get_upload_url(upload_token, 600)
            picker.upload([ft.FilePickerUploadFile(selected.name, upload_url=url)])
            notice.value = "Enviando a planilha para leitura temporária..."
        except Exception:
            upload_token = None
            notice.value = "Não foi possível iniciar o envio da planilha."
        page.update()

    def uploaded(event):
        nonlocal upload_token, statement, reviews
        if event.error:
            if upload_token is not None and upload_dir is not None:
                (Path(upload_dir) / upload_token).unlink(missing_ok=True)
            upload_token = None
            notice.value = "Falha no envio da planilha. Tente novamente."
            page.update()
            return
        if event.progress < 1 or upload_token is None or upload_dir is None:
            return
        token, upload_token = upload_token, None
        path = Path(upload_dir) / token
        try:
            imported = parse_statement(path.read_bytes())
        except (OSError, ValueError) as error:
            notice.value = str(error) if isinstance(error, ValueError) else "Não foi possível ler a planilha enviada."
        else:
            statement = imported
            reviews = card_store.load_reviews(imported)
            transaction_filter.value = "Todos"
            notice.value = ""
            on_loaded(imported)
        finally:
            path.unlink(missing_ok=True)
            render()
            page.update()

    picker = ft.FilePicker(on_result=picked, on_upload=uploaded) if upload_dir else None
    if picker is not None:
        page.overlay.append(picker)
    upload_button = ft.ElevatedButton("Carregar fatura XLSX", icon=ft.Icons.UPLOAD_FILE,
                                      on_click=pick, disabled=picker is None)

    def review_transaction(transaction):
        if statement is None:
            return

        def modal_width(preferred: int) -> int:
            viewport = page.width
            if isinstance(viewport, (int, float)) and viewport > 48:
                return min(preferred, viewport - 48)
            return preferred

        selected_company = company()
        source_rows = tuple(row for row in payments() if row.company == selected_company)
        matches = suggest_matches(transaction, source_rows, selected_company)
        card_charge = is_card_charge(transaction)
        compact_height = min(580, 370 + 50 * len(matches) + (60 if card_charge else 0))
        previous = reviews.get(transaction.row_number, BankReview())
        selected_value = (f"{previous.payment_key[0]}:{previous.payment_key[1]}"
                          if any(row.key == previous.payment_key for row in matches) else None)
        choices = (ft.RadioGroup(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Radio(value=f"{row.company_id}:{row.document_id}",
                                 active_color=colors()["info"], toggleable=True,
                                 tooltip=f"Selecionar lançamento {row.launch_number}"),
                        ft.Container(
                            content=ft.Column([
                                text(row.beneficiary, bold=True, max_lines=2, tooltip=row.beneficiary),
                                text(f"Lançamento {row.launch_number} • {_date(row.launch_date)}",
                                     muted=True, size=12),
                            ], spacing=4),
                            expand=True,
                        ),
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor=colors()["table"], border=ft.border.all(1, colors()["border"]),
                    border_radius=10, padding=ft.padding.symmetric(horizontal=12, vertical=8),
                )
                for row in matches
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            value=selected_value,
        ) if matches else None)
        available_statuses = STATUSES if matches else ("A conferir", "Pendente")
        if card_charge:
            available_statuses = (*available_statuses[:-1], CARD_CHARGE_STATUS, "Pendente")
        decision = ft.Dropdown(label="Resultado",
                               value=previous.status if previous.status in available_statuses else "A conferir",
                               options=[ft.dropdown.Option(status) for status in available_statuses])
        reason = ft.TextField(label="Pendência", value=previous.reason, multiline=True,
                              min_lines=2, max_lines=4, visible=previous.status == "Pendente",
                              hint_text="Descreva o que precisa ser verificado.")
        for field in (decision, reason):
            style_field(field)
        error_label = text("", color=colors()["danger"])
        clear_preview = None
        preview_box = ft.Container(
            content=text("Selecione um lançamento para visualizar o documento.", muted=True),
            expand=6, padding=12, visible=False,
        )
        divider = ft.VerticalDivider(width=1, color=colors()["border"], visible=False)

        def chosen_payment():
            return next((row for row in matches
                         if f"{row.company_id}:{row.document_id}" == choices.value), None) if choices else None

        def select(_=None):
            nonlocal clear_preview
            if clear_preview is not None:
                clear_preview()
                clear_preview = None
            payment = chosen_payment()
            if payment is None:
                preview_box.content = text("Selecione um lançamento para visualizar o documento.", muted=True)
                preview_box.visible = divider.visible = False
                dialog.content.width, dialog.content.height = modal_width(900), compact_height
            else:
                preview, load, clear_preview = attachment_view(page, payment, download_file, colors=colors())
                preview_box.content = preview
                preview_box.visible = divider.visible = True
                dialog.content.width, dialog.content.height = modal_width(1450), 700
                page.update()
                page.run_task(load)
            page.update()

        def close(_=None):
            if clear_preview is not None:
                clear_preview()
            page.close(dialog)

        def save(_):
            payment = chosen_payment()
            try:
                updated = classify_transaction(
                    transaction, decision.value or "A conferir", reason.value or "",
                    payment.key if payment else None, source_rows, selected_company, reviews,
                )
            except ValueError as error:
                error_label.value = str(error)
                page.update()
                return
            reviews[transaction.row_number] = updated
            if statement is not None:
                card_store.save_review(statement, transaction, updated)
            close()
            render()
            page.update()

        def change_decision(_):
            reason.visible = decision.value == "Pendente"
            page.update()

        if choices is not None:
            choices.on_change = select
        decision.on_change = change_decision
        details = [
            text(f"Fatura do Itaú • {_date(transaction.purchase_date)} • cartão final {transaction.card_last_four}",
                 muted=True),
            text(transaction.description, bold=True),
            text(_money(transaction.amount), bold=True, size=21),
            text(f"Titular do cartão: {transaction.cardholder}", muted=True),
            ft.Divider(color=colors()["border"]),
        ]
        if card_charge:
            charge_note = (
                f"Este item veio da fatura. Não encontramos lançamento interno de "
                f"{_money(transaction.amount)} na consulta. Confira o valor e selecione "
                "'Encargo conferido' se estiver correto."
                if not matches and selected_company != "Todos" else
                "Este item veio da fatura. Confira o valor e selecione 'Encargo conferido' "
                "se estiver correto. Não é necessário vincular um lançamento interno."
            )
            details.append(ft.Container(
                content=ft.Column([
                    text("Encargo do cartão", bold=True),
                    text(charge_note, muted=True, size=12),
                ], spacing=6),
                bgcolor=colors()["table"], border_radius=10, padding=14,
            ))
        if matches:
            details.extend([
                text("Lançamentos internos com o mesmo valor", bold=True),
                text("Selecione o lançamento e confira o documento antes de confirmar.",
                     muted=True, size=12),
                choices,
            ])
        elif not card_charge:
            details.append(ft.Container(
                content=ft.Column([
                    text("Empresa não selecionada." if selected_company == "Todos" else
                         "Sem lançamento interno correspondente.", bold=True),
                    text("Selecione a empresa na busca para procurar um lançamento interno."
                         if selected_company == "Todos" else
                         f"Esta cobrança consta na fatura, mas não encontramos um lançamento interno de "
                         f"{_money(transaction.amount)} para vinculá-la. Se precisar investigar, marque Pendente.",
                         muted=True, size=12),
                ], spacing=6),
                bgcolor=colors()["table"], border_radius=10, padding=14,
            ))
        details.extend([ft.Divider(color=colors()["border"]), decision, reason, error_label])
        detail_panel = ft.Column(details, spacing=12, scroll=ft.ScrollMode.AUTO)
        content = ft.Container(width=modal_width(900), height=compact_height, content=ft.Row([
            preview_box,
            divider,
            ft.Container(expand=5, padding=12, content=detail_panel),
        ], vertical_alignment=ft.CrossAxisAlignment.STRETCH))
        dialog = ft.AlertDialog(
            modal=True, bgcolor=colors()["surface"], title=text("Conferir item da fatura", bold=True, size=20),
            on_dismiss=lambda _: clear_preview() if clear_preview is not None else None,
            content=content,
            actions=[ft.TextButton("Cancelar", on_click=close),
                     ft.ElevatedButton("Salvar resultado", on_click=save)],
        )
        page.open(dialog)
        if selected_value:
            select()
    def download(_):
        if statement is None or download_file is None:
            return
        try:
            result = export_statement(statement, reviews, payments())
            url = download_file(result, f"fatura-conferida-{statement.due_date:%Y%m%d}.xlsx")
            page.launch_url(url, web_window_name="_self")
        except Exception:
            notice.value = "Não foi possível gerar a planilha conferida."
            page.update()

    export_button = ft.OutlinedButton("Baixar resultado", icon=ft.Icons.DOWNLOAD_OUTLINED,
                                      on_click=download, disabled=True)

    def change_filter(_):
        render()
        page.update()

    transaction_filter.on_change = change_filter

    def render():
        palette = colors()
        notice.color = palette["muted"]
        style_field(transaction_filter)
        upload_button.text = "Trocar fatura" if statement else "Carregar fatura XLSX"
        analyzed = sum(review.status != "A conferir" for review in reviews.values())
        total = len(statement.transactions) if statement else 0
        export_button.disabled = not analyzed or download_file is None
        export_button.text = "Baixar resultado" if analyzed == total else "Baixar parcial"
        summary = (f"{statement.company} • vence {_date(statement.due_date)} • "
                   f"{analyzed} de {total} itens analisados") if statement else (
                   "Carregue o XLSX exportado do Itaú para começar.")
        heading = ft.ResponsiveRow([
            ft.Container(ft.Column([text("Conferência da fatura", bold=True, size=20),
                                    text(summary, muted=True, size=13)], spacing=4),
                         col={"xs": 12, "md": 7}),
            ft.Container(ft.Row([upload_button, export_button], spacing=8, wrap=True,
                                alignment=ft.MainAxisAlignment.END), col={"xs": 12, "md": 5}),
        ], spacing=10, run_spacing=10)
        contents = [heading]
        if notice.value and (statement is None or notice.value != "Carregue o XLSX da fatura exportada do Itaú."):
            contents.append(notice)
        if statement is not None:
            lookup = lookup_state()
            if lookup:
                contents.append(text(lookup, color=palette["warning"] if
                                     lookup.startswith(("Não", "Selecione", "Ajuste")) else palette["muted"]))
            contents.append(text("Abra um item da fatura, confira o documento quando houver e marque o resultado.",
                                 muted=True, size=13))
            visible_items = filter_transactions(statement.transactions, payments(), company(),
                                                transaction_filter.value or "Todos")
            contents.append(ft.Row([
                transaction_filter,
                text(f"{len(visible_items)} de {total} itens", muted=True, size=13),
            ], spacing=12, wrap=True))
            def column(value, size, *, alignment=None):
                return ft.Container(content=value, expand=size, alignment=alignment)

            def table_line(cells, *, header=False):
                return ft.Container(
                    content=ft.Row([
                        column(cells[0], 5), column(cells[1], 2),
                        column(cells[2], 2, alignment=ft.alignment.center_right),
                        column(cells[3], 2), ft.Container(content=cells[4], width=112),
                    ], spacing=12, wrap=False, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor=palette["table"] if header else None,
                    padding=ft.padding.symmetric(horizontal=14, vertical=10),
                    border=None if header else ft.border.only(bottom=ft.BorderSide(1, palette["border"])),
                )

            lines = [table_line([text(name, bold=True, size=13) for name in
                                 ("Item da fatura", "Data", "Valor", "Resultado", "Ação")], header=True)]
            for transaction in visible_items:
                review = reviews.get(transaction.row_number, BankReview())
                status = "Não conferida" if review.status == "A conferir" else review.status
                status_color = palette["success"] if review.status in ("Conferido", CARD_CHARGE_STATUS) else (
                    palette["danger"] if review.status == "Pendente" else palette["muted"])
                lines.append(table_line([
                    text(transaction.description, bold=True, max_lines=2,
                         tooltip=transaction.description),
                    text(_date(transaction.purchase_date)),
                    text(_money(transaction.amount)),
                    text(status, color=status_color),
                    ft.OutlinedButton("Revisar" if review.status != "A conferir" else "Conferir",
                                      width=110, on_click=lambda _, item=transaction: review_transaction(item)),
                ]))
            if not visible_items:
                contents.append(text(
                    "Selecione uma empresa em 'Busca no CMFlex' para aplicar este filtro."
                    if company() == "Todos" and transaction_filter.value not in ("Todos", "Encargos") else
                    "Nenhum item neste filtro.", muted=True, size=13,
                ))
            contents.append(ft.Column(lines, spacing=0,
                                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        container.bgcolor = palette["surface"]
        container.border = ft.border.all(1, palette["border"])
        container.border_radius = 16
        container.padding = 16
        container.content = ft.Column(contents, spacing=10,
                                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    render()
    return BankPanelView(container, render, lambda: statement)
