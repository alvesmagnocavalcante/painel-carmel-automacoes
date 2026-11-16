"""Action plan UI: HTTP source, saved manual fields and filtered downloads."""

import asyncio
import logging

import flet as ft

from automations.inventario.action_export import export_actions_excel, export_actions_pdf, slugify
from automations.inventario.action_plan import ActionStore, AuditApi, ManualFields, STATUSES, parse_date
from automations.inventario.view import InventoryView, empty_state, inventory_header, table_height
from portal.theme import DARK, LIGHT, PRIMARY, panel_text, style_input, surface_card

STATUS_SEMANTIC = {
    "Não iniciada": "muted",
    "Em andamento": "info",
    "Replanejada": "warning",
    "Atrasada": "danger",
    "Concluída": "success",
}


def main(page, download_file=None, *, provider=None, store=None, available_width=None):
    if not page.web:
        raise RuntimeError("O plano de ação funciona apenas no navegador.")
    source = provider if provider is not None else AuditApi()
    storage = store
    rows, dark, busy = (), True, False
    message, failed = "Atualize pela API ou carregue os registros já salvos neste servidor.", False
    company = ft.Dropdown(label="Hotel", value="Todos", options=[ft.dropdown.Option("Todos")], expand=True, col={"xs": 12, "md": 4})
    month = ft.Dropdown(label="Mês do inventário", value="Todos", options=[ft.dropdown.Option("Todos")], expand=True, col={"xs": 12, "md": 4})
    status = ft.Dropdown(label="Status", value="Todos", options=[ft.dropdown.Option(value) for value in ("Todos", *STATUSES)], expand=True, col={"xs": 12, "md": 4})
    search = ft.TextField(label="Pesquisar pontos de melhoria, respostas ou responsável", prefix_icon=ft.Icons.SEARCH, expand=True)
    # Period by days: an inventory at the start of a month and another at the end
    # of it must be downloadable separately.
    period_enabled = ft.Checkbox(label="Filtrar período do inventário", value=False)
    start_field = ft.TextField(label="Data inicial", hint_text="DD/MM/AAAA", max_length=10, col={"xs": 12, "md": 4})
    end_field = ft.TextField(label="Data final", hint_text="DD/MM/AAAA", max_length=10, col={"xs": 12, "md": 4})
    period_controls = ft.ResponsiveRow([start_field, end_field], visible=False, spacing=14, run_spacing=14)
    layout = ft.Column(expand=True, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    rendered_width = 0

    def db():
        nonlocal storage
        if storage is None:
            storage = ActionStore()
        return storage

    def palette():
        return DARK if dark else LIGHT

    def text(value, **kwargs):
        return panel_text(value, palette(), **kwargs)

    def surface(content):
        return surface_card(content, palette(), radius=16, padding=18)

    def month_key(item):
        try:
            value = parse_date(item.inventory_date)
            return value.strftime("%Y-%m") if value else "Sem data"
        except ValueError:
            return "Sem data"

    def period():
        """(start, end) when the period filter is on, None when off; ValueError when invalid."""
        if not period_enabled.value:
            return None
        try:
            start, end = parse_date(start_field.value or ""), parse_date(end_field.value or "")
        except ValueError as error:
            raise ValueError("Informe as datas no formato DD/MM/AAAA.") from error
        if start is None or end is None:
            raise ValueError("Informe a data inicial e a data final do período.")
        if start > end:
            raise ValueError("A data inicial deve ser anterior ou igual à data final.")
        return start, end

    def in_period(item, bounds):
        if bounds is None:
            return True
        try:
            day = parse_date(item.inventory_date)
        except ValueError:
            return False
        return day is not None and bounds[0] <= day <= bounds[1]

    def selected():
        query = (search.value or "").strip().casefold()
        try:
            bounds = period()
        except ValueError:
            return ()  # never export or show a selection the filter could not apply
        return tuple(item for item in rows if (company.value == "Todos" or company.value == item.hotel)
            and in_period(item, bounds)
            and (month.value == "Todos" or month.value == month_key(item))
            and (status.value == "Todos" or status.value == item.manual.status())
            and (not query or query in f"{item.hotel} {item.improvement} {item.manual.how} {item.manual.responsible} {' '.join(value for _, value in item.details)}".casefold()))

    def update_options():
        hotels = ["Todos", *sorted({item.hotel for item in rows})]
        months = ["Todos", *sorted({month_key(item) for item in rows}, reverse=True)]
        company.options = [ft.dropdown.Option(value) for value in hotels]
        month.options = [ft.dropdown.Option(value) for value in months]
        if company.value not in hotels:
            company.value = "Todos"
        if month.value not in months:
            month.value = "Todos"

    def answers(item):
        """Remaining form answers (checklist, comments, photos, author e-mail)."""
        colors = palette()
        if not item.details:
            return text("Sem respostas adicionais da auditoria.", muted=True, size=12)
        return ft.ExpansionTile(
            title=text(f"Respostas da auditoria ({len(item.details)})", bold=True),
            controls=[ft.Container(ft.Column([ft.Column([
                text(label, muted=True, size=12), text(value, selectable=True)], spacing=2, tight=True)
                for label, value in item.details], spacing=10), padding=ft.padding.only(left=16, right=8, bottom=12))],
            tile_padding=ft.padding.all(0), collapsed_text_color=colors["text"], text_color=colors["text"])

    def pick_date(field):
        def changed(event):
            field.value = event.control.value.strftime("%d/%m/%Y")
            render()
            page.update()
        page.open(ft.DatePicker(on_change=changed))

    def edit(item):
        colors = palette()
        fields = {}
        for key, label in (("how", "Como?"), ("responsible", "Responsável"), ("start", "Início"),
                           ("due", "Término"), ("revised", "Novo prazo"), ("completed", "Data realizada"),
                           ("progress", "% concluído"), ("notes", "Observações")):
            is_date = key in ("start", "due", "revised", "completed")
            fields[key] = ft.TextField(label=label, value=str(getattr(item.manual, key)),
                multiline=key in ("how", "notes"), min_lines=2 if key in ("how", "notes") else 1,
                max_lines=5 if key in ("how", "notes") else 1,
                hint_text="DD/MM/AAAA" if is_date else "0 a 100" if key == "progress" else None,
                col={"xs": 12, "md": 6} if is_date else {"xs": 12},
                color=colors["text"], label_style=ft.TextStyle(color=colors["muted"]))
            if is_date:
                def choose_date(_, key=key):
                    def changed(event):
                        fields[key].value = event.control.value.strftime("%d/%m/%Y")
                        page.update()
                    page.open(ft.DatePicker(on_change=changed))
                fields[key].suffix = ft.IconButton(ft.Icons.CALENDAR_MONTH, tooltip="Selecionar data", on_click=choose_date)
        error_text = ft.Text(color=colors["warning"])

        async def save(_):
            nonlocal rows
            save_button.disabled = True
            page.update()
            try:
                values = {key: (control.value or "").strip() for key, control in fields.items()}
                try:
                    values["progress"] = int(values["progress"])
                except ValueError as error:
                    raise ValueError("Preencha o percentual concluído de 0 a 100.") from error
                manual = ManualFields(**values).validate()
                await asyncio.to_thread(db().save, item, manual)
                rows = await asyncio.to_thread(db().list)
                page.close(dialog)
                render()
            except Exception as error:
                logging.getLogger(__name__).exception("Falha ao salvar plano de ação")
                error_text.value = str(error) if isinstance(error, ValueError) else "Não foi possível salvar. Tente novamente."
            finally:
                save_button.disabled = False
                page.update()

        save_button = ft.ElevatedButton("Salvar ação", on_click=save)
        dialog = ft.AlertDialog(modal=True, title=text("Preencher plano de ação", bold=True, size=20),
            bgcolor=colors["surface"], content=ft.Container(width=740, height=610, content=ft.Column([
                text(f"{item.hotel} • Inventário: {item.inventory_date}", bold=True),
                text("O quê? — importado da API", muted=True, size=12),
                text(item.improvement or "Nenhum ponto de melhoria informado nesta auditoria.", selectable=True),
                answers(item), ft.Divider(), ft.ResponsiveRow(list(fields.values()), spacing=14, run_spacing=14), error_text,
            ], scroll=ft.ScrollMode.AUTO, spacing=12)),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: page.close(dialog)), save_button])
        page.open(dialog)

    def table_width():
        available = available_width() if available_width is not None else None
        return int(available) if isinstance(available, (int, float)) and available > 0 else 1300

    def text_widths():
        """Fixed columns stay compact; the two long-text columns share what is left."""
        flexible = max(380, table_width() - 820)
        return {2: int(flexible * 0.6), 3: int(flexible * 0.4)}

    def table(items, height):
        colors = palette()
        flexible = text_widths()
        headers = ("Hotel", "Inventário", "O quê?", "Como?", "Responsável", "Término", "% concluído", "Status", "Editar")
        data_rows = []
        for item in items:
            values = (item.hotel, item.inventory_date, item.improvement, item.manual.how,
                      item.manual.responsible, item.manual.revised or item.manual.due,
                      f"{item.manual.progress}%", item.manual.status())
            cells = []
            for index, value in enumerate(values):
                if index == 7:
                    semantic = STATUS_SEMANTIC[value]
                    cells.append(ft.DataCell(ft.Container(
                        ft.Text(value, size=12, weight=ft.FontWeight.W_600, color=colors[semantic]),
                        bgcolor=colors[f"{semantic}_soft"] if semantic != "muted" else colors["soft"],
                        padding=ft.padding.symmetric(horizontal=12, vertical=7), border_radius=20)))
                    continue
                width = flexible.get(index) or (120 if index in (0, 4) else 90 if index == 6 else 100)
                cells.append(ft.DataCell(ft.Container(text(value or "—", max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
                                                     width=width, tooltip=value or None)))
            cells.append(ft.DataCell(ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip="Preencher ação",
                icon_color=colors["info"], disabled=busy, on_click=lambda _, item=item: edit(item))))
            data_rows.append(ft.DataRow(cells=cells))
        grid = ft.DataTable(columns=[ft.DataColumn(text(label, bold=True)) for label in headers], rows=data_rows,
                            heading_row_color=colors["table"], data_row_min_height=72, data_row_max_height=86,
                            heading_row_height=50, column_spacing=10, horizontal_margin=12)
        return ft.Row([ft.Column([grid], height=height, scroll=ft.ScrollMode.ALWAYS)],
                      height=height, scroll=ft.ScrollMode.ALWAYS, vertical_alignment=ft.CrossAxisAlignment.START)

    def render():
        nonlocal rendered_width
        rendered_width = table_width()
        colors = palette()
        items = selected()
        for control in (company, month, status, search, start_field, end_field):
            control.disabled = busy
            style_input(control, colors)
        period_enabled.disabled = busy
        period_enabled.label_style = ft.TextStyle(color=colors["text"])
        period_enabled.check_color, period_enabled.active_color = "#FFFFFF", PRIMARY
        period_controls.visible = bool(period_enabled.value)
        for field in (start_field, end_field):
            field.suffix = ft.IconButton(ft.Icons.CALENDAR_MONTH, tooltip="Selecionar data", disabled=busy,
                                         on_click=lambda _, field=field: pick_date(field))
        try:
            period()
            period_error = ""
        except ValueError as error:
            period_error = str(error)
        refresh_button.disabled = saved_button.disabled = busy
        for button in (excel_button, pdf_button):
            button.disabled = busy or not items or download_file is None
            button.color = colors["text"]
        excel_button.icon_color, pdf_button.icon_color, saved_button.color = colors["success"], colors["danger"], colors["text"]
        counts = {label: sum(item.manual.status() == label for item in items) for label in STATUSES}
        metrics = [
            ft.Container(surface_card(ft.Column([
                text(label, muted=True, size=11),
                ft.Text(str(value), size=20, weight=ft.FontWeight.W_600,
                        color=colors["text" if label == "Total de ações" else STATUS_SEMANTIC[label]]),
            ], spacing=2, tight=True), colors, radius=12, padding=12), col={"xs": 6, "md": 4, "xl": 2})
            for label, value in (("Total de ações", len(items)), *counts.items())
        ]
        results = table(items, table_height(page, len(rows), row_height=80)) if items else empty_state(
            text("Nenhum plano de ação na seleção.", muted=True))
        layout.controls = [
            inventory_header(
                page,
                colors,
                "Plano de ação do inventário",
                "Pontos de melhoria da API com acompanhamento e preenchimento manual.",
                category="INVENTÁRIO • PLANO DE AÇÃO",
                action_plan=True,
            ),
            ft.Container(ft.Column([
                ft.ResponsiveRow(metrics, spacing=12, run_spacing=12),
                surface(ft.Column([
                    ft.Row([text("Consulta e filtros", bold=True, size=17),
                            ft.Row([refresh_button, saved_button], wrap=True, spacing=10)],
                           wrap=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.ResponsiveRow([company, month, status], spacing=14, run_spacing=14), search,
                    period_enabled, period_controls,
                    text(period_error or message, color=colors["warning"] if period_error else None,
                         muted=not (failed or period_error)),
                ], spacing=14)),
                surface(ft.Column([
                    ft.Row([text("Acompanhamento das ações", bold=True, size=18),
                            ft.Row([excel_button, pdf_button], wrap=True)],
                           wrap=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    text("Use o lápis para preencher. Os downloads incluem exatamente os registros filtrados, inclusive o período escolhido.", muted=True, size=12), results,
                ], spacing=14)),
            ], spacing=14, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), padding=24, expand=True),
        ]

    async def load(from_api):
        nonlocal rows, busy, message, failed
        if busy:
            return
        busy, failed, message = True, False, "Carregando plano de ação…"
        render()
        page.update()
        try:
            if from_api:
                incoming = await asyncio.to_thread(source.fetch)
                await asyncio.to_thread(db().sync, incoming)
            rows = await asyncio.to_thread(db().list)
            update_options()
            message = f"{len(rows)} registros salvos carregados. " + ("API atualizada; campos manuais preservados." if from_api else "Exibindo dados salvos, sem consultar a API.")
        except Exception as error:
            logging.getLogger(__name__).exception("Falha ao carregar plano de ação")
            failed = True
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Não foi possível carregar o plano de ação. Os dados anteriores foram mantidos."
        finally:
            busy = False
            render()
            page.update()

    async def download(kind):
        nonlocal busy, failed, message
        items = selected()
        if busy or not items or download_file is None:
            return
        busy = True
        render()
        page.update()
        try:
            exporter = export_actions_excel if kind == "xlsx" else export_actions_pdf
            bounds = period()
            labels, stem = [], ["plano-acao-inventario"]
            if company.value != "Todos":
                labels.append(f"Hotel: {company.value}")
                stem.append(slugify(company.value))
            if bounds:
                labels.append(f"Período: {bounds[0]:%d/%m/%Y} a {bounds[1]:%d/%m/%Y}")
                stem += [f"{bounds[0]:%Y%m%d}", f"{bounds[1]:%Y%m%d}"]
            content = await asyncio.to_thread(exporter, items, " | ".join(labels))
            stem = "-".join(stem)
            page.launch_url(download_file(content, f"{stem}.{kind}"), web_window_name="_self")
        except Exception:
            logging.getLogger(__name__).exception("Falha ao exportar plano de ação")
            failed, message = True, "Não foi possível gerar o arquivo. Confira a instalação das dependências."
        finally:
            busy = False
            render()
            page.update()

    async def refresh(_):
        await load(True)

    async def load_saved(_):
        await load(False)

    async def excel(_):
        await download("xlsx")

    async def pdf(_):
        await download("pdf")

    def changed(_):
        render()
        page.update()

    def apply_theme(is_dark):
        nonlocal dark
        dark = is_dark
        render()

    button_style = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), elevation=0)
    refresh_button = ft.ElevatedButton("Atualizar pela API", icon=ft.Icons.SYNC, bgcolor=PRIMARY,
        color="#FFFFFF", height=44, style=button_style, on_click=refresh)
    saved_button = ft.OutlinedButton("Carregar salvos", icon=ft.Icons.FOLDER_OPEN_OUTLINED,
        height=44, style=button_style, on_click=load_saved)
    excel_button = ft.OutlinedButton("Baixar Excel", icon=ft.Icons.DOWNLOAD, icon_color=palette()["success"],
        height=42, style=button_style, on_click=excel)
    pdf_button = ft.OutlinedButton("Baixar PDF", icon=ft.Icons.PICTURE_AS_PDF_OUTLINED,
        icon_color=palette()["danger"], height=42, style=button_style, on_click=pdf)
    company.on_change = month.on_change = status.on_change = search.on_change = changed
    period_enabled.on_change = start_field.on_change = end_field.on_change = changed
    render()
    def resize():
        if rendered_width == table_width():
            return False
        render()
        return True

    return InventoryView(layout, apply_theme, resize)
