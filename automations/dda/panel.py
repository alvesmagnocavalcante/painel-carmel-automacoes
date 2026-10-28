"""Interactive Flet panel for DDA reconciliation."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Sequence

import flet as ft

from automations.dda.attachment_view import dda_attachment_dialog
from automations.dda.data import (
    ALL_STATUSES,
    STATUS_LANC,
    STATUS_LANC_OC,
    STATUS_NAO_LANC,
    CmflexOpenDocument,
    DdaReconciliationItem,
    DdaTransaction,
    clean_tax_id,
    format_tax_id,
    normalize_text,
    parse_cmflex_export_workbook,
    parse_dda_file,
    parse_dda_workbook,
)
from automations.dda.database import SqlDdaProvider
from automations.dda.export import export_dda_reconciliation, generate_collection_email
from automations.dda.reconciliation import reconcile_dda
from automations.dda.store import DdaStore
from portal.theme import FONT_DISPLAY, get_palette

logger = logging.getLogger(__name__)


def _money(val: Decimal | float | int) -> str:
    """Format Decimal as Brazilian currency string."""
    try:
        d = Decimal(str(val))
        return f"R$ {d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {val}"


def style_input(ctrl: ft.Control, c: dict[str, str]) -> None:
    ctrl.border_color = c["border"]
    ctrl.focused_border_color = c["accent"]
    ctrl.cursor_color = c["accent"]
    ctrl.color = c["text"]
    if hasattr(ctrl, "label_style"):
        ctrl.label_style = ft.TextStyle(color=c["muted"])


def main(
    page: ft.Page,
    download_file: Callable[[bytes, str], str] | None = None,
    provider: SqlDdaProvider | None = None,
    upload_dir: str | Path | None = None,
    store: DdaStore | None = None,
    available_width: Callable[[], int | None] | None = None,
) -> SimpleNamespace:
    """Build and return the DDA reconciliation panel view."""
    dda_provider = provider or SqlDdaProvider()
    dda_store = store or DdaStore()

    dark = True
    is_loading = False
    transactions: tuple[DdaTransaction, ...] = ()
    documents: tuple[CmflexOpenDocument, ...] = ()
    reconciled_items: tuple[DdaReconciliationItem, ...] = ()
    dda_file_name = ""

    filter_sheet_val = "Todas"
    filter_status_val = "Todos"
    filter_responsible_val = "Todos"
    search_query = ""

    content_area = ft.Container(padding=24)
    layout = ft.Column(
        expand=True,
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    # File upload handling
    pending_uploads: dict[str, str] = {}

    def on_file_picked(e: ft.FilePickerResultEvent):
        nonlocal is_loading
        if not e.files:
            return
        pending_uploads.clear()
        is_loading = True
        render()

        for f in e.files:
            token = f"{f.name}"
            upload_url = page.get_upload_url(token, 600)
            pending_uploads[f.name] = token
            if picker:
                picker.upload([ft.FilePickerUploadFile(f.name, upload_url=upload_url)])

    def on_upload_progress(e: ft.FilePickerUploadEvent):
        nonlocal dda_file_name, is_loading, transactions
        if e.error:
            logger.error("Upload error: %s", e.error)
            page.snack_bar = ft.SnackBar(ft.Text(f"Erro no upload: {e.error}"), bgcolor="#DC2626")
            page.snack_bar.open = True
            is_loading = False
            render()
            return

        if e.progress < 1.0:
            return

        # Find uploaded file
        uploaded_token = None
        if e.file_name and isinstance(e.file_name, str) and e.file_name in pending_uploads:
            uploaded_token = pending_uploads.pop(e.file_name)
        elif pending_uploads:
            uploaded_token = pending_uploads.pop(next(iter(pending_uploads)))

        if not uploaded_token or not upload_dir:
            is_loading = False
            render()
            return

        file_path = Path(upload_dir) / uploaded_token
        try:
            raw_data = file_path.read_bytes()
            # Try parsing as DDA spreadsheet or CSV
            parsed_txs = parse_dda_file(raw_data, file_name=uploaded_token)
            if not parsed_txs:
                # Try parsing as CMFlex open payments spreadsheet
                parsed_docs = parse_cmflex_export_workbook(raw_data)
                if parsed_docs:
                    on_cmflex_docs_loaded(parsed_docs)
                    page.snack_bar = ft.SnackBar(
                        ft.Text(f"{len(parsed_docs)} títulos carregados do CMFlex com sucesso!"),
                        bgcolor="#10B981",
                    )
                    page.snack_bar.open = True
                    return
                raise ValueError("Nenhum boleto válido encontrado no arquivo. Verifique se é uma planilha ou CSV do DDA.")

            transactions = parsed_txs
            dda_file_name = uploaded_token
            on_dda_loaded()
        except Exception as err:
            logger.error("Falha ao ler arquivo: %s", err)
            page.snack_bar = ft.SnackBar(ft.Text(f"Erro ao processar: {err}"), bgcolor="#DC2626")
            page.snack_bar.open = True
        finally:
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass
            is_loading = False
            render()

    picker = ft.FilePicker(on_result=on_file_picked, on_upload=on_upload_progress) if upload_dir else None
    if picker is not None:
        page.overlay.append(picker)

    def pick_file(_):
        if picker is not None:
            picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx", "xls", "csv", "txt"],
                allow_multiple=False,
            )

    async def load_cmflex_and_reconcile():
        nonlocal documents, reconciled_items, is_loading
        is_loading = True
        render()

        try:
            start_date = None
            end_date = None
            if transactions:
                valid_dates = [tx.due_date for tx in transactions if tx.due_date]
                if valid_dates:
                    start_date = min(valid_dates) - timedelta(days=35)
                    end_date = max(valid_dates) + timedelta(days=35)

            docs = await asyncio.to_thread(
                dda_provider.fetch_open_documents,
                start_date=start_date,
                end_date=end_date,
            )
            documents = docs

            items = reconcile_dda(transactions, documents)
            dda_store.apply_reviews(items)
            reconciled_items = items
        except Exception as err:
            logger.error("Erro ao carregar títulos do CMFlex: %s", err)
            page.snack_bar = ft.SnackBar(
                ft.Text(f"Erro ao consultar CMFlex: {err}"), bgcolor="#DC2626"
            )
            page.snack_bar.open = True
        finally:
            is_loading = False
            render()

    def on_dda_loaded():
        page.run_task(load_cmflex_and_reconcile)

    def on_cmflex_docs_loaded(loaded_docs: tuple[CmflexOpenDocument, ...]):
        nonlocal documents, reconciled_items
        documents = loaded_docs
        if transactions:
            items = reconcile_dda(transactions, documents)
            dda_store.apply_reviews(items)
            reconciled_items = items
            render()

    def get_filtered_items() -> tuple[DdaReconciliationItem, ...]:
        q = normalize_text(search_query)
        items: list[DdaReconciliationItem] = []
        for item in reconciled_items:
            tx = item.transaction
            doc = item.matched_document

            if filter_sheet_val != "Todas" and normalize_text(tx.sheet_name) != normalize_text(filter_sheet_val):
                continue
            if filter_status_val != "Todos" and normalize_text(item.effective_status) != normalize_text(filter_status_val):
                continue
            if filter_responsible_val != "Todos" and normalize_text(item.effective_responsible) != normalize_text(filter_responsible_val):
                continue

            if q:
                match_text = normalize_text(
                    f"{tx.sheet_name} {tx.company} {tx.supplier} {tx.tax_id} {tx.document_number} {tx.amount} "
                    f"{item.effective_status} {item.effective_observation} {item.effective_responsible} "
                    f"{doc.launch_number if doc else ''} {doc.reference if doc else ''}"
                )
                if q not in match_text:
                    continue
            items.append(item)
        return tuple(items)

    def open_email_draft_dialog(_):
        items = get_filtered_items()
        text = generate_collection_email(items)

        def copy_to_clipboard(_):
            page.set_clipboard(text)
            page.snack_bar = ft.SnackBar(ft.Text("Resumo de cobrança copiado!"), bgcolor="#10B981")
            page.snack_bar.open = True
            page.close(dlg)
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.EMAIL_OUTLINED, color=c["accent"]),
                ft.Text("Cobrança de Pendências • Contas a Pagar", size=16, weight=ft.FontWeight.W_600),
            ]),
            content=ft.Container(
                content=ft.TextField(
                    value=text,
                    multiline=True,
                    read_only=True,
                    min_lines=14,
                    max_lines=20,
                    text_size=12,
                    border_color=c["border"],
                    color=c["text"],
                ),
                width=720,
            ),
            actions=[
                ft.TextButton("Fechar", on_click=lambda _: page.close(dlg)),
                ft.FilledButton("Copiar texto", icon=ft.Icons.COPY, on_click=copy_to_clipboard),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def open_edit_dialog(item: DdaReconciliationItem):
        status_dropdown = ft.Dropdown(
            label="Situação",
            value=item.effective_status,
            options=[ft.dropdown.Option(st) for st in ALL_STATUSES],
            expand=True,
        )
        style_input(status_dropdown, c)

        obs_field = ft.TextField(
            label="Observação / Motivo",
            value=item.effective_observation,
            multiline=True,
            min_lines=2,
            max_lines=4,
            expand=True,
        )
        style_input(obs_field, c)

        resp_field = ft.TextField(
            label="Responsável pelo Lançamento",
            value=item.effective_responsible,
            expand=True,
        )
        style_input(resp_field, c)

        def save_and_close(_):
            item.custom_status = status_dropdown.value
            item.custom_observation = obs_field.value.strip() if obs_field.value else ""
            item.custom_responsible = resp_field.value.strip() if resp_field.value else ""

            dda_store.save_review(
                item.transaction,
                custom_status=item.custom_status,
                custom_observation=item.custom_observation,
                custom_responsible=item.custom_responsible,
            )
            page.close(dlg)
            render()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar Lançamento DDA", size=16, weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"{item.transaction.supplier}", size=13, weight=ft.FontWeight.W_600, color=c["text"]),
                    ft.Text(f"Valor: {_money(item.transaction.amount)} | Venc: {item.transaction.due_date.strftime('%d/%m/%Y') if item.transaction.due_date else 'S/D'}", size=12, color=c["muted"]),
                    ft.Divider(color=c["border"], height=16),
                    status_dropdown,
                    obs_field,
                    resp_field,
                ], spacing=12, tight=True),
                width=500,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: page.close(dlg)),
                ft.FilledButton("Salvar", icon=ft.Icons.SAVE, on_click=save_and_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def trigger_download(_):
        if not download_file or not reconciled_items:
            return
        try:
            excel_bytes = export_dda_reconciliation(reconciled_items)
            dt_tag = date.today().strftime("%Y%m%d")
            filename = f"conferencia_dda_{dt_tag}.xlsx"
            download_file(excel_bytes, filename)
            page.snack_bar = ft.SnackBar(ft.Text("Download iniciado!"), bgcolor="#10B981")
            page.snack_bar.open = True
            page.update()
        except Exception as err:
            logger.error("Export error: %s", err)
            page.snack_bar = ft.SnackBar(ft.Text(f"Erro ao exportar: {err}"), bgcolor="#DC2626")
            page.snack_bar.open = True
            page.update()

    def render():
        nonlocal c
        c = get_palette(dark)

        # Build Header
        header = ft.Container(
            padding=ft.padding.symmetric(horizontal=32, vertical=20),
            border=ft.border.only(bottom=ft.BorderSide(1, c["border"])),
            bgcolor=c["surface"],
            content=ft.Column([
                ft.Text("DDA • DÉBITO DIRETO AUTORIZADO", size=11, weight=ft.FontWeight.W_600, color=c["accent"]),
                ft.Text("Conferência da Planilha do DDA", size=24, weight=ft.FontWeight.W_600, color=c["text"]),
                ft.Text("Importe a planilha de boletos do Itaú, concilie com os títulos em aberto do CMFlex e analise os anexos.", size=13, color=c["muted"]),
            ], spacing=4),
        )

        if not transactions:
            empty_view = ft.Container(
                height=420,
                alignment=ft.alignment.center,
                padding=60,
                content=ft.Column([
                    ft.Container(
                        ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=52, color=c["accent"]),
                        padding=20,
                        bgcolor=c["hero"],
                        border_radius=24,
                    ),
                    ft.Container(height=4),
                    ft.Text("Nenhum arquivo do DDA carregado", size=20, weight=ft.FontWeight.W_600, color=c["text"]),
                    ft.Text("Importe a planilha Excel (.xlsx) ou extrato do Itaú (.csv) para cruzar com os títulos do CMFlex.",
                            size=14, color=c["muted"], text_align=ft.TextAlign.CENTER),
                    ft.Container(height=12),
                    ft.FilledButton(
                        "Importar boletos Itaú (Excel / CSV)",
                        icon=ft.Icons.UPLOAD_FILE,
                        on_click=pick_file,
                        disabled=is_loading or picker is None,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            )
            content_area.content = empty_view
            layout.controls = [header, content_area]
            if page:
                page.update()
            return

        # Metrics
        total_count = len(reconciled_items)
        total_val = sum(it.transaction.amount for it in reconciled_items)
        lanc_items = [it for it in reconciled_items if it.effective_status == STATUS_LANC]
        nao_lanc_items = [it for it in reconciled_items if it.effective_status == STATUS_NAO_LANC]
        lanc_oc_items = [it for it in reconciled_items if it.effective_status == STATUS_LANC_OC]

        # Available options for filters
        sheets = sorted({it.transaction.sheet_name for it in reconciled_items if it.transaction.sheet_name})
        responsaveis = sorted({it.effective_responsible for it in reconciled_items if it.effective_responsible})

        def metric_card(title: str, value: str, sub: str, icon: str, color_hex: str):
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(icon, color=color_hex, size=20),
                        ft.Text(title, size=11, color=c["muted"], weight=ft.FontWeight.W_600),
                    ], spacing=6),
                    ft.Text(value, size=22, weight=ft.FontWeight.W_700, color=c["text"]),
                    ft.Text(sub, size=11, color=c["muted"]),
                ], spacing=4),
                padding=16,
                border_radius=12,
                bgcolor=c["surface"],
                border=ft.border.all(1, c["border"]),
                expand=True,
            )

        metrics_row = ft.Row([
            metric_card("TOTAL DDA", str(total_count), _money(total_val), ft.Icons.RECEIPT_LONG_OUTLINED, c["info"]),
            metric_card("LANÇADOS NO ERP", str(len(lanc_items)), _money(sum(it.transaction.amount for it in lanc_items)), ft.Icons.CHECK_CIRCLE_OUTLINE, "#10B981"),
            metric_card("NÃO LANÇADOS", str(len(nao_lanc_items)), _money(sum(it.transaction.amount for it in nao_lanc_items)), ft.Icons.ERROR_OUTLINE, "#EF4444"),
            metric_card("LANÇADOS OC", str(len(lanc_oc_items)), _money(sum(it.transaction.amount for it in lanc_oc_items)), ft.Icons.WARNING_AMBER_OUTLINED, "#F59E0B"),
        ], spacing=14)

        # Filters
        sheet_dropdown = ft.Dropdown(
            label="Aba / Unidade",
            value=filter_sheet_val,
            options=[ft.dropdown.Option("Todas"), *[ft.dropdown.Option(s) for s in sheets]],
            width=180,
        )
        style_input(sheet_dropdown, c)

        def change_sheet(e):
            nonlocal filter_sheet_val
            filter_sheet_val = e.control.value or "Todas"
            render()

        sheet_dropdown.on_change = change_sheet

        status_dropdown = ft.Dropdown(
            label="Situação",
            value=filter_status_val,
            options=[
                ft.dropdown.Option("Todos"),
                ft.dropdown.Option(STATUS_LANC),
                ft.dropdown.Option(STATUS_NAO_LANC),
                ft.dropdown.Option(STATUS_LANC_OC),
            ],
            width=180,
        )
        style_input(status_dropdown, c)

        def change_status(e):
            nonlocal filter_status_val
            filter_status_val = e.control.value or "Todos"
            render()

        status_dropdown.on_change = change_status

        resp_dropdown = ft.Dropdown(
            label="Responsável",
            value=filter_responsible_val,
            options=[ft.dropdown.Option("Todos"), *[ft.dropdown.Option(r) for r in responsaveis]],
            width=240,
        )
        style_input(resp_dropdown, c)

        def change_resp(e):
            nonlocal filter_responsible_val
            filter_responsible_val = e.control.value or "Todos"
            render()

        resp_dropdown.on_change = change_resp

        search_field = ft.TextField(
            label="Buscar fornecedor, CNPJ, valor ou documento",
            value=search_query,
            prefix_icon=ft.Icons.SEARCH,
        )
        style_input(search_field, c)

        def on_search(e):
            nonlocal search_query
            search_query = e.control.value
            render()

        search_field.on_change = on_search

        action_row = ft.Row([
            ft.FilledButton(
                "Baixar Planilha Conferida",
                icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                on_click=trigger_download,
                disabled=is_loading or not reconciled_items,
            ),
            ft.OutlinedButton(
                "Copiar Cobrança para E-mail",
                icon=ft.Icons.EMAIL_OUTLINED,
                on_click=open_email_draft_dialog,
                disabled=is_loading or not reconciled_items,
            ),
            ft.OutlinedButton(
                "Importar outra planilha",
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

        # Build table rows
        filtered = get_filtered_items()
        table_rows = []

        for item in filtered:
            tx = item.transaction
            doc = item.matched_document
            st_val = item.effective_status
            obs_val = item.effective_observation
            resp_val = item.effective_responsible

            if st_val == STATUS_LANC:
                st_color = "#10B981"
            elif st_val == STATUS_NAO_LANC:
                st_color = "#EF4444"
            else:
                st_color = "#F59E0B"

            has_obs_pendency = obs_val and obs_val not in ("SEM ALTERAÇÃO", "OK")

            table_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(tx.sheet_name, size=11, weight=ft.FontWeight.W_600, color=c["accent"])),
                        ft.DataCell(ft.Text(tx.due_date.strftime("%d/%m/%Y") if tx.due_date else "—", size=12, color=c["text"])),
                        ft.DataCell(ft.Text(tx.supplier, size=12, color=c["text"], no_wrap=True, tooltip=tx.supplier)),
                        ft.DataCell(ft.Text(tx.formatted_cnpj, size=11, color=c["muted"], no_wrap=True)),
                        ft.DataCell(ft.Text(tx.document_number or "—", size=12, color=c["text"], no_wrap=True)),
                        ft.DataCell(ft.Text(_money(tx.amount), size=12, weight=ft.FontWeight.W_600, color=c["text"])),
                        ft.DataCell(ft.Text(st_val, size=11, weight=ft.FontWeight.W_700, color=st_color, no_wrap=True)),
                        ft.DataCell(ft.Container(
                            content=ft.Text(obs_val or "OK", size=11, weight=ft.FontWeight.W_600 if has_obs_pendency else ft.FontWeight.NORMAL, color="#B45309" if has_obs_pendency else c["muted"], no_wrap=True),
                            padding=ft.padding.symmetric(horizontal=6, vertical=2) if has_obs_pendency else None,
                            border_radius=4,
                            bgcolor="#FEF08A" if has_obs_pendency and not dark else "#453408" if has_obs_pendency else None,
                        )),
                        ft.DataCell(ft.Text(resp_val or "—", size=12, weight=ft.FontWeight.W_600 if resp_val else ft.FontWeight.NORMAL, color=c["text"], no_wrap=True)),
                        ft.DataCell(ft.Text(
                            f"#{doc.launch_number} ({doc.installment}) | {doc.company}" if doc else "Não lançado no ERP",
                            size=12,
                            color=c["text"] if doc else "#EF4444",
                            no_wrap=True,
                            tooltip=f"Histórico: {doc.history}" if doc and doc.history else None,
                        )),
                        ft.DataCell(ft.IconButton(
                            ft.Icons.ATTACH_FILE,
                            tooltip=f"Ver anexo ({doc.attachment_count})" if doc and doc.attachment_count else "Sem anexo",
                            disabled=not (doc and doc.attachment_count > 0),
                            icon_color=c["info"],
                            on_click=lambda _, d=doc: dda_attachment_dialog(page, d, dda_provider, c, download_file),
                        )),
                        ft.DataCell(ft.IconButton(
                            ft.Icons.EDIT_NOTE,
                            tooltip="Editar status e observações",
                            icon_color=c["accent"],
                            on_click=lambda _, it=item: open_edit_dialog(it),
                        )),
                    ]
                )
            )

        def compute_width() -> int:
            if available_width is not None:
                aw = available_width()
                if isinstance(aw, (int, float)) and aw > 700:
                    return int(aw)
            if isinstance(page.width, (int, float)) and page.width > 700:
                return int(page.width - 150)
            return 1300

        target_width = max(1250, compute_width())
        extra_width = max(0, target_width - 1200)
        col_spacing = 16 + (extra_width // 12)

        data_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Unidade", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Vencimento", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Fornecedor / Favorecido", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("CNPJ", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Documento", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Valor DDA", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Situação", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Observação", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Responsável", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Documento CMFlex", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Anexo", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
                ft.DataColumn(ft.Text("Ações", size=12, weight=ft.FontWeight.W_600, color=c["muted"])),
            ],
            rows=table_rows,
            width=target_width,
            heading_row_color=c["soft"],
            horizontal_margin=20,
            column_spacing=col_spacing,
            heading_row_height=52,
            data_row_min_height=54,
            data_row_max_height=64,
        )

        if isinstance(page.height, (int, float)) and page.height > 600:
            max_viewport = max(500, min(800, int(page.height) - 360))
        else:
            max_viewport = 600

        viewport_height = min(max_viewport, 52 + max(1, len(table_rows)) * 60 + 20)
        table_body = ft.Column([data_table], width=target_width, height=viewport_height, scroll=ft.ScrollMode.ALWAYS)

        table_card = ft.Container(
            content=ft.Row([table_body], scroll=ft.ScrollMode.ALWAYS),
            border=ft.border.all(1, c["border"]),
            border_radius=12,
            bgcolor=c["surface"],
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

        filters_row = ft.Row([sheet_dropdown, status_dropdown, resp_dropdown], spacing=10, wrap=True)
        info_bar = ft.Row([
            ft.Text(f"Exibindo {len(filtered)} de {len(reconciled_items)} boletos", size=13, color=c["muted"]),
            ft.Container(expand=True),
            ft.Text(f"Arquivo: {dda_file_name}", size=12, color=c["muted"]) if dda_file_name else ft.Container(),
        ])

        content_area.content = ft.Column([
            ft.ProgressBar(visible=is_loading, color=c["accent"]),
            metrics_row,
            filters_row,
            search_field,
            action_row,
            info_bar,
            table_card,
        ], spacing=16)

        layout.controls = [header, content_area]
        if page:
            page.update()

    c = get_palette(dark)
    render()

    def apply_theme(is_dark: bool):
        nonlocal dark
        dark = is_dark
        render()

    def resize():
        render()

    return SimpleNamespace(
        control=layout,
        apply_theme=apply_theme,
        resize=resize,
    )
