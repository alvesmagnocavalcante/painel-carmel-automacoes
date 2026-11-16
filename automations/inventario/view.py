"""Shared inventory view contract and navigation; no data loading."""

from dataclasses import dataclass
from typing import Callable

import flet as ft

from portal.theme import panel_text

TABLE_HEIGHT = 420  # smallest scroll window used when the screen is short
EMPTY_HEIGHT = 150  # compact placeholder; never reserve a full table's height for nothing


def table_height(page, rows: int, row_height: int = 60, header: int = 56) -> int:
    """Fit a table to its rows and to the screen.

    Sized from the loaded data, not from the active filter, so the page does not
    jump when a filter changes. Scrolls inside the table only when it is taller
    than the screen allows.
    """
    available = page.height if isinstance(page.height, (int, float)) and page.height else 900
    ceiling = max(TABLE_HEIGHT, int(available) - 300)
    return max(EMPTY_HEIGHT, min(ceiling, header + rows * row_height + 16))


def empty_state(content: ft.Control) -> ft.Container:
    return ft.Container(content, height=EMPTY_HEIGHT, alignment=ft.alignment.center, padding=ft.padding.all(16))


@dataclass(frozen=True)
class InventoryView:
    control: ft.Column
    apply_theme: Callable[[bool], None]
    resize: Callable[[], bool]


def inventory_navigation(page, colors, *, financial=False, action_plan=False):
    buttons = []
    for label, icon, route, active in (
        ("Contagem de itens", ft.Icons.INVENTORY_2_OUTLINED, "/inventario", not financial and not action_plan),
        ("Impacto financeiro", ft.Icons.ACCOUNT_BALANCE_OUTLINED, "/inventario/financeiro", financial),
        ("Plano de ação", ft.Icons.CHECKLIST_OUTLINED, "/inventario/plano-acao", action_plan),
    ):
        buttons.append(ft.TextButton(
            label, icon=icon, height=42,
            icon_color=colors["info"] if active else colors["muted"],
            style=ft.ButtonStyle(
                color=colors["text"] if active else colors["muted"],
                bgcolor=colors["soft"] if active else ft.Colors.TRANSPARENT,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                text_style=ft.TextStyle(weight=ft.FontWeight.W_600),
            ),
            on_click=lambda _, destination=route: page.go(destination),
        ))
    return ft.Container(ft.Row(buttons, spacing=8, run_spacing=8, wrap=True,
                              alignment=ft.MainAxisAlignment.START),
                        padding=ft.padding.only(top=10))


def inventory_header(
    page,
    colors,
    title: str,
    subtitle: str,
    category: str = "INVENTÁRIO • ALMOXARIFADO",
    *,
    financial: bool = False,
    action_plan: bool = False,
) -> ft.Container:
    return ft.Container(
        ft.Column([
            ft.Text(category, size=11, weight=ft.FontWeight.W_600, color=colors["accent"]),
            ft.Text(title, size=24, weight=ft.FontWeight.W_600, color=colors["text"]),
            ft.Text(subtitle, size=13, color=colors["muted"]),
            inventory_navigation(page, colors, financial=financial, action_plan=action_plan),
        ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=ft.padding.symmetric(horizontal=24, vertical=16),
        bgcolor=colors["surface"],
        border=ft.border.only(bottom=ft.BorderSide(1, colors["border"])),
    )
