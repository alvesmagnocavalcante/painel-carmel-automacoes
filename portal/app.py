"""Web portal navigation; payment conference rules remain in the Bordero module."""

import flet as ft

from automations.bordero.panel import main as build_bordero
from automations.inventario.panel import main as build_inventory
from automations.inventario.financial_panel import main as build_financial_inventory
from automations.inventario.action_panel import main as build_action_plan
from portal.theme import DARK, LIGHT, FONT_DISPLAY


def main(page, web_download, attachment_download=None):
    dark = True
    collapsed = False
    body = ft.Container(expand=True)
    sidebar = ft.Container(width=224, padding=18, animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT))

    def palette():
        return DARK if dark else LIGHT

    def home():
        colors = palette()

        def card(name, title, description, icon, route, button, semantic):
            return ft.Container(col={"xs": 12, "lg": 6}, padding=28, border_radius=22, bgcolor=colors["surface"],
                border=ft.border.all(1, colors["border"]), content=ft.Column([
                    ft.Container(ft.Icon(icon, color=colors[semantic], size=27),
                                 padding=14, bgcolor=colors[f"{semantic}_soft"], border_radius=16),
                    ft.Text(name, size=25, weight=ft.FontWeight.W_600, color=colors["text"]),
                    ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=colors["text"]),
                    ft.Text(description, size=13, color=colors["muted"]),
                    ft.Divider(height=18, color=colors["border"]),
                    ft.ElevatedButton(button, icon=ft.Icons.ARROW_FORWARD,
                        bgcolor=colors["brand_soft"], color=colors["on_brand"], height=46,
                        style=ft.ButtonStyle(elevation=0, shape=ft.RoundedRectangleBorder(radius=12)),
                        on_click=lambda _: page.go(route)),
                ], spacing=14))

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
            ], spacing=20, run_spacing=20),
        ], spacing=10, scroll=ft.ScrollMode.AUTO))

    def navigation():
        colors = palette()

        def item(label, icon, route):
            active = page.route == route or (route == "/inventario" and page.route.startswith("/inventario/"))
            return ft.Container(
                ft.Row([ft.Icon(icon, color=colors["accent"] if active else colors["info"], size=20),
                        ft.Text(label, color=colors["text"], weight=ft.FontWeight.W_600, visible=not collapsed)], spacing=12,
                       alignment=ft.MainAxisAlignment.CENTER if collapsed else ft.MainAxisAlignment.START),
                padding=14, border_radius=12,
                tooltip=label,
                bgcolor=colors["nav_active"] if active else None,
                border=ft.border.all(1, colors["border"] if active else ft.Colors.TRANSPARENT),
                on_click=lambda _: page.go(route),
            )

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
    panels = {"/bordero": bordero.control, "/inventario": inventory.control,
              "/inventario/financeiro": financial_inventory.control,
              "/inventario/plano-acao": action_plan.control}
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
