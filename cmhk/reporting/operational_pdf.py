from __future__ import annotations

import io
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from fontTools.ttLib import TTCollection, TTFont as FontToolsTTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


HKT = ZoneInfo("Asia/Hong_Kong")
PAGE_SIZE = landscape(A4)
NAVY = colors.HexColor("#071F2D")
NAVY_2 = colors.HexColor("#0C3446")
CYAN = colors.HexColor("#2EA8C2")
MINT = colors.HexColor("#42B99A")
RED = colors.HexColor("#D86457")
AMBER = colors.HexColor("#D59B42")
INK = colors.HexColor("#17313D")
MUTED = colors.HexColor("#607985")
LINE = colors.HexColor("#DCE6EA")
PALE = colors.HexColor("#F4F8F9")

PERIOD_LABELS = {"daily": "日报", "weekly": "周报", "monthly": "月报", "annual": "年报"}
REPORT_LABELS = {"alert": "故障报警运营报告", "log": "系统任务日志报告"}

FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/Library/Fonts/NotoSansCJK-Regular.ttc"),
)
_FONT_NAME = "CMHK-Operations-CJK"
_FONT_PATH: Path | None = None
_FONT_CMAP: set[int] | None = None


def _font_path() -> Path:
    global _FONT_PATH
    if _FONT_PATH and _FONT_PATH.exists():
        return _FONT_PATH
    _FONT_PATH = next((item for item in FONT_CANDIDATES if item.exists()), None)
    if not _FONT_PATH:
        raise RuntimeError("未找到可嵌入的中文字体；请安装 fonts-noto-cjk")
    return _FONT_PATH


def _register_font() -> str:
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_font_path()), subfontIndex=0))
        pdfmetrics.registerFontFamily(_FONT_NAME, normal=_FONT_NAME, bold=_FONT_NAME, italic=_FONT_NAME, boldItalic=_FONT_NAME)
    return _FONT_NAME


def _font_cmap() -> set[int]:
    global _FONT_CMAP
    if _FONT_CMAP is not None:
        return _FONT_CMAP
    path = _font_path()
    if path.suffix.lower() == ".ttc":
        collection = TTCollection(str(path), lazy=True)
        font = collection.fonts[0]
    else:
        font = FontToolsTTFont(str(path), lazy=True)
    _FONT_CMAP = {codepoint for table in font["cmap"].tables for codepoint in table.cmap}
    return _FONT_CMAP


def renderable_text(value: object, limit: int = 900) -> str:
    """Return compact report text whose every output character exists in the embedded font."""
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(value or ""))
    raw = re.sub(r"\s+", " ", raw).strip()
    cmap = _font_cmap()
    cleaned = "".join(char if ord(char) in cmap else "?" for char in raw)
    return cleaned[:limit] or "-"


def _parse_hkt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    return parsed.replace(tzinfo=HKT) if parsed.tzinfo is None else parsed.astimezone(HKT)


def report_window(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    if period not in PERIOD_LABELS:
        raise ValueError("报告周期只支持 daily、weekly、monthly、annual")
    end = (now or datetime.now(HKT)).astimezone(HKT)
    if period == "daily":
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = (end - timedelta(days=end.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "monthly":
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = end.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, end


def _record_time(record: dict, report_type: str) -> datetime | None:
    keys = ("occurred_at_hkt", "started_at_hkt", "completed_at_hkt") if report_type == "alert" else ("started_at_hkt", "completed_at_hkt", "heartbeat_at_hkt")
    return next((parsed for key in keys if (parsed := _parse_hkt(record.get(key)))), None)


def _status(record: dict, report_type: str) -> str:
    if report_type == "alert":
        if record.get("handler_name"):
            return "人工修复"
        return "待处理" if record.get("incident_status") == "open" else "自动恢复"
    value = str(record.get("run_status") or "").lower()
    return {"completed": "完成", "failed": "失败", "running": "运行中", "cutoff": "截止", "interrupted": "中断"}.get(value, value or "未知")


def _duration_seconds(record: dict) -> float:
    try:
        milliseconds = float(record.get("duration_ms") or 0)
    except (TypeError, ValueError):
        milliseconds = 0
    return max(0.0, milliseconds / 1000)


def _percent(numerator: int | float, denominator: int | float) -> str:
    return f"{(100 * numerator / denominator):.1f}%" if denominator else "0.0%"


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]


def _display_stamp(value: object) -> str:
    parsed = _parse_hkt(value)
    return parsed.strftime("%m-%d %H:%M") if parsed else "-"


def build_report_model(report_type: str, period: str, records: list[dict], now: datetime | None = None) -> dict:
    if report_type not in REPORT_LABELS:
        raise ValueError("报告类型只支持 alert 或 log")
    start, end = report_window(period, now)
    selected = [record for record in records if (stamp := _record_time(record, report_type)) and start <= stamp <= end]
    selected.sort(key=lambda item: _record_time(item, report_type) or start, reverse=True)
    statuses = Counter(_status(item, report_type) for item in selected)
    types = Counter(renderable_text(item.get("kind_label") or item.get("kind") or item.get("scope"), 60) for item in selected)
    days = Counter((_record_time(item, report_type) or start).strftime("%m-%d") for item in selected)
    model = {
        "report_type": report_type,
        "period": period,
        "title": REPORT_LABELS[report_type],
        "period_label": PERIOD_LABELS[period],
        "start": start,
        "end": end,
        "records": selected,
        "statuses": statuses,
        "types": types,
        "days": days,
        "total": len(selected),
    }
    if report_type == "alert":
        open_count = statuses["待处理"]
        recovered = statuses["自动恢复"] + statuses["人工修复"]
        severities = Counter(str(item.get("severity") or "未分级").upper() for item in selected)
        model.update({
            "severities": severities,
            "kpis": [
                ("报警总数", str(len(selected)), "本周期登记"),
                ("待处理", str(open_count), "需人工关注"),
                ("已恢复", str(recovered), "自动或人工"),
                ("恢复率", _percent(recovered, len(selected)), "已恢复/总数"),
                ("P1/P2", str(severities["P1"] + severities["P2"]), "高优先级"),
                ("人工修复", str(statuses["人工修复"]), "身份已审计"),
            ],
        })
    else:
        success = statuses["完成"]
        durations = [_duration_seconds(item) for item in selected if _duration_seconds(item) > 0]
        model.update({
            "durations": durations,
            "kpis": [
                ("任务总数", str(len(selected)), "本周期启动"),
                ("完成", str(success), "正常完成"),
                ("失败/中断", str(statuses["失败"] + statuses["中断"]), "需复核"),
                ("成功率", _percent(success, len(selected)), "完成/总数"),
                ("平均耗时", f"{mean(durations):.1f}s" if durations else "0.0s", "已记录任务"),
                ("P95耗时", f"{_p95(durations):.1f}s", "第95百分位"),
            ],
        })
    return model


class DistributionChart(Flowable):
    def __init__(self, title: str, values: Counter, width: float, height: float = 58 * mm):
        super().__init__()
        self.title = title
        self.values = values
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        c.setFillColor(PALE)
        c.roundRect(0, 0, self.width, self.height, 3 * mm, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont(_FONT_NAME, 10)
        c.drawString(5 * mm, self.height - 9 * mm, renderable_text(self.title, 50))
        items = self.values.most_common(7)
        if not items:
            c.setFillColor(MUTED)
            c.setFont(_FONT_NAME, 8)
            c.drawString(5 * mm, self.height - 22 * mm, "本周期暂无记录")
            return
        maximum = max(value for _, value in items) or 1
        bar_width = self.width - 48 * mm
        y = self.height - 18 * mm
        for index, (label, value) in enumerate(items):
            c.setFillColor(MUTED)
            c.setFont(_FONT_NAME, 7.4)
            c.drawString(5 * mm, y, renderable_text(label, 16))
            c.setFillColor(colors.HexColor("#D9E9ED"))
            c.roundRect(34 * mm, y - 1.2 * mm, bar_width, 3.2 * mm, 1.6 * mm, fill=1, stroke=0)
            c.setFillColor((CYAN, MINT, AMBER, RED)[index % 4])
            c.roundRect(34 * mm, y - 1.2 * mm, max(1.5 * mm, bar_width * value / maximum), 3.2 * mm, 1.6 * mm, fill=1, stroke=0)
            c.setFillColor(INK)
            c.setFont(_FONT_NAME, 7.4)
            c.drawRightString(self.width - 5 * mm, y, str(value))
            y -= 6.4 * mm


class OperationsDocTemplate(BaseDocTemplate):
    def __init__(self, stream: io.BytesIO, title: str, period_text: str):
        super().__init__(stream, pagesize=PAGE_SIZE, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=19 * mm, bottomMargin=15 * mm, title=title, author="CMHK Competitive Intelligence", subject=period_text)
        self.report_title = title
        self.period_text = period_text
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="operations", frames=[frame], onPage=self._header_footer))

    def _header_footer(self, c: canvas.Canvas, doc):
        c.saveState()
        width, height = PAGE_SIZE
        c.setFillColor(NAVY)
        c.rect(0, height - 12 * mm, width, 12 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(_FONT_NAME, 7.5)
        c.drawString(14 * mm, height - 7.4 * mm, "CMHK 竞争情报 · 运营治理中心")
        c.setFillColor(colors.HexColor("#91C9D5"))
        c.drawRightString(width - 14 * mm, height - 7.4 * mm, renderable_text(self.period_text, 80))
        c.setStrokeColor(LINE)
        c.line(14 * mm, 10 * mm, width - 14 * mm, 10 * mm)
        c.setFillColor(MUTED)
        c.setFont(_FONT_NAME, 7)
        c.drawString(14 * mm, 6 * mm, "内部运营资料 · 数据截至生成时刻")
        c.drawRightString(width - 14 * mm, 6 * mm, f"第 {doc.page} 页")
        c.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    font = _register_font()
    return {
        "title": ParagraphStyle("title", fontName=font, fontSize=25, leading=32, textColor=colors.white, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", fontName=font, fontSize=10, leading=16, textColor=colors.HexColor("#A9CED6")),
        "h1": ParagraphStyle("h1", fontName=font, fontSize=14, leading=20, textColor=INK, spaceBefore=4 * mm, spaceAfter=3 * mm),
        "h2": ParagraphStyle("h2", fontName=font, fontSize=10, leading=15, textColor=INK, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", fontName=font, fontSize=8, leading=12, textColor=INK),
        "small": ParagraphStyle("small", fontName=font, fontSize=6.7, leading=9.2, textColor=MUTED),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=6.4, leading=8.7, textColor=INK),
        "cell_white": ParagraphStyle("cell_white", fontName=font, fontSize=6.5, leading=9, textColor=colors.white, alignment=TA_CENTER),
        "right": ParagraphStyle("right", fontName=font, fontSize=7, leading=10, textColor=MUTED, alignment=TA_RIGHT),
    }


def _p(style: ParagraphStyle, value: object, limit: int = 900) -> Paragraph:
    text = renderable_text(value, limit).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(text, style)


def _cover(model: dict, styles: dict[str, ParagraphStyle]) -> list:
    start, end = model["start"], model["end"]
    title_block = Table([
        [_p(styles["subtitle"], "OPERATIONAL GOVERNANCE REPORT")],
        [_p(styles["title"], f'{model["title"]} · {model["period_label"]}')],
        [_p(styles["subtitle"], f'{start:%Y年%m月%d日 %H:%M} - {end:%Y年%m月%d日 %H:%M}（香港时间）')],
    ], colWidths=[PAGE_SIZE[0] - 28 * mm], rowHeights=[11 * mm, 24 * mm, 10 * mm])
    title_block.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 9 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 9 * mm), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    kpi_cells = []
    for label, value, note in model["kpis"]:
        kpi_cells.append(Table([[_p(styles["small"], label)], [_p(ParagraphStyle("kpi", parent=styles["body"], fontSize=19, leading=23, textColor=INK), value)], [_p(styles["small"], note)]], colWidths=[(PAGE_SIZE[0] - 33 * mm) / 6], rowHeights=[7 * mm, 11 * mm, 7 * mm]))
    kpis = Table([kpi_cells], colWidths=[(PAGE_SIZE[0] - 33 * mm) / 6] * 6, hAlign="LEFT")
    kpis.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), .5, LINE), ("INNERGRID", (0, 0), (-1, -1), .5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm)]))
    return [title_block, Spacer(1, 8 * mm), _p(styles["h1"], "管理摘要"), kpis, Spacer(1, 6 * mm)]


def _summary_charts(model: dict, styles: dict[str, ParagraphStyle]) -> list:
    left = model["statuses"]
    right = model.get("severities") if model["report_type"] == "alert" else model["types"]
    right_title = "紧急程度分布" if model["report_type"] == "alert" else "任务类型分布"
    chart_width = (PAGE_SIZE[0] - 34 * mm) / 2
    charts = Table([[DistributionChart("状态分布", left, chart_width), DistributionChart(right_title, right, chart_width)]], colWidths=[chart_width, chart_width], hAlign="LEFT")
    charts.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm)]))
    return [_p(styles["h1"], "统计分析"), charts, Spacer(1, 5 * mm)]


def _detail_table(model: dict, styles: dict[str, ParagraphStyle]) -> Table:
    alert = model["report_type"] == "alert"
    if alert:
        headers = ["发生时间", "级别", "状态", "报警任务", "组件/范围", "原因摘要", "修复人员", "恢复时间"]
        widths = [28, 13, 18, 37, 31, 76, 23, 28]
        rows = []
        for record in model["records"]:
            when = _record_time(record, "alert")
            cause = record.get("error") or record.get("summary") or "未记录具体原因"
            recovery = _display_stamp(record.get("manual_repaired_at_hkt") or record.get("auto_repaired_at_hkt"))
            rows.append([when.strftime("%m-%d %H:%M") if when else "-", record.get("severity") or "-", _status(record, "alert"), record.get("title") or record.get("kind_label"), record.get("scope") or record.get("kind"), cause, record.get("handler_name") or ("监控机器人" if record.get("incident_status") == "resolved" else "待认领"), recovery])
    else:
        headers = ["开始时间", "状态", "任务类型", "任务名称", "范围/阶段", "耗时", "日志行数", "结果摘要"]
        widths = [29, 17, 31, 43, 42, 18, 18, 56]
        rows = []
        for record in model["records"]:
            when = _record_time(record, "log")
            summary = record.get("status_detail") or record.get("progress_detail") or record.get("error") or "未记录结果摘要"
            rows.append([when.strftime("%m-%d %H:%M") if when else "-", _status(record, "log"), record.get("kind_label") or record.get("kind"), record.get("title") or record.get("task_id"), f'{record.get("scope") or "-"} / {record.get("phase") or "-"}', f'{_duration_seconds(record):.1f}s', str(record.get("lines") or 0), summary])
    table_data = [[_p(styles["cell_white"], value, 40) for value in headers]]
    if rows:
        table_data.extend([[_p(styles["cell"], value, 160) for value in row] for row in rows])
    else:
        table_data.append([_p(styles["body"], "本周期暂无符合条件的记录。"), "", "", "", "", "", "", ""])
    table = Table(table_data, colWidths=[value * mm for value in widths], repeatRows=1, hAlign="LEFT")
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY_2), ("GRID", (0, 0), (-1, -1), .35, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm)]
    for index in range(1, len(table_data)):
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), PALE))
    if not rows:
        style.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(style))
    return table


def generate_operational_report_pdf(report_type: str, period: str, records: list[dict], now: datetime | None = None) -> tuple[bytes, dict]:
    _register_font()
    model = build_report_model(report_type, period, records, now=now)
    styles = _styles()
    stream = io.BytesIO()
    period_text = f'{model["period_label"]} · {model["start"]:%Y-%m-%d} 至 {model["end"]:%Y-%m-%d}'
    doc = OperationsDocTemplate(stream, f'{model["title"]} - {model["period_label"]}', period_text)
    story = _cover(model, styles) + _summary_charts(model, styles)
    story.extend([CondPageBreak(70 * mm), _p(styles["h1"], "明细记录"), _p(styles["small"], f'共 {model["total"]} 条；按发生/启动时间倒序排列。'), Spacer(1, 3 * mm), _detail_table(model, styles)])
    story.extend([Spacer(1, 6 * mm), KeepTogether([_p(styles["h2"], "口径说明"), _p(styles["small"], "统计窗口采用香港时间的自然日、自然周（周一开始）、自然月或自然年；报警恢复率为已自动恢复或已登记人工修复的报警数占报警总数。日志成功率为正常完成任务数占任务总数。空值以 - 表示，不以推测值补齐。")])])
    doc.build(story)
    return stream.getvalue(), model


def report_filename(report_type: str, period: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(HKT)).astimezone(HKT).strftime("%Y%m%d-%H%M")
    prefix = "alert-operations" if report_type == "alert" else "task-log-operations"
    return f"CMHK-{prefix}-{period}-{stamp}.pdf"
