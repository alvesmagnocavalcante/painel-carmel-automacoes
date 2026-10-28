"""Flet panel for Flash corporate card reconciliation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from secrets import token_urlsafe
from typing import Callable

import flet as ft

from automations.cartao_flash.attachment_view import flash_attachment_dialog
from automations.cartao_flash.data import (
    STATUS_PENDING_LAUNCH,
    STATUS_PENDING_SETTLEMENT,
    STATUS_SETTLED,
    CmflexFlashDocument,
    FlashReconciliationItem,
    FlashStatement,
    FlashTransaction,
    merge_flash_statements,
    normalize_text,
    parse_flash_statement,
)
from automations.cartao_flash.database import SqlFlashProvider
from automations.cartao_flash.export import export_flash_reconciliation, generate_email_text
from automations.cartao_flash.reconciliation import reconcile_flash_statement
from automations.cartao_flash.store import FlashStore
from portal.theme import get_palette, style_input

logger = logging.getLogger(__name__)

MAX_STATEMENT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class FlashPanelView:
    control: ft.Column
    apply_theme: Callable[[bool], None]
    resize: Callable[[], bool] = lambda: False


def _money(value: Decimal) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main(
    page: ft.Page,
    download_file: Callable[[bytes, str], str] | None = None,
    *,
    provider: SqlFlashProvider | None = None,
    upload_dir: str | None = None,
    store: FlashStore | None = None,
    available_width: Callable[[], float | None] | None = None,
) -> FlashPanelView:
    flash_provider = provider if provider is not None else SqlFlashProvider()
    flash_store = store if store is not None else FlashStore()

    dark = True
    statement: FlashStatement | None = None
    documents: tuple[CmflexFlashDocument, ...] = ()
    reconciled_items: tuple[FlashReconciliationItem, ...] = ()
    persisted_reviews: dict[str, tuple[str, str]] = {}
    is_loading = False

    filter_hotel_val = "Todos"
    filter_status_val = "Todos"
    filter_person_val = "Todos"
    search_query = ""

    def colors():
        return get_palette(dark)

    # Reusable containers matching the portal architecture
    # The portal body is already expanded by its parent Row. Keeping another
    # expanded Container/Column pair here makes Flet calculate a zero-height
    # content area in the web client, leaving only the header visible.
    content_area = ft.Container(padding=24)
    layout = ft.Column(
        expand=True,
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    # File picker configuration supporting single and multiple file uploads
    upload_map: dict[str, str] = {}
    pending_uploads: set[str] = set()
    completed_tokens: list[str] = []

    def on_upload_progress(e: ft.FilePickerUploadEvent):
        nonlocal upload_map, pending_uploads, completed_tokens
        if e.error:
            logger.error("Flash upload failed: %s", e.error)
            if upload_dir:
                for tok in upload_map.values():
                    (Path(upload_dir) / tok).unlink(missing_ok=True)
            upload_map = {}
            pending_uploads = set()
            completed_tokens = []
            page.snack_bar = ft.SnackBar(ft.Text(f"Erro no envio: {e.error}"), bgcolor="#DC2626")
            page.snack_bar.open = True
            page.update()
            return

        if e.progress < 1.0 or not upload_dir or not upload_map:
            return

        file_name = getattr(e, "file_name", None)
        if isinstance(file_name, str) and file_name in pending_uploads:
            pending_uploads.remove(file_name)
            completed_tokens.append(upload_map[file_name])
        elif pending_uploads:
            first_name = next(iter(pending_uploads))
            pending_uploads.remove(first_name)
            completed_tokens.append(upload_map[first_name])

        if pending_uploads:
            return

        tokens_to_process = list(completed_tokens)
        upload_map = {}
        pending_uploads = set()
        completed_tokens = []

        parsed_statements: list[FlashStatement] = []
        parse_errors: list[str] = []
        for tok in tokens_to_process:
            target = Path(upload_dir) / tok
            if not target.exists():
                continue
            try:
                loaded = parse_flash_statement(target.read_bytes(), file_name=target.name)
                if loaded.expense_transactions:
                    parsed_statements.append(loaded)
                else:
                    parse_errors.append(f"O arquivo {tok} não contém despesas válidas.")
            except (OSError, ValueError) as err:
                logger.warning("Failed to read Flash statement %s: %s", tok, err)
                parse_errors.append(
                    str(err) if isinstance(err, ValueError) else "Não foi possível ler o arquivo enviado."
                )
            except Exception:
                logger.exception("Unexpected error while reading Flash statement %s", tok)
                parse_errors.append("Arquivo inválido. Envie um CSV ou XLSX exportado pela Flash.")
            finally:
                target.unlink(missing_ok=True)

        if not parsed_statements:
            msg = parse_errors[0] if parse_errors else "Nenhuma despesa válida encontrada nos arquivos enviados."
            page.snack_bar = ft.SnackBar(ft.Text(msg), bgcolor="#DC2626")
            page.snack_bar.open = True
            page.update()
            return

        merged = merge_flash_statements(parsed_statements)
        on_statement_loaded(merged)

    def on_file_picked(e: ft.FilePickerResultEvent):
        nonlocal upload_map, pending_uploads, completed_tokens
        files = e.files or ()
        if not files:
            return

        upload_map = {}
        pending_uploads = set()
        completed_tokens = []
        upload_files: list[ft.FilePickerUploadFile] = []

        for idx, picked in enumerate(files):
            suffix = Path(picked.name).suffix.lower()
            if suffix not in {".csv", ".xlsx"} or (picked.size and picked.size > MAX_STATEMENT_BYTES):
                page.snack_bar = ft.SnackBar(
                    ft.Text(f"Arquivo '{picked.name}' inválido. Selecione CSV ou XLSX de até 5 MB."),
                    bgcolor="#DC2626",
                )
                page.snack_bar.open = True
                page.update()
                return

            token = f"flash_{token_urlsafe(16)}_{idx}{suffix}"
            upload_map[picked.name] = token
            pending_uploads.add(picked.name)
            upload_url = page.get_upload_url(token, 300)
            upload_files.append(ft.FilePickerUploadFile(name=picked.name, upload_url=upload_url))

        try:
            picker.upload(upload_files)
        except Exception:
            upload_map = {}
            pending_uploads = set()
            completed_tokens = []
            logger.exception("Failed to start Flash statements upload")
            page.snack_bar = ft.SnackBar(
                ft.Text("Não foi possível iniciar o envio dos arquivos."), bgcolor="#DC2626"
            )
            page.snack_bar.open = True
            page.update()

    picker = ft.FilePicker(on_result=on_file_picked, on_upload=on_upload_progress) if upload_dir else None
    if picker is not None:
        page.overlay.append(picker)

    def pick_file(_):
        if picker is not None:
            picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv", "xlsx"],
                allow_multiple=True,
            )

    async def load_cmflex_and_reconcile():
        nonlocal documents, reconciled_items, persisted_reviews, is_loading
        if not statement:
            return
        is_loading = True
        render()

        try:
            expenses = statement.expense_transactions
            start_date = min(tx.purchase_date for tx in expenses) - timedelta(days=30)
            # The provider uses an exclusive upper bound. Keep the same 30-day
            # matching window used by the reconciliation engine.
            end_date = max(tx.purchase_date for tx in expenses) + timedelta(days=31)
            persisted_reviews = await asyncio.to_thread(flash_store.load_reviews)
            documents = await asyncio.to_thread(
                flash_provider.fetch_documents,
                start_date=start_date,
                end_date=end_date,
            )
            reconciled_items = reconcile_flash_statement(
                expenses,
                documents,
                overrides=persisted_reviews,
            )
        except Exception as err:
            logger.error("Failed to fetch CMFlex documents: %s", err)
            page.snack_bar = ft.SnackBar(
                ft.Text(f"Erro ao consultar CMFlex: {err}"), bgcolor="#DC2626"
            )
            page.snack_bar.open = True
        finally:
            is_loading = False
            render()

    def on_statement_loaded(loaded: FlashStatement):
        nonlocal statement, documents, reconciled_items, persisted_reviews
        statement = loaded
        documents = ()
        reconciled_items = ()
        persisted_reviews = {}
        render()
        page.run_task(load_cmflex_and_reconcile)

    def get_filtered_items() -> tuple[FlashReconciliationItem, ...]:
        q = normalize_text(search_query)
        items: list[FlashReconciliationItem] = []
        for item in reconciled_items:
            if filter_status_val != "Todos" and item.status != filter_status_val:
                continue
            if filter_hotel_val != "Todos" and normalize_text(item.effective_hotel) != normalize_text(filter_hotel_val):
                continue
            if filter_person_val != "Todos" and normalize_text(item.transaction.person) != normalize_text(filter_person_val):
                continue
            if q:
                match_text = normalize_text(
                    f"{item.transaction.description} {item.transaction.person} "
                    f"{item.effective_hotel} {item.transaction.amount} "
                    f"{item.matched_document.launch_number if item.matched_document else ''} "
                    f"{item.matched_document.batch_id if item.matched_document else ''} "
                    f"{item.matched_document.display_batch if item.matched_document else ''} "
                    f"{item.matched_document.supplier if item.matched_document else ''}"
                )
                if q not in match_text:
                    continue
            items.append(item)
        return tuple(items)

    def open_email_draft_dialog(_):
        items = get_filtered_items()
        text = generate_email_text(items)

        def copy_to_clipboard(_):
            page.set_clipboard(text)
            page.snack_bar = ft.SnackBar(ft.Text("Resumo copiado para a área de transferência!"))
            page.snack_bar.open = True
            page.close(dlg)
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Resumo para E-mail"),
            content=ft.Container(
                content=ft.TextField(
                    value=text,
                    multiline=True,
                    read_only=True,
                    min_lines=12,
                    max_lines=18,
                    text_size=12,
                ),
                width=680,
                height=380,
            ),
            actions=[
                ft.TextButton("Copiar Texto", icon=ft.Icons.COPY, on_click=copy_to_clipboard),
                ft.TextButton("Fechar", on_click=lambda _: page.close(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)
        page.update()

    def open_edit_dialog(item: FlashReconciliationItem):
        note_field = ft.TextField(
            label="Anotação / Justificativa",
            value=item.manual_notes,
            expand=True,
            multiline=True,
        )
        status_dropdown = ft.Dropdown(
            label="Situação da Conferência",
            value=item.status,
            options=[
                ft.dropdown.Option(STATUS_PENDING_LAUNCH),
                ft.dropdown.Option(STATUS_PENDING_SETTLEMENT),
                ft.dropdown.Option(STATUS_SETTLED),
            ],
        )

        def save_changes(_):
            flash_store.save_review(
                item.transaction,
                status=status_dropdown.value or item.status,
                notes=note_field.value or "",
            )
            page.close(dlg)
            page.run_task(load_cmflex_and_reconcile)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Observação • {item.transaction.description}"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"Data: {item.transaction.purchase_date:%d/%m/%Y} | "
                        f"Valor: {_money(item.transaction.amount)} | "
                        f"Portador: {item.transaction.person}",
                        size=12,
                        color=colors()["muted"],
                    ),
                    status_dropdown,
                    note_field,
                ], spacing=14),
                width=520,
                height=260,
            ),
            actions=[
                ft.OutlinedButton("Cancelar", on_click=lambda _: page.close(dlg)),
                ft.FilledButton("Salvar", on_click=save_changes),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)
        page.update()

    def trigger_download(_):
        if not download_file or not reconciled_items:
            return
        xlsx_bytes = export_flash_reconciliation(reconciled_items)
        name = f"conferencia_cartao_flash_{date.today():%Y%m%d}.xlsx"
        url = download_file(xlsx_bytes, name)
        page.launch_url(url)

    def render():
        c = colors()

        # Build Header
        header = ft.Container(
            padding=ft.padding.symmetric(horizontal=32, vertical=20),
            border=ft.border.only(bottom=ft.BorderSide(1, c["border"])),
            bgcolor=c["surface"],
            content=ft.Column([
                ft.Text("CARTÃO FLASH • CONCILIAÇÃO CORPORATIVA", size=11, weight=ft.FontWeight.W_600, color=c["accent"]),
                ft.Text("Conferência de despesas Flash x CMFlex", size=24, weight=ft.FontWeight.W_600, color=c["text"]),
                ft.Text("Importe o extrato do Flash, confira com os lançamentos do CMFlex e gere cobranças.", size=13, color=c["muted"]),
            ], spacing=4),
        )

        # Build Main Body Content
        if statement is None:
            empty_view = ft.Container(
                height=420,
                alignment=ft.alignment.center,
                padding=60,
                content=ft.Column([
                    ft.Container(
                        ft.Icon(ft.Icons.PAYMENTS_OUTLINED, size=52, color=c["accent"]),
                        padding=20,
                        bgcolor=c["hero"],
                        border_radius=24,
                    ),
                    ft.Container(height=4),
                    ft.Text("Nenhum extrato do Flash carregado", size=20, weight=ft.FontWeight.W_600, color=c["text"]),
                    ft.Text("Importe um ou vários arquivos Excel (.xlsx) ou CSV da Flash para cruzar as despesas.",
                            size=14, color=c["muted"], text_align=ft.TextAlign.CENTER),
                    ft.Container(height=12),
                    ft.FilledButton(
                        "Importar extratos Flash (Excel / CSV)",
                        icon=ft.Icons.UPLOAD_FILE,
                        on_click=pick_file,
                        disabled=picker is None,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            )
            content_area.content = empty_view
        else:
            # Metrics bar
            pending_launch = [i for i in reconciled_items if i.status == STATUS_PENDING_LAUNCH]
            pending_settle = [i for i in reconciled_items if i.status == STATUS_PENDING_SETTLEMENT]
            settled = [i for i in reconciled_items if i.status == STATUS_SETTLED]

            val_total = sum((i.transaction.amount for i in reconciled_items), Decimal("0.00"))
            val_launch = sum((i.transaction.amount for i in pending_launch), Decimal("0.00"))
            val_settle = sum((i.transaction.amount for i in pending_settle), Decimal("0.00"))
            val_settled = sum((i.transaction.amount for i in settled), Decimal("0.00"))

            def kpi_card(title: str, count: int, val: Decimal, text_color: str, bg_color: str):
                return ft.Container(
                    content=ft.Column([
                        ft.Text(title.upper(), size=11, weight=ft.FontWeight.W_600, color=text_color),
                        ft.Row([
                            ft.Text(str(count), size=24, weight=ft.FontWeight.BOLD, color=c["text"]),
                            ft.Text(f"item{'s' if count != 1 else ''}", size=12, color=c["muted"]),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
                        ft.Text(_money(val), size=13, weight=ft.FontWeight.W_500, color=text_color),
                    ], spacing=4),
                    padding=16,
                    border_radius=12,
                    bgcolor=bg_color,
                    border=ft.border.all(1, c["border"]),
                    col={"xs": 12, "sm": 6, "md": 3},
                )

            metrics = ft.ResponsiveRow([
                kpi_card("Total em Despesas", len(reconciled_items), val_total, c["accent"], c["hero"]),
                kpi_card("Pendente de Lançamento", len(pending_launch), val_launch, "#EF4444", c["surface"]),
                kpi_card("Pendente de Prestação", len(pending_settle), val_settle, "#F59E0B", c["surface"]),
                kpi_card("Prestado Contas", len(settled), val_settled, "#10B981", c["surface"]),
            ], spacing=16, run_spacing=16)

            # Filter controls
            all_hotels = sorted({i.effective_hotel for i in reconciled_items if i.effective_hotel})
            all_persons = sorted({i.transaction.person for i in reconciled_items if i.transaction.person})

            hotel_dropdown = ft.Dropdown(
                label="Hotel / Empresa",
                value=filter_hotel_val,
                options=[ft.dropdown.Option("Todos")] + [ft.dropdown.Option(h) for h in all_hotels],
                width=200,
            )
            style_input(hotel_dropdown, c)

            def change_hotel(e):
                nonlocal filter_hotel_val
                filter_hotel_val = e.control.value
                render()

            hotel_dropdown.on_change = change_hotel

            status_dropdown = ft.Dropdown(
                label="Situação",
                value=filter_status_val,
                options=[
                    ft.dropdown.Option("Todos"),
                    ft.dropdown.Option(STATUS_PENDING_LAUNCH),
                    ft.dropdown.Option(STATUS_PENDING_SETTLEMENT),
                    ft.dropdown.Option(STATUS_SETTLED),
                ],
                width=220,
            )
            style_input(status_dropdown, c)

            def change_status(e):
                nonlocal filter_status_val
                filter_status_val = e.control.value
                render()

            status_dropdown.on_change = change_status

            person_dropdown = ft.Dropdown(
                label="Portador",
                value=filter_person_val,
                options=[ft.dropdown.Option("Todos")] + [ft.dropdown.Option(p) for p in all_persons],
                width=220,
            )
            style_input(person_dropdown, c)

            def change_person(e):
                nonlocal filter_person_val
                filter_person_val = e.control.value
                render()

            person_dropdown.on_change = change_person

            search_field = ft.TextField(
                label="Buscar estabelecimento, valor, documento ou lote",
                value=search_query,
                prefix_icon=ft.Icons.SEARCH,
            )
            style_input(search_field, c)

            def change_search(e):
                nonlocal search_query
                search_query = e.control.value
                render()

            search_field.on_change = change_search

            action_row = ft.Row([
                ft.FilledButton(
                    "Baixar Excel de Cobrança",
                    icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                    on_click=trigger_download,
                    disabled=is_loading or not reconciled_items,
                ),
                ft.OutlinedButton(
                    "Copiar resumo para e-mail",
                    icon=ft.Icons.EMAIL_OUTLINED,
                    on_click=open_email_draft_dialog,
                    disabled=is_loading or not reconciled_items,
                ),
                ft.OutlinedButton(
                    "Importar outros extratos",
                    icon=ft.Icons.UPLOAD_FILE_OUTLINED,
                    on_click=pick_file,
                    disabled=is_loading or picker is None,
                ),
                ft.IconButton(
                    ft.Icons.REFRESH,
                    tooltip="Recarregar CMFlex",
                    on_click=lambda _: page.run_task(load_cmflex_and_reconcile),
                    disabled=is_loading,
                ),
            ], spacing=10)

            # Table
            filtered_items = get_filtered_items()
            table_rows = []
            for item in filtered_items:
                tx = item.transaction
                doc = item.matched_document

                if item.status == STATUS_PENDING_LAUNCH:
                    status_color = "#EF4444"
                elif item.status == STATUS_PENDING_SETTLEMENT:
                    status_color = "#D97706"
                else:
                    status_color = "#10B981"

                table_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(tx.purchase_date.strftime("%d/%m/%Y"), size=12, color=c["text"])),
                            ft.DataCell(ft.Text(
                                tx.description,
                                size=12,
                                color=c["text"],
                                no_wrap=True,
                                tooltip=" | ".join(
                                    value for value in (tx.description, tx.payment_method) if value
                                ),
                            )),
                            ft.DataCell(ft.Text(_money(tx.amount), size=12, weight=ft.FontWeight.W_600, color=c["text"])),
                            ft.DataCell(ft.Text(tx.person, size=12, color=c["text"], no_wrap=True)),
                            ft.DataCell(ft.Text(item.effective_hotel, size=12, color=c["muted"], no_wrap=True)),
                            ft.DataCell(ft.Text(
                                item.status,
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=status_color,
                                no_wrap=True,
                            )),
                            ft.DataCell(ft.Text(
                                f"#{doc.launch_number} ({doc.display_batch}) | {doc.supplier} | {doc.company}"
                                if doc else "Não lançado no ERP",
                                size=12,
                                color=c["text"] if doc else "#EF4444",
                                no_wrap=True,
                                tooltip=f"Situação no CMFlex: {doc.cmflex_situation}" if doc and doc.cmflex_situation else None,
                            )),
                            ft.DataCell(ft.IconButton(
                                ft.Icons.ATTACH_FILE,
                                tooltip=f"Ver anexo ({doc.attachment_count})" if doc and doc.attachment_count else "Sem anexo",
                                disabled=not (doc and doc.attachment_count > 0),
                                icon_color=c["info"],
                                on_click=lambda _, d=doc: flash_attachment_dialog(page, d, flash_provider, c, download_file),
                            )),
                            ft.DataCell(ft.IconButton(
                                ft.Icons.EDIT_NOTE,
                                tooltip="Editar anotação",
                                icon_color=c["accent"],
                                on_click=lambda _, it=item: open_edit_dialog(it),
                            )),
                        ]
                    )
                )

            def compute_target_width() -> int:
                if available_width is not None:
                    aw = available_width()
                    if isinstance(aw, (int, float)) and aw > 600:
                        return int(aw)
                if isinstance(page.width, (int, float)) and page.width > 600:
                    return int(page.width - 150)
                return 1200

            target_width = max(1150, compute_target_width())
            extra_width = max(0, target_width - 1100)
            dynamic_spacing = 22 + (extra_width // 8)

            data_table = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Data", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Movimentação / Estabelecimento", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Valor", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Portador", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Hotel", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Situação", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Documento CMFlex", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Anexo", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                    ft.DataColumn(ft.Text("Editar", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ],
                rows=table_rows,
                width=target_width,
                heading_row_color=c["soft"],
                horizontal_margin=24,
                column_spacing=dynamic_spacing,
                heading_row_height=56,
                data_row_min_height=58,
                data_row_max_height=68,
            )

            if isinstance(page.height, (int, float)) and page.height > 600:
                max_viewport = max(550, min(860, int(page.height) - 340))
            else:
                max_viewport = 640

            viewport_height = min(max_viewport, 56 + max(1, len(table_rows)) * 64 + 20)
            table_body = ft.Column(
                [data_table],
                width=target_width,
                height=viewport_height,
                scroll=ft.ScrollMode.ALWAYS,
            )

            table_container = ft.Column([
                ft.Row([
                    ft.Text(f"Exibindo {len(filtered_items)} de {len(reconciled_items)} compras", size=13, color=c["muted"]),
                ]),
                ft.Container(
                    content=ft.Row(
                        [table_body],
                        height=viewport_height,
                        scroll=ft.ScrollMode.ALWAYS,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    border=ft.border.all(1, c["border"]),
                    border_radius=8,
                    bgcolor=c["surface"],
                ),
            ], spacing=8)

            filters_row = ft.Row(
                [hotel_dropdown, status_dropdown, person_dropdown],
                wrap=True,
                spacing=12,
            )

            content_area.content = ft.Column(
                [
                    ft.ProgressBar(visible=is_loading, color=c["accent"]),
                    metrics,
                    filters_row,
                    search_field,
                    action_row,
                    table_container,
                ],
                spacing=16,
            )

        layout.controls = [header, content_area]
        if page:
            page.update()

    def resize() -> bool:
        if statement is not None:
            render()
            return True
        return False

    def apply_theme(is_dark: bool):
        nonlocal dark
        dark = is_dark
        render()

    render()
    return FlashPanelView(control=layout, apply_theme=apply_theme, resize=resize)
