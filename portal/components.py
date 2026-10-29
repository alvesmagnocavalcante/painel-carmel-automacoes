"""Reusable UI components for the Carmel portal navigation and modules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import flet as ft

from portal.theme import get_palette, style_input


def module_card(
    name: str,
    title: str,
    description: str,
    icon: str,
    route: str,
    button: str,
    semantic: str,
    colors: dict[str, str],
    on_navigate: Callable[[str], None],
) -> ft.Container:
    """Standard dashboard card for an automation module."""
    return ft.Container(
        col={"xs": 12, "md": 6, "xl": 4},
        padding=20,
        border_radius=16,
        bgcolor=colors["surface"],
        border=ft.border.all(1, colors["border"]),
        content=ft.Column([
            ft.Container(
                ft.Icon(icon, color=colors[semantic], size=22),
                padding=10,
                bgcolor=colors[f"{semantic}_soft"],
                border_radius=12,
            ),
            ft.Text(name, size=20, weight=ft.FontWeight.W_600, color=colors["text"]),
            ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=colors["text"],
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=title),
            ft.Text(description, size=12, color=colors["muted"], max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=description),
            ft.Divider(height=10, color=colors["border"]),
            ft.ElevatedButton(
                button,
                icon=ft.Icons.ARROW_FORWARD,
                bgcolor=colors["brand_soft"],
                color=colors["on_brand"],
                height=40,
                style=ft.ButtonStyle(elevation=0, shape=ft.RoundedRectangleBorder(radius=10)),
                on_click=lambda _: on_navigate(route),
            ),
        ], spacing=8, tight=True),
    )


def nav_item(
    label: str,
    icon: str,
    route: str,
    current_route: str,
    collapsed: bool,
    colors: dict[str, str],
    on_navigate: Callable[[str], None],
) -> ft.Container:
    """Standard sidebar navigation item."""
    active = current_route == route or (route == "/inventario" and current_route.startswith("/inventario/"))
    return ft.Container(
        ft.Row([
            ft.Icon(icon, color=colors["accent"] if active else colors["info"], size=20),
            ft.Text(label, color=colors["text"], weight=ft.FontWeight.W_600, visible=not collapsed),
        ], spacing=12, alignment=ft.MainAxisAlignment.CENTER if collapsed else ft.MainAxisAlignment.START),
        padding=14,
        border_radius=12,
        tooltip=label,
        bgcolor=colors["nav_active"] if active else None,
        border=ft.border.all(1, colors["border"] if active else ft.Colors.TRANSPARENT),
        on_click=lambda _: on_navigate(route),
    )


def date_picker_field(
    page: ft.Page,
    label: str,
    initial_date: date,
    icon: str,
    on_change: Callable[[date], None],
    *,
    first_date: date = date(2020, 1, 1),
    last_date: date | None = None,
    expand: bool = True,
    col: dict | None = None,
) -> tuple[ft.TextField, ft.DatePicker]:
    """Create a paired TextField and DatePicker with standard Carmel date formatting."""
    today = date.today()
    max_date = last_date or date(today.year + 1, 12, 31)

    field = ft.TextField(
        label=label,
        value=initial_date.strftime("%d/%m/%Y"),
        read_only=True,
        prefix=ft.Icon(icon),
        expand=expand,
        col=col,
    )

    def handle_change(event: ft.ControlEvent) -> None:
        val = event.control.value
        selected = val.date() if hasattr(val, "date") else val
        field.value = selected.strftime("%d/%m/%Y")
        field.update()
        on_change(selected)

    picker = ft.DatePicker(
        value=initial_date,
        first_date=first_date,
        last_date=max_date,
        on_change=handle_change,
    )

    field.on_click = lambda _: page.open(picker)
    return field, picker
