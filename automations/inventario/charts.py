"""Adaptive comparisons from the loaded inventory snapshot; no I/O."""

from decimal import Decimal
from math import ceil

import flet as ft

from automations.inventario.data import InventoryCount


def _warehouse_chart(rows: tuple[InventoryCount, ...], colors: dict[str, str]) -> ft.Control:
    totals = {}
    for item in rows:
        counted, different = totals.get(item.warehouse, (0, 0))
        totals[item.warehouse] = counted + item.counted, different + item.different
    warehouses = [(name, counted, different, Decimal(different) / Decimal(counted))
                  for name, (counted, different) in totals.items() if counted]
    warehouses.sort(key=lambda item: (-item[3], item[0]))
    controls = []
    for name, counted, different, fraction in warehouses:
        formatted = f"{fraction * 100:.2f}%".replace(".", ",")
        tooltip = f"{name}\n{formatted} com diferença\n{different} de {counted} contados"
        controls.append(ft.Container(ft.ResponsiveRow([
            ft.Text(name, color=colors["text"], size=13, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=name, col={"xs": 12, "md": 4}),
            ft.Container(ft.ProgressBar(
                value=float(fraction), bar_height=14, border_radius=7,
                color=colors["warning"], bgcolor=colors["warning_soft"],
                tooltip=tooltip, semantics_label=name, semantics_value=float(fraction * 100),
            ), alignment=ft.alignment.center, col={"xs": 8, "md": 4}),
            ft.Text(formatted, color=colors["warning"] if different else colors["text"],
                    size=13, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.RIGHT,
                    col={"xs": 4, "md": 1}),
            ft.Text(f"{different} com diferença de {counted} contados", color=colors["text"], size=12,
                    text_align=ft.TextAlign.RIGHT,
                    tooltip="Itens cuja quantidade física difere da quantidade registrada no sistema.",
                    col={"xs": 12, "md": 3}),
        ], spacing=12, run_spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(vertical=9)))
    return ft.Column(controls, expand=True, spacing=2, scroll=ft.ScrollMode.AUTO,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def company_chart(rows: tuple[InventoryCount, ...], colors: dict[str, str]) -> ft.Control:
    totals = {}
    for item in rows:
        counted, different = totals.get(item.company, (0, 0))
        totals[item.company] = counted + item.counted, different + item.different
    companies = [(name, counted, different, Decimal(different) * 100 / Decimal(counted))
                 for name, (counted, different) in totals.items() if counted]
    companies.sort(key=lambda item: (-item[3], item[0]))
    if not companies:
        return ft.Container(ft.Text("Consulte um período com contagens para visualizar o gráfico.",
                                    color=colors["muted"], text_align=ft.TextAlign.CENTER),
                            alignment=ft.alignment.center, expand=True)
    if len(totals) == 1:
        return _warehouse_chart(rows, colors)
    maximum = min(100, max(10, ceil(float(companies[0][3]) / 10) * 10))
    interval = maximum / 4
    groups, labels, value_labels = [], [], []
    for index, (name, counted, different, percentage) in enumerate(companies):
        formatted = f"{percentage:.2f}%".replace(".", ",")
        value_labels.append(ft.ChartAxisLabel(value=index, label=ft.Column([
            ft.Text(formatted, color=colors["warning"], size=14, weight=ft.FontWeight.W_600,
                    text_align=ft.TextAlign.CENTER),
            ft.Text(f"{different} com diferença\n{counted} contados", color=colors["text"], size=11,
                    text_align=ft.TextAlign.CENTER),
        ], spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)))
        groups.append(ft.BarChartGroup(x=index, bar_rods=[ft.BarChartRod(
            from_y=0, to_y=float(percentage), width=38, color=colors["warning"],
            border_radius=ft.border_radius.only(top_left=7, top_right=7),
            bg_from_y=0, bg_to_y=maximum, bg_color=colors["warning_soft"],
            tooltip=f"{name}\n{formatted} com diferença\n{different} de {counted} contados",
            tooltip_style=ft.TextStyle(color=colors["text"], size=13),
        )]))
        labels.append(ft.ChartAxisLabel(value=index, label=ft.Text(
            name.removeprefix("CARMEL "), color=colors["text"], size=12,
            text_align=ft.TextAlign.CENTER, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
        )))
    axis_labels = [ft.ChartAxisLabel(value=index * interval, label=ft.Text(
        f"{index * interval:g}%".replace(".", ","), color=colors["muted"], size=11,
    )) for index in range(5)]
    chart = ft.BarChart(
        bar_groups=groups, min_y=0, max_y=maximum, height=240, expand=True,
        animate=ft.Animation(350, ft.AnimationCurve.EASE_OUT), interactive=True,
        bottom_axis=ft.ChartAxis(labels=labels, labels_size=40),
        left_axis=ft.ChartAxis(labels=axis_labels, labels_interval=interval, labels_size=44),
        right_axis=ft.ChartAxis(show_labels=False),
        top_axis=ft.ChartAxis(labels=value_labels, labels_size=60),
        horizontal_grid_lines=ft.ChartGridLines(color=colors["border"], width=1, dash_pattern=[4, 4]),
        tooltip_bgcolor=colors["surface"], tooltip_rounded_radius=10,
        tooltip_fit_inside_horizontally=True, tooltip_fit_inside_vertically=True,
    )
    return ft.Row([chart], expand=True)
