"""In-memory PDF preview dialog for DDA CMFlex attachments."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import flet as ft

from automations.cartao_flash.attachments import render_pdf_page
from automations.dda.data import CmflexOpenDocument
from automations.dda.database import SqlDdaProvider

logger = logging.getLogger(__name__)


def dda_attachment_dialog(
    page: ft.Page,
    document: CmflexOpenDocument,
    provider: SqlDdaProvider,
    colors: dict[str, str],
    download_file: Callable[[bytes, str], str] | None = None,
) -> None:
    """Open an interactive modal dialog previewing document attachments."""
    attachments: list[dict[str, object]] = []
    current_content = b""
    page_index = 0
    page_count = 0
    zoom = 100
    active = True

    notice = ft.Text("Carregando anexos…", color=colors.get("muted", "#9CA3AF"))
    image = ft.Image(fit=ft.ImageFit.CONTAIN, width=700, visible=False)
    counter = ft.Text("", color=colors.get("text", "#F3F4F6"), weight=ft.FontWeight.W_500)

    prev_btn = ft.IconButton(
        ft.Icons.CHEVRON_LEFT,
        tooltip="Página anterior",
        disabled=True,
        icon_color=colors.get("info", "#38BDF8"),
    )
    next_btn = ft.IconButton(
        ft.Icons.CHEVRON_RIGHT,
        tooltip="Próxima página",
        disabled=True,
        icon_color=colors.get("info", "#38BDF8"),
    )
    zoom_label = ft.Text("100%", color=colors.get("text", "#F3F4F6"))
    zoom_out = ft.IconButton(
        ft.Icons.ZOOM_OUT,
        tooltip="Diminuir",
        disabled=True,
        icon_color=colors.get("info", "#38BDF8"),
    )
    zoom_in = ft.IconButton(
        ft.Icons.ZOOM_IN,
        tooltip="Ampliar",
        disabled=True,
        icon_color=colors.get("info", "#38BDF8"),
    )
    zoom_reset = ft.IconButton(
        ft.Icons.RESTART_ALT,
        tooltip="100%",
        disabled=True,
        icon_color=colors.get("info", "#38BDF8"),
    )

    selector = ft.Dropdown(
        label="Selecione o anexo",
        disabled=True,
        expand=True,
        bgcolor=colors.get("surface", "#1E1A18"),
        color=colors.get("text", "#F3F4F6"),
    )

    download_btn = ft.IconButton(
        ft.Icons.DOWNLOAD,
        tooltip="Baixar anexo",
        disabled=True,
        visible=download_file is not None,
        icon_color=colors.get("success", "#10B981"),
    )

    viewer = ft.InteractiveViewer(
        ft.Container(content=image),
        pan_enabled=True,
        scale_enabled=False,
        constrained=False,
        alignment=ft.alignment.top_left,
    )

    def close_dialog(_=None):
        nonlocal active
        active = False
        dialog.open = False
        page.update()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Icon(ft.Icons.ATTACH_FILE, color=colors.get("accent", "#C8956A")),
            ft.Text(f"Anexos • Doc #{document.launch_number} ({document.company})", size=16, weight=ft.FontWeight.W_600),
        ]),
        content=ft.Container(
            content=ft.Column([
                ft.Row([selector, download_btn], spacing=10),
                ft.Row([
                    prev_btn,
                    counter,
                    next_btn,
                    ft.Container(expand=True),
                    zoom_out,
                    zoom_label,
                    zoom_in,
                    zoom_reset,
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(
                    content=ft.Stack([
                        ft.Container(content=notice, alignment=ft.alignment.center),
                        viewer,
                    ]),
                    height=520,
                    width=740,
                    border=ft.border.all(1, colors.get("border", "#374151")),
                    border_radius=8,
                    bgcolor=colors.get("soft", "#141110"),
                ),
            ], spacing=10, tight=True),
            width=760,
        ),
        actions=[
            ft.TextButton("Fechar", on_click=close_dialog),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def update_controls():
        if not active:
            return
        has_pdf = page_count > 0
        prev_btn.disabled = not has_pdf or page_index <= 0
        next_btn.disabled = not has_pdf or page_index >= page_count - 1
        counter.value = f"Pág. {page_index + 1} de {page_count}" if has_pdf else ""
        zoom_label.value = f"{zoom}%"
        zoom_out.disabled = not has_pdf or zoom <= 50
        zoom_in.disabled = not has_pdf or zoom >= 250
        zoom_reset.disabled = not has_pdf or zoom == 100
        download_btn.disabled = len(current_content) == 0
        image.width = int(700 * (zoom / 100.0))
        page.update()

    def show_page(index: int):
        nonlocal page_index, page_count
        if not current_content:
            return
        try:
            b64, count = render_pdf_page(current_content, index)
            page_index = index
            page_count = count
            image.src_base64 = b64
            image.visible = True
            notice.visible = False
        except Exception as ex:
            logger.warning("Falha ao renderizar PDF: %s", ex)
            image.visible = False
            notice.visible = True
            notice.value = f"Não foi possível visualizar este anexo: {ex}"
        update_controls()

    def on_attachment_selected(e):
        nonlocal current_content, page_index, zoom
        idx = int(e.control.value)
        meta = attachments[idx]
        current_content = bytes(meta.get("conteudo") or b"")
        page_index = 0
        zoom = 100
        show_page(0)

    selector.on_change = on_attachment_selected

    def change_page(delta: int):
        new_idx = page_index + delta
        if 0 <= new_idx < page_count:
            show_page(new_idx)

    prev_btn.on_click = lambda _: change_page(-1)
    next_btn.on_click = lambda _: change_page(1)

    def change_zoom(delta: int):
        nonlocal zoom
        zoom = max(50, min(250, zoom + delta))
        update_controls()

    zoom_out.on_click = lambda _: change_zoom(-25)
    zoom_in.on_click = lambda _: change_zoom(25)
    zoom_reset.on_click = lambda _: change_zoom(100 - zoom)

    def trigger_download(_):
        if not current_content or not download_file or selector.value is None:
            return
        idx = int(selector.value)
        filename = str(attachments[idx].get("annomedoarquivo") or f"anexo_doc_{document.launch_number}.pdf")
        download_file(current_content, filename)

    download_btn.on_click = trigger_download

    async def load():
        nonlocal attachments
        try:
            raw = await asyncio.to_thread(
                provider.fetch_attachments_for_document,
                document.document_id,
                document.company_id,
            )
            attachments = raw
            if not active:
                return
            if not attachments:
                notice.value = "Nenhum anexo encontrado para este lançamento."
                page.update()
                return

            selector.options = [
                ft.dropdown.Option(
                    key=str(i),
                    text=f"{a.get('annomedoarquivo') or 'Anexo'} ({int(a.get('size') or 0) // 1024} KB)",
                )
                for i, a in enumerate(attachments)
            ]
            selector.value = "0"
            selector.disabled = False
            selector.on_change(type("Event", (), {"control": selector})())
        except Exception as ex:
            if active:
                notice.value = f"Erro ao carregar anexos: {ex}"
                page.update()

    page.overlay.append(dialog)
    dialog.open = True
    page.update()
    page.run_task(load)
