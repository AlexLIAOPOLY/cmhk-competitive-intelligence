from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parent
CHART_OUTPUT_DIR = ROOT / "agent_knowledge" / "generated_charts"
CHART_RENDERER_VERSION = "2026-08-03-complete-inside-bar-labels-v4"

COLOR_PALETTE = [
    "#0077C8",
    "#16A34A",
    "#F59E0B",
    "#DC2626",
    "#7C3AED",
    "#0891B2",
    "#DB2777",
    "#64748B",
]

SUPPORTED_CHART_TYPES = {
    "line",
    "bar",
    "grouped_bar",
    "horizontal_bar",
    "stacked_bar",
    "area",
    "stacked_area",
    "pie",
    "donut",
    "scatter",
    "bubble",
    "radar",
    "heatmap",
    "histogram",
    "box",
    "combo",
}

CHART_TYPE_ALIASES = {
    "column": "bar",
    "grouped_column": "grouped_bar",
    "barh": "horizontal_bar",
    "horizontal": "horizontal_bar",
    "stacked_column": "stacked_bar",
    "stacked": "stacked_bar",
    "stackedarea": "stacked_area",
    "doughnut": "donut",
    "scatter_plot": "scatter",
    "bubble_chart": "bubble",
    "radar_chart": "radar",
    "heat_map": "heatmap",
    "hist": "histogram",
    "boxplot": "box",
    "mixed": "combo",
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def generated_chart_path(name: str) -> Path | None:
    clean = Path(str(name or "")).name
    if not re.fullmatch(r"chart_[a-f0-9]{16}\.png", clean):
        return None
    target = (CHART_OUTPUT_DIR / clean).resolve()
    if CHART_OUTPUT_DIR.resolve() not in target.parents:
        return None
    return target


def _find_cjk_font() -> tuple[str | None, str]:
    for path in FONT_CANDIDATES:
        candidate = Path(path)
        if candidate.exists():
            try:
                prop = font_manager.FontProperties(fname=str(candidate))
                return str(candidate), prop.get_name()
            except Exception:
                return str(candidate), candidate.stem
    for name in ("Songti SC", "Heiti TC", "STHeiti", "Arial Unicode MS", "Noto Sans CJK SC"):
        try:
            path = font_manager.findfont(name, fallback_to_default=False)
            if path and Path(path).exists():
                return path, name
        except Exception:
            continue
    return None, "Matplotlib default"


def _parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _normalize_spec(raw_spec: dict[str, Any]) -> dict[str, Any]:
    chart_type = str(raw_spec.get("type") or "line").strip().lower().replace("-", "_")
    chart_type = CHART_TYPE_ALIASES.get(chart_type, chart_type)
    if chart_type not in SUPPORTED_CHART_TYPES:
        choices = ", ".join(sorted(SUPPORTED_CHART_TYPES))
        raise ValueError(f"不支持的图表类型 {chart_type!r}；可选类型：{choices}。")

    x_values = [str(item) for item in raw_spec.get("x", [])]
    series = []
    for item in raw_spec.get("series", []):
        if not isinstance(item, dict):
            continue
        data = [_parse_number(value) for value in item.get("data", item.get("values", []))]
        if not any(value is not None for value in data):
            continue
        series.append(
            {
                "name": str(item.get("name") or f"系列 {len(series) + 1}"),
                "data": data,
                "sizes": [_parse_number(value) for value in item.get("sizes", [])],
                "color": str(item.get("color") or COLOR_PALETTE[len(series) % len(COLOR_PALETTE)]),
            }
        )
    if not series:
        raise ValueError("图表必须包含 series.data 数据。")
    if chart_type not in {"histogram", "box"} and not x_values:
        raise ValueError(f"{chart_type} 图必须包含 x 分类或时间标签。")
    if chart_type in {"pie", "donut"}:
        if len(series) != 1:
            raise ValueError("饼图和环形图每张只接受一个系列；多个口径请分别生成多张图。")
        values = series[0]["data"][: len(x_values)]
        if any(value is not None and value < 0 for value in values):
            raise ValueError("饼图和环形图不能包含负数。")
        if sum(value is not None and value > 0 for value in values) < 2:
            raise ValueError("饼图和环形图至少需要两个正值分类。")
    if chart_type == "heatmap" and len(series) < 2:
        raise ValueError("热力图至少需要两个系列作为矩阵行。")
    return {
        "type": chart_type,
        "title": str(raw_spec.get("title") or "数据图表"),
        "unit": str(raw_spec.get("unit") or ""),
        "x": x_values,
        "series": series,
        "bins": max(3, min(30, int(_parse_number(raw_spec.get("bins")) or 10))),
    }


def _value_formatter(unit: str):
    if unit.strip() == "%":
        return FuncFormatter(lambda value, _pos: f"{value:.0f}%")
    return FuncFormatter(lambda value, _pos: f"{value:,.0f}")


def _x_tick_step(label_count: int) -> int:
    if label_count <= 10:
        return 1
    if label_count <= 20:
        return 2
    if label_count <= 32:
        return 3
    return max(4, round(label_count / 10))


def _category_values(item: dict[str, Any], count: int, missing: float = 0.0) -> list[float]:
    values = list(item["data"][:count])
    values.extend([None] * (count - len(values)))
    return [missing if value is None else float(value) for value in values]


def _format_value_label(value: float, *, compact: bool = False) -> str:
    if compact:
        absolute = abs(value)
        if absolute >= 1_000_000:
            return f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
        if absolute >= 10_000:
            return f"{value / 1_000:.0f}k"
        if absolute >= 1_000:
            return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _label_bars(
    ax,
    container,
    values: list[float],
    font_prop,
    *,
    center: bool = False,
    compact: bool = False,
    rotation: float = 0,
):
    labels = [
        _format_value_label(value, compact=compact)
        if value != 0
        else ""
        for value in values
    ]
    return ax.bar_label(
        container,
        labels=labels,
        label_type="center" if center else "edge",
        padding=0 if center else 4,
        fontsize=7.6 if compact else 8.2,
        color="white" if center else "#344054",
        fontweight="bold" if center else "normal",
        fontproperties=font_prop,
        rotation=rotation,
    )


def _style_cartesian_axis(ax, unit: str, font_prop) -> None:
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D8E3EE")
    ax.spines["bottom"].set_color("#D8E3EE")
    ax.grid(axis="y", color="#E6EEF6", linewidth=1.0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(_value_formatter(unit))
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(font_prop)
    ax.tick_params(axis="both", colors="#66758A", labelsize=8.8)


def _set_category_ticks(ax, x_labels: list[str], font_prop) -> int:
    x_pos = list(range(len(x_labels)))
    step = _x_tick_step(len(x_labels))
    tick_positions = x_pos[::step]
    if x_pos and tick_positions[-1] != x_pos[-1]:
        tick_positions.append(x_pos[-1])
    labels = [x_labels[index] for index in tick_positions]
    ax.set_xticks(tick_positions, labels, fontproperties=font_prop)
    rotation = 0 if len(labels) <= 10 else 35
    for tick in ax.get_xticklabels():
        tick.set_rotation(rotation)
        tick.set_ha("right" if rotation else "center")
    return rotation


def render_chart(raw_spec: dict[str, Any]) -> dict[str, str]:
    spec = _normalize_spec(raw_spec)
    CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    font_path, font_name = _find_cjk_font()
    font_prop = font_manager.FontProperties(fname=font_path) if font_path else None
    plt.rcParams["axes.unicode_minus"] = False
    if font_path:
        try:
            font_manager.fontManager.addfont(font_path)
        except Exception:
            pass
        plt.rcParams["font.family"] = [font_name, "sans-serif"]
        plt.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]

    chart_type = spec["type"]
    x_labels = spec["x"]
    label_count = len(x_labels)
    x_pos = list(range(label_count))
    fig_width = min(13.5, max(7.2, 0.38 * label_count + 4.0))
    subplot_kw = {"projection": "polar"} if chart_type == "radar" else {}
    fig, ax = plt.subplots(figsize=(fig_width, 4.6), dpi=160, subplot_kw=subplot_kw)
    fig.patch.set_facecolor("white")
    cartesian = chart_type not in {"pie", "donut", "radar", "heatmap"}
    if cartesian:
        _style_cartesian_axis(ax, spec["unit"], font_prop)

    if chart_type in {"bar", "grouped_bar"}:
        count = len(spec["series"])
        dense_labels = label_count * count > 12
        width = min(0.22, 0.72 / max(count, 1))
        offsets = [(index - (count - 1) / 2) * width for index in range(count)]
        for index, item in enumerate(spec["series"]):
            values = _category_values(item, label_count)
            bars = ax.bar([x + offsets[index] for x in x_pos], values, width=width * 0.92, label=item["name"], color=item["color"], alpha=0.92)
            _label_bars(
                ax,
                bars,
                values,
                font_prop,
                center=dense_labels,
                compact=dense_labels,
                rotation=90 if dense_labels else 0,
            )
        ax.margins(y=0.12)
    elif chart_type == "horizontal_bar":
        count = len(spec["series"])
        dense_labels = label_count * count > 12
        height = min(0.24, 0.72 / max(count, 1))
        offsets = [(index - (count - 1) / 2) * height for index in range(count)]
        for index, item in enumerate(spec["series"]):
            values = _category_values(item, label_count)
            bars = ax.barh([y + offsets[index] for y in x_pos], values, height=height * 0.92, label=item["name"], color=item["color"], alpha=0.92)
            _label_bars(
                ax,
                bars,
                values,
                font_prop,
                center=dense_labels,
                compact=dense_labels,
            )
        ax.set_yticks(x_pos, x_labels, fontproperties=font_prop)
        ax.invert_yaxis()
        ax.grid(axis="x", color="#E6EEF6", linewidth=1.0)
        ax.grid(axis="y", visible=False)
        ax.xaxis.set_major_formatter(_value_formatter(spec["unit"]))
        ax.margins(x=0.12)
    elif chart_type == "stacked_bar":
        positive = [0.0] * label_count
        negative = [0.0] * label_count
        for item in spec["series"]:
            values = _category_values(item, label_count)
            bottoms = [positive[i] if value >= 0 else negative[i] for i, value in enumerate(values)]
            bars = ax.bar(x_pos, values, bottom=bottoms, label=item["name"], color=item["color"], alpha=0.92)
            if label_count * len(spec["series"]) <= 24:
                _label_bars(ax, bars, values, font_prop, center=True, compact=label_count * len(spec["series"]) > 12)
            for index, value in enumerate(values):
                if value >= 0:
                    positive[index] += value
                else:
                    negative[index] += value
    elif chart_type in {"area", "stacked_area"}:
        rows = [_category_values(item, label_count) for item in spec["series"]]
        if chart_type == "stacked_area":
            if any(value < 0 for row in rows for value in row):
                raise ValueError("堆叠面积图不能包含负数，请改用折线图或普通面积图。")
            ax.stackplot(x_pos, *rows, labels=[item["name"] for item in spec["series"]], colors=[item["color"] for item in spec["series"]], alpha=0.78)
        else:
            for item, row in zip(spec["series"], rows):
                ax.plot(x_pos, row, label=item["name"], color=item["color"], linewidth=2.0)
                ax.fill_between(x_pos, row, 0, color=item["color"], alpha=0.16)
    elif chart_type in {"pie", "donut"}:
        item = spec["series"][0]
        pairs = [(label, value) for label, value in zip(x_labels, _category_values(item, label_count)) if value > 0]
        labels, values = zip(*pairs)
        _wedges, _texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=[COLOR_PALETTE[index % len(COLOR_PALETTE)] for index in range(len(values))],
            autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "",
            pctdistance=0.78 if chart_type == "donut" else 0.65,
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.42 if chart_type == "donut" else 1.0, "edgecolor": "white", "linewidth": 1.5},
            textprops={"fontproperties": font_prop, "color": "#344054", "fontsize": 8.8},
        )
        for text in autotexts:
            text.set_color("white")
            text.set_fontweight("bold")
            text.set_fontsize(8.2)
        ax.axis("equal")
    elif chart_type in {"scatter", "bubble"}:
        numeric_x = [_parse_number(label) for label in x_labels]
        plot_x = numeric_x if all(value is not None for value in numeric_x) else x_pos
        for item in spec["series"]:
            values = _category_values(item, label_count, float("nan"))
            sizes = item.get("sizes") or []
            if chart_type == "bubble":
                raw_sizes = [sizes[i] if i < len(sizes) and sizes[i] is not None else abs(values[i]) for i in range(label_count)]
                scale_max = max((abs(value) for value in raw_sizes if math.isfinite(value)), default=1.0) or 1.0
                marker_sizes = [40 + 380 * abs(value) / scale_max if math.isfinite(values[i]) else 0 for i, value in enumerate(raw_sizes)]
            else:
                marker_sizes = 54
            ax.scatter(plot_x, values, s=marker_sizes, label=item["name"], color=item["color"], alpha=0.72, edgecolors="white", linewidths=0.7)
        if plot_x == x_pos:
            _set_category_ticks(ax, x_labels, font_prop)
    elif chart_type == "radar":
        if label_count < 3:
            raise ValueError("雷达图至少需要三个维度。")
        angles = [2 * math.pi * index / label_count for index in range(label_count)]
        closed_angles = angles + angles[:1]
        for item in spec["series"]:
            values = _category_values(item, label_count)
            closed_values = values + values[:1]
            ax.plot(closed_angles, closed_values, label=item["name"], color=item["color"], linewidth=2.0)
            ax.fill(closed_angles, closed_values, color=item["color"], alpha=0.12)
        ax.set_xticks(angles, x_labels, fontproperties=font_prop, color="#344054", fontsize=8.8)
        ax.set_rlabel_position(15)
        ax.grid(color="#D8E3EE")
    elif chart_type == "heatmap":
        matrix = [_category_values(item, label_count, float("nan")) for item in spec["series"]]
        image = ax.imshow(matrix, aspect="auto", cmap="Blues")
        ax.set_xticks(x_pos, x_labels, fontproperties=font_prop)
        ax.set_yticks(range(len(spec["series"])), [item["name"] for item in spec["series"]], fontproperties=font_prop)
        finite = [value for row in matrix for value in row if math.isfinite(value)]
        midpoint = (min(finite) + max(finite)) / 2 if finite else 0
        if label_count * len(spec["series"]) <= 80:
            for row_index, row in enumerate(matrix):
                for column_index, value in enumerate(row):
                    if math.isfinite(value):
                        ax.text(column_index, row_index, f"{value:,.0f}", ha="center", va="center", fontsize=7.8, color="white" if value > midpoint else "#172033", fontproperties=font_prop)
        colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.025)
        colorbar.ax.yaxis.set_major_formatter(_value_formatter(spec["unit"]))
    elif chart_type == "histogram":
        for item in spec["series"]:
            values = [float(value) for value in item["data"] if value is not None]
            ax.hist(values, bins=spec["bins"], label=item["name"], color=item["color"], alpha=0.58, edgecolor="white")
        ax.set_ylabel("频数", fontproperties=font_prop, color="#66758A")
    elif chart_type == "box":
        samples = [[float(value) for value in item["data"] if value is not None] for item in spec["series"]]
        labels = [item["name"] for item in spec["series"]]
        boxes = ax.boxplot(samples, tick_labels=labels, patch_artist=True, showmeans=True)
        for index, patch in enumerate(boxes["boxes"]):
            patch.set_facecolor(COLOR_PALETTE[index % len(COLOR_PALETTE)])
            patch.set_alpha(0.52)
        for tick in ax.get_xticklabels():
            tick.set_fontproperties(font_prop)
    elif chart_type == "combo":
        first, *rest = spec["series"]
        first_values = _category_values(first, label_count)
        bars = ax.bar(x_pos, first_values, width=0.58, label=first["name"], color=first["color"], alpha=0.82)
        if label_count <= 20:
            _label_bars(ax, bars, first_values, font_prop, compact=label_count > 12)
        ax.margins(y=0.12)
        for item in rest:
            ax.plot(x_pos, _category_values(item, label_count, float("nan")), label=item["name"], color=item["color"], linewidth=2.2, marker="o", markersize=4.0)
    else:
        for item in spec["series"]:
            ax.plot(x_pos, _category_values(item, label_count, float("nan")), label=item["name"], color=item["color"], linewidth=2.0, marker="o", markersize=4.2)

    ax.set_title(spec["title"], loc="center", fontsize=13.5, fontweight="bold", color="#172033", pad=14, fontproperties=font_prop)
    if spec["unit"] and chart_type not in {"pie", "donut"}:
        ax.text(-0.03, 1.015, spec["unit"], transform=ax.transAxes, ha="center", va="bottom", fontsize=9.5, color="#66758A", fontproperties=font_prop)
    rotation = 0
    if chart_type in {"line", "bar", "grouped_bar", "stacked_bar", "area", "stacked_area", "combo"}:
        rotation = _set_category_ticks(ax, x_labels, font_prop)
    if chart_type not in {"pie", "donut", "heatmap"}:
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            legend = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=min(4, max(1, len(labels))), frameon=False, prop=font_prop, fontsize=8.8, handlelength=1.8)
            for text in legend.get_texts():
                text.set_color("#344054")
    if cartesian and chart_type != "horizontal_bar":
        ax.margins(x=0.04)

    bottom = 0.24 if rotation or chart_type in {"radar", "box"} else 0.18
    if chart_type in {"pie", "donut", "heatmap"}:
        bottom = 0.08
    fig.subplots_adjust(left=0.10, right=0.97, top=0.82, bottom=bottom)

    digest_payload = {"renderer": CHART_RENDERER_VERSION, "spec": spec}
    digest = hashlib.sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    filename = f"chart_{digest}.png"
    path = CHART_OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"filename": filename, "path": str(path), "url": f"/generated-charts/{filename}", "font": font_name}
