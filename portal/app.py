"""Web portal navigation; payment conference rules remain in the Bordero module."""

import flet as ft

from automations.bordero.panel import main as build_bordero
from automations.inventario.panel import main as build_inventory
from automations.inventario.financial_panel import main as build_financial_inventory
from automations.inventario.action_panel import main as build_action_plan
from automations.cartoes_credito.panel import main as build_cards
from automations.cartao_flash.panel import main as build_flash
from portal.components import module_card, nav_item
from portal.theme import FONT_DISPLAY, get_palette


def main(page, web_download, attachment_download=None, card_upload_dir=None):
    dark = True
    collapsed = False
    body = ft.Container(expand=True)
    sidebar = ft.Container(width=224, padding=18, animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT))

    def palette():
        return get_palette(dark)

    def home():
        colors = palette()

        def card(name, title, description, icon, route, button, semantic):
            return module_card(name, title, description, icon, route, button, semantic, colors, page.go)

        return ft.Container(padding=32, content=ft.Column([
            ft.Container(ft.ResponsiveRow([
                ft.Container(ft.Column([
                    ft.Text("FINANCEIRO • CARMEL HOTÉIS", size=11, weight=ft.FontWeight.W_600,
                            color=colors["accent"]),
                    ft.Text("Central de automações financeiras", size=42, font_family=FONT_DISPLAY,
                            weight=ft.FontWeight.W_600, color=colors["text"]),
                    ft.Text("Conferência, acompanhamento e controle em um só lugar.",
                            size=14, color=colors["muted"]),
                ], spacing=14), col={"xs": 12, "lg": 9}),
                ft.Container(ft.Image(src="/carmel-symbol-white.png" if dark else "/carmel-symbol-brown.png",
                    width=110, height=90, fit=ft.ImageFit.CONTAIN, semantics_label="Símbolo Carmel"),
                    col={"xs": 12, "lg": 3}, alignment=ft.alignment.center_right,
                    visible=isinstance(page.width, (int, float)) and page.width >= 1100),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=30, border_radius=22,
                bgcolor=colors["hero"], border=ft.border.all(1, colors["border"])),
            ft.Container(height=12),
            ft.Text("Automações disponíveis", size=18, weight=ft.FontWeight.W_600, color=colors["text"]),
            ft.Text("Selecione a automação para começar.", size=13, color=colors["muted"]),
            ft.Container(height=4),
            ft.ResponsiveRow([
                card("Borderô", "Conferência de pagamentos em aberto",
                     "Consulte o período, confira os anexos e classifique os pagamentos.",
                     ft.Icons.FACT_CHECK_OUTLINED, "/bordero", "Abrir conferência", "info"),
                card("Inventário", "Conferência mensal dos almoxarifados",
                     "Contagens, impacto financeiro e plano de ação dos almoxarifados.",
                     ft.Icons.INVENTORY_2_OUTLINED, "/inventario", "Consultar inventário", "money"),
                card("Cartões de crédito", "Conferência de faturas e anexos",
                     "Importe a fatura XLSX, confira os PDFs e registre pendências.",
                     ft.Icons.CREDIT_CARD_OUTLINED, "/cartoes", "Conferir cartões", "warning"),
                card("Cartão Flash", "Conciliação de despesas corporativas",
                     "Importe o extrato Flash, identifique pendências no ERP e gere cobranças.",
                     ft.Icons.BOLT_OUTLINED, "/flash", "Conferir Flash", "money"),
            ], spacing=20, run_spacing=20),
        ], spacing=10, scroll=ft.ScrollMode.AUTO))

    def navigation():
        colors = palette()

        def item(label, icon, route):
            return nav_item(label, icon, route, page.route, collapsed, colors, page.go)

        sidebar.bgcolor = colors["surface"]
        sidebar.width = 76 if collapsed else 224
        sidebar.padding = 10 if collapsed else 18
        sidebar.border = ft.border.only(right=ft.BorderSide(1, colors["border"]))
        if collapsed:
            brand = ft.Image(
                src="/carmel-symbol-white.png" if dark else "/carmel-symbol-brown.png",
                width=56, height=52, fit=ft.ImageFit.CONTAIN,
                semantics_label="Símbolo Carmel Hotéis",
            )
        else:
            # Tint the original transparent logo instead of recreating its lettering.
            brand = ft.Image(src="/carmel-logo.png", width=188, height=90,
                             color="#FFFFFF" if dark else None,
                             color_blend_mode=ft.BlendMode.SRC_IN if dark else None,
                             fit=ft.ImageFit.CONTAIN, semantics_label="Carmel Hotéis")
        sidebar.content = ft.Column([
            ft.Row([ft.IconButton(
                ft.Icons.CHEVRON_RIGHT if collapsed else ft.Icons.CHEVRON_LEFT,
                tooltip="Expandir menu" if collapsed else "Recolher menu",
                icon_color=colors["text"], on_click=toggle_sidebar,
            )], alignment=ft.MainAxisAlignment.CENTER if collapsed else ft.MainAxisAlignment.END),
            ft.Container(brand, height=56 if collapsed else 90,
                         alignment=ft.alignment.center, tooltip="Carmel Hotéis • Início",
                         on_click=lambda _: page.go("/")),
            ft.Container(height=8, visible=not collapsed),
            ft.Divider(height=16, color=colors["border"], visible=not collapsed),
            ft.Text("PORTAL DE AUTOMAÇÕES", size=11, color=colors["muted"], weight=ft.FontWeight.W_600, visible=not collapsed),
            item("Início", ft.Icons.HOME_OUTLINED, "/"),
            item("Borderô", ft.Icons.FACT_CHECK_OUTLINED, "/bordero"),
            item("Inventário", ft.Icons.INVENTORY_2_OUTLINED, "/inventario"),
            item("Cartões de crédito", ft.Icons.CREDIT_CARD_OUTLINED, "/cartoes"),
            item("Cartão Flash", ft.Icons.BOLT_OUTLINED, "/flash"),
            ft.Container(expand=True),
            ft.Text("FINANCEIRO CARMEL", size=10, color=colors["muted"], visible=not collapsed),
            ft.IconButton(
                ft.Icons.LIGHT_MODE_OUTLINED if dark else ft.Icons.DARK_MODE_OUTLINED,
                tooltip="Modo claro" if dark else "Modo escuro", icon_color=colors["warning"] if dark else colors["info"],
                on_click=bordero.toggle_theme,
            ) if collapsed else ft.TextButton("Modo claro" if dark else "Modo escuro",
                icon=ft.Icons.LIGHT_MODE_OUTLINED if dark else ft.Icons.DARK_MODE_OUTLINED,
                icon_color=colors["warning"] if dark else colors["info"], on_click=bordero.toggle_theme),
        ], expand=True, spacing=10)

    def toggle_sidebar(_):
        nonlocal collapsed
        collapsed = not collapsed
        navigation()
        inventory.resize()
        financial_inventory.resize()
        page.update()

    def theme_changed(is_dark):
        nonlocal dark
        dark = is_dark
        inventory.apply_theme(is_dark)
        financial_inventory.apply_theme(is_dark)
        action_plan.apply_theme(is_dark)
        cards.apply_theme(is_dark)
        flash_panel.apply_theme(is_dark)
        navigation()
        if page.route == "/":
            body.content = home()

    # Build once per browser session, without querying the database.
    # Reusing the controls preserves classifications when navigating to the home screen.
    bordero = build_bordero(page, web_download, attachment_download,
                           embedded=True, on_theme_change=theme_changed)
    inventory = build_inventory(page, download_file=attachment_download,
                                 available_width=lambda: page.width - sidebar.width - 90
                                 if isinstance(page.width, (int, float)) else None)
    financial_inventory = build_financial_inventory(page, download_file=attachment_download,
        available_width=lambda: page.width - sidebar.width - 90 if isinstance(page.width, (int, float)) else None)
    action_plan = build_action_plan(page, download_file=attachment_download)
    cards = build_cards(page, download_file=attachment_download, upload_dir=card_upload_dir)
    flash_panel = build_flash(page, download_file=attachment_download, upload_dir=card_upload_dir)

    panels = {
        "/bordero": bordero.control,
        "/inventario": inventory.control,
        "/inventario/financeiro": financial_inventory.control,
        "/inventario/plano-acao": action_plan.control,
        "/cartoes": cards.control,
        "/flash": flash_panel.control,
    }
    page.title = "Carmel • Portal de automações"

    def route_changed(_):
        if page.route not in ("/", *panels):
            page.go("/")
            return
        body.content = panels[page.route] if page.route in panels else home()
        navigation()
        page.update()

    page.on_route_change = route_changed

    def resized(_):
        if page.route == "/":
            body.content = home()
            page.update()
            return
        inventory_changed = inventory.resize()
        financial_changed = financial_inventory.resize()
        if inventory_changed or financial_changed:
            page.update()

    page.on_resized = resized
    page.add(ft.Row([sidebar, body], expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    if page.route not in ("/", *panels):
        page.go("/")
    else:
        route_changed(None)
