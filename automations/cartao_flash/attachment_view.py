"""In-memory PDF preview dialog for Flash CMFlex attachments."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import flet as ft

from automations.cartao_flash.attachments import render_pdf_page
from automations.cartao_flash.data import CmflexFlashDocument
from automations.cartao_flash.database import FlashAttachmentMeta, SqlFlashProvider

logger = logging.getLogger(__name__)


def flash_attachment_dialog(
    page: ft.Page,
    document: CmflexFlashDocument,
    provider: SqlFlashProvider,
    colors: dict[str, str],
    download_file: Callable[[bytes, str], str] | None = None,
) -> None:
    """Open an interactive modal dialog previewing document attachments."""
    attachments: tuple[FlashAttachmentMeta, ...] = ()
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
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        boundary_margin=0,
        expand=True,
        visible=False,
    )

    content_box = ft.Column(
        [
            ft.Row([selector, download_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row(
                [prev_btn, counter, next_btn, ft.Container(width=16), zoom_out, zoom_label, zoom_in, zoom_reset],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            ),
            ft.Container(
                content=ft.Column([notice, viewer], expand=True),
                expand=True,
                border=ft.border.all(1, colors.get("border", "#374151")),
                border_radius=8,
                padding=10,
                bgcolor=colors.get("background", "#12100E"),
            ),
        ],
        expand=True,
        spacing=10,
    )

    def apply_zoom(enabled: bool):
        image.width = 700 * zoom / 100
        zoom_label.value = f"{zoom}%"
        zoom_out.disabled = not enabled or zoom <= 50
        zoom_in.disabled = not enabled or zoom >= 200
        zoom_reset.disabled = not enabled or zoom == 100
        if page:
            page.update()

    def render_current_page():
        nonlocal page_count
        if not current_content:
            return
        try:
            base64_data, count = render_pdf_page(current_content, page_index)
            page_count = count
            image.src_base64 = base64_data
            image.visible = True
            viewer.visible = True
            notice.visible = False
            counter.value = f"{page_index + 1} de {page_count}"
            prev_btn.disabled = page_index <= 0
            next_btn.disabled = page_index >= page_count - 1
            apply_zoom(True)
        except Exception as err:
            logger.warning("Failed to render PDF: %s", err)
            image.visible = False
            viewer.visible = False
            notice.value = f"Não foi possível visualizar este anexo: {err}"
            notice.visible = True
            apply_zoom(False)
        if page:
            page.update()

    def select_attachment(e):
        nonlocal current_content, page_index
        att_id_str = selector.value
        if not att_id_str:
            return
        att_id = int(att_id_str)
        matched_meta = next((a for a in attachments if a.id == att_id), None)
        try:
            current_content = provider.read_attachment_bytes(att_id)
            page_index = 0
            if download_file and matched_meta:
                download_btn.disabled = False
                download_btn.on_click = lambda _: page.launch_url(
                    download_file(current_content, matched_meta.name)
                )
            render_current_page()
        except Exception as err:
            notice.value = f"Erro ao abrir anexo: {err}"
            notice.visible = True
            image.visible = False
            viewer.visible = False
            if page:
                page.update()

    selector.on_change = select_attachment

    def on_prev(_):
        nonlocal page_index
        if page_index > 0:
            page_index -= 1
            render_current_page()

    def on_next(_):
        nonlocal page_index
        if page_index < page_count - 1:
            page_index += 1
            render_current_page()

    prev_btn.on_click = on_prev
    next_btn.on_click = on_next

    def on_zoom_in(_):
        nonlocal zoom
        zoom = min(200, zoom + 25)
        apply_zoom(True)

    def on_zoom_out(_):
        nonlocal zoom
        zoom = max(50, zoom - 25)
        apply_zoom(True)

    def on_zoom_reset(_):
        nonlocal zoom
        zoom = 100
        apply_zoom(True)

    zoom_in.on_click = on_zoom_in
    zoom_out.on_click = on_zoom_out
    zoom_reset.on_click = on_zoom_reset

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Anexos • Doc #{document.launch_number} - {document.supplier}"),
        content=ft.Container(content=content_box, width=820, height=540),
        actions=[
            ft.TextButton("Fechar", on_click=lambda _: page.close(dialog)),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    page.open(dialog)

    # Load attachment list
    try:
        attachments = provider.fetch_attachments(document.document_id, document.company_id)
        if not attachments:
            notice.value = "Este documento não possui anexos cadastrados no CMFlex."
            selector.disabled = True
        else:
            selector.options = [ft.dropdown.Option(str(a.id), a.name) for a in attachments]
            selector.value = str(attachments[0].id)
            selector.disabled = False
            select_attachment(None)
    except Exception as err:
        notice.value = f"Erro ao buscar anexos: {err}"
    if page:
        page.update()
