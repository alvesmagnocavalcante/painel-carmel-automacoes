"""Shared brand palette, typography, and Flet UI builders for the Carmel portal."""

from __future__ import annotations

import flet as ft

PRIMARY = "#4C3427"
FONT_BODY = "Carmel Sans"
FONT_DISPLAY = "Carmel Display"
FONTS = {FONT_BODY: "/fonts/PlusJakartaSans.ttf", FONT_DISPLAY: "/fonts/Cormorant-SemiBold.ttf"}

LIGHT = {
    "background": "#D8D2C8", "surface": "#EFEBE4", "border": "#C4B9AB",
    "text": "#151311", "muted": "#302B26", "soft": "#DBD4CA",
    "table": "#DBD4CA", "accent": "#4C3427", "warning": "#7A4F00",
    "success": "#205E3F", "info": "#2D587E", "money": "#1D5E5B",
    "warning_soft": "#F0DFC1", "success_soft": "#D9E5D9",
    "info_soft": "#DCE4EB", "money_soft": "#D4E4DF",
    "brand_soft": "#E7D0A7", "nav_active": "#E4DACB", "hero": "#E8E7E1",
    "on_brand": "#4C3427",
    "danger": "#A1392F", "danger_soft": "#F4E0DB",
}

DARK = {
    "background": "#1D1D1B", "surface": "#292623", "border": "#4A423B",
    "text": "#E8E7E1", "muted": "#C3B9AC", "soft": "#3B342D",
    "table": "#3B342D", "accent": "#E7D0A7", "warning": "#E4B55E",
    "success": "#83C79B", "info": "#8AB8DC", "money": "#7CC7BB",
    "warning_soft": "#493B25", "success_soft": "#2D4032",
    "info_soft": "#2D3944", "money_soft": "#293F3B",
    "brand_soft": "#E7D0A7", "nav_active": "#463A2E", "hero": "#302A25",
    "on_brand": "#4C3427",
    "danger": "#F39A8A", "danger_soft": "#4B2F2A",
}


def get_palette(is_dark: bool) -> dict[str, str]:
    """Return the active color palette based on theme mode."""
    return DARK if is_dark else LIGHT


def build_theme(seed: str, colors: dict[str, str]) -> ft.Theme:
    medium = ft.TextStyle(color=colors["text"], weight=ft.FontWeight.W_500)
    bold = ft.TextStyle(color=colors["text"], weight=ft.FontWeight.W_600)
    return ft.Theme(
        color_scheme_seed=seed,
        font_family=FONT_BODY,
        text_theme=ft.TextTheme(
            body_large=medium,
            body_medium=medium,
            body_small=ft.TextStyle(color=colors["muted"], weight=ft.FontWeight.W_500),
            label_large=bold,
            label_medium=bold,
            label_small=bold,
        ),
        color_scheme=ft.ColorScheme(
            on_surface=colors["text"],
            on_surface_variant=colors["muted"],
            surface=colors["surface"],
            surface_container=colors["surface"],
            surface_container_high=colors["surface"],
            surface_variant=colors["soft"],
            surface_container_low=colors["surface"],
        ),
    )


def panel_text(
    value: str,
    colors: dict[str, str],
    *,
    muted: bool = False,
    bold: bool = False,
    color: str | None = None,
    size: int | None = None,
    **kwargs,
) -> ft.Text:
    return ft.Text(
        value,
        color=color or colors["muted" if muted else "text"],
        size=size,
        weight=ft.FontWeight.W_600 if bold else ft.FontWeight.W_500,
        **kwargs,
    )


def surface_card(
    content: ft.Control,
    colors: dict[str, str],
    *,
    radius: int = 16,
    padding: int = 20,
    **kwargs,
) -> ft.Container:
    return ft.Container(
        content,
        bgcolor=colors["surface"],
        border=ft.border.all(1, colors["border"]),
        border_radius=radius,
        padding=padding,
        **kwargs,
    )


def style_input(
    control: ft.Control,
    colors: dict[str, str],
    *,
    weight: ft.FontWeight = ft.FontWeight.W_500,
) -> None:
    control.bgcolor = colors["surface"]
    control.color = colors["text"]
    control.text_style = ft.TextStyle(color=colors["text"], weight=weight)
    control.label_style = ft.TextStyle(color=colors["muted"], weight=ft.FontWeight.W_500)
    control.hint_style = ft.TextStyle(color=colors["muted"])
    if isinstance(control, ft.Dropdown):
        control.hover_color = colors["soft"]


def metric_card(
    label: str,
    value: str,
    icon: str,
    semantic: str,
    colors: dict[str, str],
    *,
    col: dict,
    value_size: int = 20,
) -> ft.Container:
    return surface_card(
        ft.Row([
            ft.Container(
                ft.Icon(icon, color=colors[semantic], size=19),
                bgcolor=colors[f"{semantic}_soft"],
                padding=8,
                border_radius=9,
            ),
            ft.Column([
                panel_text(label, colors, muted=True, size=11, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, tooltip=label),
                panel_text(value, colors, bold=True, size=value_size),
            ], spacing=1, tight=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        colors,
        radius=12,
        padding=12,
        col=col,
    )
