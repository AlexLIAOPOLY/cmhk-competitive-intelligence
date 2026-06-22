from __future__ import annotations

import hashlib
import json
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

COLOR_PALETTE = [
    "#0077C8",
    "#16A34A",
    "#F59E0B",
    "#DC2626",
    "#7C3AED",
    "#0891B2",
]

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
    text = str(value).strip().replace(",", "")
    text = text.replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _normalize_spec(raw_spec: dict[str, Any]) -> dict[str, Any]:
    x_values = [str(item) for item in raw_spec.get("x", [])]
    series = []
    for item in raw_spec.get("series", []):
        if not isinstance(item, dict):
            continue
        data = [_parse_number(value) for value in item.get("data", [])]
        if not any(value is not None for value in data):
            continue
        series.append(
            {
                "name": str(item.get("name") or f"系列 {len(series) + 1}"),
                "data": data,
                "color": str(item.get("color") or COLOR_PALETTE[len(series) % len(COLOR_PALETTE)]),
            }
        )
    if not x_values or not series:
        raise ValueError("图表必须包含 x 和 series 数据。")
    return {
        "type": str(raw_spec.get("type") or "line").lower(),
        "title": str(raw_spec.get("title") or "趋势图"),
        "unit": str(raw_spec.get("unit") or ""),
        "x": x_values,
        "series": series,
        "notes": [str(item) for item in raw_spec.get("notes", []) if str(item).strip()],
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


def render_chart(raw_spec: dict[str, Any]) -> dict[str, str]:
    spec = _normalize_spec(raw_spec)
    CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    font_path, font_name = _find_cjk_font()
    font_prop = font_manager.FontProperties(fname=font_path) if font_path else None
    plt.rcParams["axes.unicode_minus"] = False

    x_labels = spec["x"]
    label_count = len(x_labels)
    fig_width = min(13.5, max(7.2, 0.38 * label_count + 4.0))
    fig, ax = plt.subplots(figsize=(fig_width, 4.35), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D8E3EE")
    ax.spines["bottom"].set_color("#D8E3EE")
    ax.grid(axis="y", color="#E6EEF6", linewidth=1.0)
    ax.set_axisbelow(True)

    x_pos = list(range(len(x_labels)))
    chart_type = spec["type"]

    if chart_type in {"bar", "grouped_bar"}:
        series_count = len(spec["series"])
        width = min(0.22, 0.72 / max(series_count, 1))
        offsets = [(idx - (series_count - 1) / 2) * width for idx in range(series_count)]
        for idx, item in enumerate(spec["series"]):
            values = [value if value is not None else 0 for value in item["data"]]
            ax.bar(
                [x + offsets[idx] for x in x_pos],
                values,
                width=width * 0.92,
                label=item["name"],
                color=item["color"],
                alpha=0.92,
            )
    else:
        for item in spec["series"]:
            y_values = [value if value is not None else float("nan") for value in item["data"]]
            ax.plot(
                x_pos,
                y_values,
                label=item["name"],
                color=item["color"],
                linewidth=2.0,
                marker="o",
                markersize=4.2,
            )

    ax.set_title(spec["title"], loc="center", fontsize=13.5, fontweight="bold", color="#172033", pad=12, fontproperties=font_prop)
    if spec["unit"]:
        ax.text(
            -0.03,
            1.015,
            spec["unit"],
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=9.5,
            color="#66758A",
            fontproperties=font_prop,
        )
    step = _x_tick_step(len(x_labels))
    tick_positions = x_pos[::step]
    if x_pos and tick_positions[-1] != x_pos[-1]:
        tick_positions.append(x_pos[-1])
    tick_labels = [x_labels[index] for index in tick_positions]
    ax.set_xticks(tick_positions, tick_labels, fontproperties=font_prop)
    rotation = 0 if len(tick_labels) <= 10 else 35
    for tick in ax.get_xticklabels():
        tick.set_rotation(rotation)
        tick.set_ha("right" if rotation else "center")
    ax.yaxis.set_major_formatter(_value_formatter(spec["unit"]))
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(font_prop)
    ax.tick_params(axis="both", colors="#66758A", labelsize=8.8)
    ax.margins(x=0.04)

    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=min(3, max(1, len(spec["series"]))),
        frameon=False,
        prop=font_prop,
        fontsize=8.8,
        handlelength=1.8,
    )
    for text in legend.get_texts():
        text.set_color("#344054")

    bottom = 0.24 if rotation else 0.18
    fig.subplots_adjust(left=0.10, right=0.97, top=0.82, bottom=bottom)

    digest = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    filename = f"chart_{digest}.png"
    path = CHART_OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {
        "filename": filename,
        "path": str(path),
        "url": f"/generated-charts/{filename}",
        "font": font_name,
    }
