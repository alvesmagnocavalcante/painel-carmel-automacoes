"""PDF preview controls for the payment review dialog."""

import asyncio
import logging

import flet as ft

from automations.bordero.attachments import AttachmentSource, render_pdf_page


def attachment_view(page, row, download_file=None, colors=None):
    colors = colors or {}
    source = AttachmentSource()
    attachments = ()
    content = b""
    selected = None
    page_index = 0
    page_count = 0
    generation = 0
    active = True
    zoom = 100
    notice = ft.Text("Carregando anexos…", selectable=True)
    image = ft.Image(fit=ft.ImageFit.CONTAIN, width=800, visible=False)
    counter = ft.Text("")
    previous = ft.IconButton(ft.Icons.CHEVRON_LEFT, icon_color=colors.get("info"), tooltip="Página anterior", disabled=True)
    following = ft.IconButton(ft.Icons.CHEVRON_RIGHT, icon_color=colors.get("info"), tooltip="Próxima página", disabled=True)
    zoom_label = ft.Text("100%")
    zoom_out = ft.IconButton(ft.Icons.ZOOM_OUT, icon_color=colors.get("info"), tooltip="Diminuir PDF", disabled=True)
    zoom_in = ft.IconButton(ft.Icons.ZOOM_IN, icon_color=colors.get("info"), tooltip="Ampliar PDF", disabled=True)
    zoom_reset = ft.IconButton(ft.Icons.RESTART_ALT, icon_color=colors.get("info"), tooltip="Restaurar zoom", disabled=True)
    selector = ft.Dropdown(
        label="Anexo", disabled=True, expand=True,
        bgcolor=colors.get("surface"), color=colors.get("text"),
        text_style=ft.TextStyle(color=colors.get("text")),
        label_style=ft.TextStyle(color=colors.get("muted")),
        hover_color=colors.get("soft"), focused_bgcolor=colors.get("soft"),
    )
    download = ft.IconButton(ft.Icons.DOWNLOAD, icon_color=colors.get("success"), tooltip="Baixar anexo", disabled=True, visible=download_file is not None)
    viewer = ft.InteractiveViewer(
        # Flet validates the direct child even when the viewer is hidden.
        # Keep this wrapper visible while the inner image is loading/cleared.
        ft.Container(content=image), pan_enabled=True, scale_enabled=False, constrained=False,
        alignment=ft.alignment.top_left, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        boundary_margin=0, expand=True, visible=False,
    )
    body = ft.Column([notice, viewer], expand=True)
    panel = ft.Column([
        ft.Text("Documento para conferência", size=18, weight=ft.FontWeight.W_600),
        ft.Row([selector, download]),
        ft.Row([previous, counter, following, ft.Container(width=12), zoom_out, zoom_label, zoom_in, zoom_reset],
               alignment=ft.MainAxisAlignment.CENTER, wrap=True, spacing=4),
        ft.Text("Clique e arraste o documento para visualizar outras regiões.", size=12, color=colors.get("muted")),
        body,
    ], expand=True)

    def update_zoom(enabled):
        image.width = 800 * zoom / 100
        viewer.visible = enabled and image.visible
        zoom_label.value = f"{zoom}%"
        zoom_out.disabled = not enabled or zoom == 50
        zoom_in.disabled = not enabled or zoom == 200
        zoom_reset.disabled = not enabled

    def reset_position():
        # Flet invokes methods only after the control has been mounted.
        if active and image.visible and viewer.uid:
            viewer.reset(animation_duration=150)

    def restore(_):
        if not active or not image.visible:
            return
        set_zoom(100)
        reset_position()

    def set_zoom(value):
        nonlocal zoom
        if not active or not image.visible:
            return
        zoom = max(50, min(200, value))
        update_zoom(True)
        page.update()

    def clear():
        nonlocal active, generation, content, attachments
        active = False
        generation += 1
        content = b""
        attachments = ()
        image.src_base64 = None
        image.visible = False
        update_zoom(False)

    def error_message(error):
        logging.getLogger(__name__).exception("Falha ao visualizar anexo do borderô")
        return str(error) if isinstance(error, (ValueError, RuntimeError)) else "Não foi possível visualizar o anexo. Tente novamente."

    async def show(index):
        nonlocal page_index, page_count
        revision = generation
        previous.disabled = following.disabled = True
        notice.value = "Carregando página…"
        notice.visible = True
        page.update()

        try:
            encoded, count = await asyncio.to_thread(render_pdf_page, content, index)
            if not active or revision != generation:
                return
            page_index, page_count = index, count
            image.src_base64, image.visible = encoded, True
            update_zoom(True)
            notice.visible = False
            counter.value = f"Página {index + 1} de {count}"
            previous.disabled = index == 0
            following.disabled = index + 1 == count
        except Exception as error:
            if not active or revision != generation:
                return
            image.visible = False
            update_zoom(False)
            notice.value = error_message(error)
            counter.value = ""
        page.update()
        if active and revision == generation and image.visible:
            reset_position()

    async def choose(_):
        nonlocal content, selected, generation, zoom
        generation += 1
        revision = generation
        selected = next((item for item in attachments if str(item.id) == selector.value), None)
        content = b""
        image.visible = False
        zoom = 100
        update_zoom(False)
        download.disabled = previous.disabled = following.disabled = True
        counter.value = ""
        notice.value, notice.visible = "Carregando documento…", True
        page.update()
        if selected is None:
            return
        try:
            data = await asyncio.to_thread(source.read, row, selected)
            if not active or revision != generation:
                return
            content = data
            download.disabled = False
            await show(0)
        except Exception as error:
            if active and revision == generation:
                notice.value = error_message(error)
                page.update()

    async def load():
        nonlocal attachments
        try:
            items = await asyncio.to_thread(source.list, row)
            if not active:
                return
            attachments = items
            if not items:
                notice.value = "Nenhum anexo disponível para este pagamento."
                page.update()
                return
            selector.options = [ft.dropdown.Option(str(item.id), item.name) for item in items]
            selector.value, selector.disabled = str(items[0].id), False
            await choose(None)
        except Exception as error:
            if active:
                notice.value = error_message(error)
                page.update()

    async def back(_):
        if page_index > 0:
            await show(page_index - 1)

    async def forward(_):
        if page_index + 1 < page_count:
            await show(page_index + 1)

    def save_file(_):
        if content and selected and download_file:
            try:
                page.launch_url(download_file(content, selected.name), web_window_name="_self")
            except Exception as error:
                notice.value, notice.visible = error_message(error), True
                page.update()

    selector.on_change = choose
    previous.on_click, following.on_click = back, forward
    download.on_click = save_file
    zoom_out.on_click = lambda _: set_zoom(zoom - 25)
    zoom_in.on_click = lambda _: set_zoom(zoom + 25)
    zoom_reset.on_click = restore
    return panel, load, clear
