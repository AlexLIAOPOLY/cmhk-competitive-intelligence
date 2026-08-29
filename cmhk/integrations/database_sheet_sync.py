"""Bidirectional Feishu mirror for the crawler's governed competitor datasets.

The crawler CSV packages remain the source-of-record.  Feishu exposes a compact
human-readable projection plus two governed fields: ``人工修訂值`` and
``人工備註``.  Numeric overrides never replace ``official_value``; the effective
``value`` is changed with explicit provenance columns and a local audit state.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cmhk.integrations.feishu_runtime import lark_cli_env, resolve_lark_cli


ROOT = Path(__file__).resolve().parents[2]
HKT = ZoneInfo("Asia/Hong_Kong")
SPREADSHEET_TOKEN = os.environ.get(
    "CMHK_DATABASE_SHEET_SPREADSHEET_TOKEN", "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
)
SHEET_TITLE = os.environ.get("CMHK_PRODUCER_DATABASE_SHEET_TITLE", "競對資料庫")
STATE_PATH = ROOT / "var" / "feishu_database_sync" / "producer_state.json"
EDITABLE_HEADERS = ("人工修訂值", "人工備註")
HEADERS = (
    "資料庫",
    "資料集",
    "主體",
    "期間",
    "指標",
    "本地值",
    "單位",
    "資料狀態",
    "資料備註",
    "人工修訂值",
    "人工備註",
    "來源",
    "同步時間",
    "同步鍵",
    "版本／快照",
)
PROVENANCE_FIELDS = (
    "feishu_original_value",
    "feishu_override_value",
    "feishu_override_note",
    "feishu_override_actor",
    "feishu_override_at",
)
SUCCESS_MESSAGE = "已经同步到飞书"


@dataclass(frozen=True)
class SourceSpec:
    dataset_key: str
    dataset_label: str
    path: Path
    natural_fields: tuple[str, ...]
    subject_fields: tuple[str, ...]
    period_fields: tuple[str, ...]
    metric_fields: tuple[str, ...]
    value_field: str
    unit_fields: tuple[str, ...]
    status_fields: tuple[str, ...]
    note_fields: tuple[str, ...]
    source_fields: tuple[str, ...]


def _now() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _text(value: Any, limit: int = 800) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _first(row: dict[str, Any], fields: tuple[str, ...], *, limit: int = 800) -> str:
    for field in fields:
        value = _text(row.get(field), limit)
        if value:
            return value
    return ""


def _sync_key(dataset_key: str, values: list[str]) -> str:
    raw = "\x1f".join([dataset_key, *values])
    return f"{dataset_key[:12]}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _enabled() -> bool:
    return os.environ.get("CMHK_DATABASE_SHEET_SYNC_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _source_specs(dataset_dir: Path) -> tuple[SourceSpec, ...]:
    knowledge = dataset_dir.parent
    return (
        SourceSpec(
            "quarterly_competitor_metrics",
            "季度競對指標",
            dataset_dir / "quarterly_metrics.csv",
            ("subject", "period", "grain", "metric_key"),
            ("subject", "legal_name"),
            ("period", "period_end"),
            ("metric_zh", "metric_key"),
            "value",
            ("unit", "official_unit"),
            ("verification_status", "quality_status"),
            ("verification_note", "quality_note", "official_evidence"),
            ("official_source_url", "official_source_label"),
        ),
        SourceSpec(
            "local_hk_operator_operating_metrics",
            "香港營運商年度指標",
            knowledge / "local_hk_operator_operating_metrics_2016_2025" / "annual_metrics.csv",
            ("operator_id", "year", "metric_key"),
            ("operator", "legal_name", "operator_id"),
            ("period", "year", "period_end"),
            ("metric_zh", "metric_key"),
            "value",
            ("unit",),
            ("verification_status", "audit_outcome"),
            ("quality_note", "gap_reason"),
            ("primary_source_url", "primary_source_id"),
        ),
        SourceSpec(
            "global_operator_operating_metrics",
            "國際營運商年度指標",
            knowledge / "global_top5_operators_2016_2025" / "annual_metrics.csv",
            ("operator_id", "year", "metric_key"),
            ("operator", "legal_name", "operator_id"),
            ("period", "year", "period_end"),
            ("metric_zh", "metric_key"),
            "value",
            ("unit",),
            ("verification_status", "triple_source_status"),
            ("quality_note",),
            ("primary_source_url", "primary_source_id"),
        ),
        SourceSpec(
            "cloud_vendor_metrics",
            "雲廠商年度指標",
            knowledge / "cloud_vendor_metrics_2026-06-17" / "cloud_vendor_metrics_2016_2025.csv",
            ("vendor", "fiscal_year", "metric_key"),
            ("vendor", "legal_name"),
            ("fiscal_year", "fiscal_year_end"),
            ("metric_zh", "metric_key"),
            "value",
            ("official_unit", "unit", "currency"),
            ("verification_status", "disclosure_quality"),
            ("quality_note", "gap_reason", "verification_note"),
            ("primary_source_url", "source_ids"),
        ),
        SourceSpec(
            "competitor_product_tariffs",
            "競對產品資費",
            knowledge / "competitor_product_tariffs" / "product_tariffs_formal_agent_records.csv",
            ("记录键", "品牌", "套餐名称", "期间", "抓取/生效时间", "来源URL"),
            ("品牌", "数据子库"),
            ("期间", "抓取/生效时间"),
            ("套餐名称", "产品类别"),
            "月费_HKD",
            ("计价单位",),
            ("核验状态", "来源状态"),
            ("证据摘录", "usage_policy"),
            ("来源URL", "来源ID"),
        ),
    )


def _manifest_id(spec: SourceSpec) -> str:
    manifest = spec.path.parent / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return spec.path.parent.name
    return _text(payload.get("id") or payload.get("dataset_id") or spec.path.parent.name, 160)


def _read_sources(dataset_dir: Path) -> tuple[list[dict[str, str]], dict[Path, dict[str, Any]]]:
    records: list[dict[str, str]] = []
    files: dict[Path, dict[str, Any]] = {}
    for spec in _source_specs(dataset_dir):
        if not spec.path.is_file():
            continue
        with spec.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
        files[spec.path] = {"spec": spec, "fieldnames": fieldnames, "rows": rows}
        version = _manifest_id(spec)
        for index, row in enumerate(rows):
            natural = [_text(row.get(field), 500) for field in spec.natural_fields]
            if not any(natural):
                continue
            key = _sync_key(spec.dataset_key, natural)
            value = _text(row.get(spec.value_field), 160)
            note = _first(row, spec.note_fields, limit=600)
            source = _first(row, spec.source_fields, limit=500)
            status = "／".join(
                value for value in (_text(row.get(field), 120) for field in spec.status_fields) if value
            )
            if _text(row.get("feishu_override_value"), 160):
                status = f"人工修訂／{status}" if status else "人工修訂"
            records.append(
                {
                    "資料庫": "競對生產源庫",
                    "資料集": spec.dataset_label,
                    "主體": _first(row, spec.subject_fields, limit=240),
                    "期間": _first(row, spec.period_fields, limit=120),
                    "指標": _first(row, spec.metric_fields, limit=240),
                    "本地值": value,
                    "單位": _first(row, spec.unit_fields, limit=120) or ("HKD／月" if spec.dataset_key == "competitor_product_tariffs" else ""),
                    "資料狀態": status,
                    "資料備註": note,
                    "人工修訂值": "",
                    "人工備註": "",
                    "來源": source,
                    "同步時間": "",
                    "同步鍵": key,
                    "版本／快照": version,
                    "__path": str(spec.path),
                    "__index": str(index),
                    "__value_field": spec.value_field,
                }
            )
    records.sort(key=lambda row: (row["資料集"], row["主體"], row["期間"], row["指標"], row["同步鍵"]))
    return records, files


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "rows": {}, "audit": []}
    if not isinstance(payload.get("rows"), dict):
        payload["rows"] = {}
    if not isinstance(payload.get("audit"), list):
        payload["audit"] = []
    return payload


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_override(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        number = float(text.replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"人工修訂值必須是數字：{text}") from exc
    if not math.isfinite(number):
        raise ValueError(f"人工修訂值必須是有限數字：{text}")
    return format(number, ".15g")


def _choose_editable(
    *, remote: str, local: str, last_remote: str | None, remote_exists: bool
) -> tuple[str, str]:
    if not remote_exists:
        return local, "local"
    if last_remote is None:
        return (remote, "remote") if remote else (local, "local")
    remote_changed = remote != last_remote
    local_changed = local != last_remote
    if remote_changed:
        return remote, "remote_conflict_wins" if local_changed and local != remote else "remote"
    return local, "local" if local_changed else "unchanged"


def _reconcile_editable(
    records: list[dict[str, str]], remote_rows: dict[str, dict[str, str]], state: dict[str, Any]
) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    state_rows = state.setdefault("rows", {})
    for record in records:
        key = record["同步鍵"]
        row_state = state_rows.setdefault(key, {})
        remote = remote_rows.get(key, {})
        for header, state_key in (("人工修訂值", "override_value"), ("人工備註", "note")):
            chosen, decision = _choose_editable(
                remote=_text(remote.get(header), 800),
                local=_text(row_state.get(state_key), 800),
                last_remote=(
                    _text(row_state.get(f"last_remote_{state_key}"), 800)
                    if f"last_remote_{state_key}" in row_state
                    else None
                ),
                remote_exists=bool(remote),
            )
            if state_key == "override_value":
                chosen = _validate_override(chosen)
            if decision != "unchanged" and chosen != _text(row_state.get(state_key), 800):
                audit.append(
                    {
                        "at": _now(),
                        "sync_key": key,
                        "field": header,
                        "from": _text(row_state.get(state_key), 800),
                        "to": chosen,
                        "decision": decision,
                    }
                )
            row_state[state_key] = chosen
            row_state[f"last_remote_{state_key}"] = chosen
            record[header] = chosen
        row_state["updated_at"] = _now()
    return audit


def _rewrite_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _apply_overrides(
    records: list[dict[str, str]], files: dict[Path, dict[str, Any]], state: dict[str, Any]
) -> int:
    changed_files: set[Path] = set()
    at = _now()
    for record in records:
        path = Path(record["__path"])
        source = files[path]
        row = source["rows"][int(record["__index"])]
        value_field = record["__value_field"]
        row_state = state["rows"][record["同步鍵"]]
        override = _text(row_state.get("override_value"), 160)
        current = _text(row.get(value_field), 160)
        existing_override = _text(row.get("feishu_override_value"), 160)
        last_applied = _text(row_state.get("last_applied_value") or existing_override, 160)
        original = _text(
            row.get("feishu_original_value")
            or row_state.get("original_value")
            or current,
            160,
        )
        if override:
            if last_applied and current not in {last_applied, override}:
                original = current
            elif not last_applied and current != override:
                original = current
            for field in PROVENANCE_FIELDS:
                if field not in source["fieldnames"]:
                    source["fieldnames"].append(field)
            desired = {
                value_field: override,
                "feishu_original_value": original,
                "feishu_override_value": override,
                "feishu_override_note": _text(row_state.get("note"), 800),
                "feishu_override_actor": "Feishu user",
                "feishu_override_at": at,
            }
            if any(_text(row.get(field), 800) != _text(value, 800) for field, value in desired.items()):
                row.update(desired)
                changed_files.add(path)
            row_state["original_value"] = original
            row_state["last_applied_value"] = override
        elif existing_override or last_applied:
            if current in {existing_override, last_applied}:
                row[value_field] = original
            for field in PROVENANCE_FIELDS:
                if field in row:
                    row[field] = ""
            changed_files.add(path)
            row_state.pop("original_value", None)
            row_state.pop("last_applied_value", None)
    for path in sorted(changed_files):
        source = files[path]
        _rewrite_csv(path, source["fieldnames"], source["rows"])
    return len(changed_files)


def _stamp_records(records: list[dict[str, str]], state: dict[str, Any]) -> None:
    """Keep unchanged rows stable so a periodic task only writes real deltas."""

    changed_at = _now()
    hash_headers = tuple(header for header in HEADERS if header != "同步時間")
    for record in records:
        row_state = state["rows"].setdefault(record["同步鍵"], {})
        digest = hashlib.sha256(
            json.dumps(
                [_text(record.get(header), 800) for header in hash_headers],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if digest != row_state.get("data_hash"):
            row_state["data_hash"] = digest
            row_state["data_synced_at"] = changed_at
        record["同步時間"] = _text(row_state.get("data_synced_at") or changed_at, 80)


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


class LarkSheetGateway:
    def __init__(self, *, token: str = SPREADSHEET_TOKEN, title: str = SHEET_TITLE) -> None:
        self.token = token
        self.title = title
        self.cli = resolve_lark_cli()
        self.profile = _text(os.environ.get("CMHK_DATABASE_SHEET_PROFILE") or os.environ.get("CMHK_FEISHU_PROFILE"), 180)
        configured_identity = _text(os.environ.get("CMHK_DATABASE_SHEET_IDENTITY"), 20)
        self.identity = configured_identity or ("bot" if self.profile else "user")
        if self.identity not in {"user", "bot"}:
            raise ValueError("CMHK_DATABASE_SHEET_IDENTITY 必須是 user 或 bot")
        self.sheet_headers: tuple[str, ...] = HEADERS
        self.sheet_col_count = len(HEADERS)
        self.ignored_manual_rows = 0
        self.ignored_duplicate_rows = 0

    def _run(
        self,
        args: list[str],
        *,
        input_text: str = "",
        timeout: int = 240,
        retry_safe: bool = False,
    ) -> dict[str, Any]:
        command = [self.cli, *args, "--as", self.identity]
        if self.profile:
            command.extend(["--profile", self.profile])
        attempts = 3 if retry_safe else 1
        completed: subprocess.CompletedProcess[str] | None = None
        for attempt in range(attempts):
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=lark_cli_env(),
                input=input_text,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            if not completed.returncode:
                break
            detail = (completed.stderr or completed.stdout).strip()
            transient = any(
                marker in detail.lower()
                for marker in (
                    '"type": "network"',
                    "timeout",
                    "timed out",
                    "deadline exceeded",
                    "dial tcp",
                    "connection reset",
                    "temporarily unavailable",
                )
            )
            if not (retry_safe and transient and attempt + 1 < attempts):
                raise RuntimeError(detail[-1600:])
            time.sleep(0.75 * (attempt + 1))
        assert completed is not None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("lark-cli 未返回有效 JSON") from exc
        if not payload.get("ok"):
            raise RuntimeError(_text(payload.get("error") or payload, 1600))
        return payload

    def _sheet(self) -> dict[str, Any] | None:
        payload = self._run(
            ["sheets", "+workbook-info", "--spreadsheet-token", self.token],
            retry_safe=True,
        )
        sheets = (payload.get("data") or {}).get("sheets") or []
        sheet = next(
            (
                item
                for item in sheets
                if _text(item.get("sheet_name") or item.get("title"), 160) == self.title
            ),
            None,
        )
        if sheet is not None:
            self.sheet_col_count = max(len(HEADERS), int(sheet.get("column_count") or 0))
        return sheet

    @staticmethod
    def _parse_annotated(
        text: str, headers: tuple[str, ...] | None
    ) -> tuple[tuple[str, ...], list[dict[str, str]]]:
        parsed: list[dict[str, str]] = []
        known = headers
        for raw in csv.reader(io.StringIO(text)):
            if not raw:
                continue
            match = re.match(r"^\[row=(\d+)\]\s?", raw[0])
            if not match:
                continue
            row_number = int(match.group(1))
            raw[0] = re.sub(r"^\[row=\d+\]\s?", "", raw[0], count=1)
            if known is None:
                known = tuple(raw)
                continue
            values = (raw + [""] * len(known))[: len(known)]
            row = dict(zip(known, values, strict=True))
            row["__row_number"] = str(row_number)
            parsed.append(row)
        return known or (), parsed

    def read_rows(self) -> tuple[bool, dict[str, dict[str, str]], int]:
        sheet = self._sheet()
        if sheet is None:
            return False, {}, 1
        rows: list[dict[str, str]] = []
        headers: tuple[str, ...] | None = None
        final_row = 1
        start = 1
        while True:
            end = start + 999
            payload = self._run(
                [
                    "sheets",
                    "+csv-get",
                    "--spreadsheet-token",
                    self.token,
                    "--sheet-name",
                    self.title,
                    "--range",
                    f"A{start}:{_column_letter(self.sheet_col_count)}{end}",
                ],
                retry_safe=True,
            )
            data = payload.get("data") or {}
            headers, page = self._parse_annotated(
                _text(data.get("annotated_csv"), 8_000_000), headers
            )
            rows.extend(page)
            region = _text(data.get("current_region"), 120)
            match = re.search(r":[A-Z]+(\d+)$", region)
            final_row = int(match.group(1)) if match else max(final_row, end if page else 1)
            row_indices = [int(value) for value in data.get("row_indices") or []]
            page_last = max(row_indices) if row_indices else start - 1
            if data.get("has_more") and start <= page_last < end:
                start = page_last + 1
                continue
            if end >= final_row:
                break
            start = end + 1
        if headers:
            missing = [header for header in HEADERS if header not in headers]
            ambiguous = [header for header in HEADERS if headers.count(header) > 1]
            if missing or ambiguous:
                raise RuntimeError(
                    f"飛書子表 {self.title} 核心欄位異常；缺少={missing}；重複={ambiguous}。"
                )
            self.sheet_headers = headers
            self.sheet_col_count = len(headers)
        mapped: dict[str, dict[str, str]] = {}
        manual_rows = 0
        duplicate_rows = 0
        for row in rows:
            if not any(_text(row.get(header)) for header in HEADERS):
                continue
            key = _text(row.get("同步鍵"), 200)
            if not key:
                manual_rows += 1
                continue
            if key in mapped:
                duplicate_rows += 1
                continue
            mapped[key] = row
        self.ignored_manual_rows = manual_rows
        self.ignored_duplicate_rows = duplicate_rows
        return True, mapped, final_row

    def _table_put(self, rows: list[dict[str, str]], *, start_row: int, header: bool) -> None:
        payload = {
            "sheets": [
                {
                    "name": self.title,
                    "mode": "overwrite",
                    "start_cell": f"A{start_row}",
                    "header": header,
                    "allow_overwrite": True,
                    "columns": list(HEADERS),
                    "dtypes": {name: "object" for name in HEADERS},
                    "data": [[_text(row.get(name), 800) for name in HEADERS] for row in rows],
                }
            ]
        }
        self._run(
            ["sheets", "+table-put", "--spreadsheet-token", self.token, "--sheets", "-"],
            input_text=json.dumps(payload, ensure_ascii=False),
            timeout=300,
            retry_safe=True,
        )

    def _styles(self, rows: list[dict[str, str]], last_row: int) -> None:
        widths: dict[str, int] = {}
        samples = rows[:250]
        positions = {header: self.sheet_headers.index(header) + 1 for header in HEADERS}
        for header in HEADERS:
            content = max([len(header), *[len(_text(row.get(header), 120)) for row in samples]])
            maximum = 360 if header in {"資料備註", "人工備註", "來源"} else 230
            widths[_column_letter(positions[header])] = max(
                86, min(maximum, 24 + content * 13)
            )
        editable_styles = [
            {
                "range": f"{_column_letter(positions[header])}2:{_column_letter(positions[header])}{max(2, last_row)}",
                "background_color": "#FFF2CC",
            }
            for header in EDITABLE_HEADERS
        ]
        technical_styles = [
            {
                "range": f"{_column_letter(positions[header])}2:{_column_letter(positions[header])}{max(2, last_row)}",
                "background_color": "#F3F4F6",
                "font_color": "#666666",
            }
            for header in ("同步鍵", "版本／快照")
        ]
        last_column = _column_letter(len(self.sheet_headers))
        styles = {
            "styles": [
                {
                    "name": self.title,
                    "cell_styles": [
                        {
                            "range": f"A1:{last_column}1",
                            "font_weight": "bold",
                            "font_color": "#FFFFFF",
                            "background_color": "#174A78",
                            "horizontal_alignment": "center",
                            "vertical_alignment": "middle",
                        },
                        {
                            "range": f"A2:{last_column}{max(2, last_row)}",
                            "font_size": 11,
                            "vertical_alignment": "middle",
                            "word_wrap": "auto-wrap",
                        },
                        *editable_styles,
                        *technical_styles,
                    ],
                    "row_sizes": [{"range": "1:1", "size": 34}],
                    "col_sizes": [
                        {"range": column, "size": width} for column, width in widths.items()
                    ],
                    "freeze": {"rows": 1, "cols": 5},
                }
            ]
        }
        self._run(
            ["sheets", "+styles-put", "--spreadsheet-token", self.token, "--styles", "-"],
            input_text=json.dumps(styles, ensure_ascii=False),
            retry_safe=True,
        )

    def _row_writes(
        self,
        row: dict[str, str],
        *,
        row_number: int,
        remote: dict[str, str] | None,
    ) -> list[dict[str, Any]]:
        positions = sorted(
            (self.sheet_headers.index(header) + 1, header)
            for header in HEADERS
            if remote is None
            or _text(remote.get(header), 800) != _text(row.get(header), 800)
        )
        if not positions:
            return []
        groups: list[list[tuple[int, str]]] = []
        for position in positions:
            if groups and position[0] == groups[-1][-1][0] + 1:
                groups[-1].append(position)
            else:
                groups.append([position])
        writes: list[dict[str, Any]] = []
        for group in groups:
            start_column = _column_letter(group[0][0])
            end_column = _column_letter(group[-1][0])
            writes.append(
                {
                    "sheet_name": self.title,
                    "range": f"{start_column}{row_number}:{end_column}{row_number}",
                    "cells": [
                        [{"value": _text(row.get(header), 800)} for _, header in group]
                    ],
                }
            )
        return writes

    def _write_batches(self, writes: list[dict[str, Any]]) -> None:
        for offset in range(0, len(writes), 80):
            self._run(
                [
                    "sheets",
                    "+cells-set",
                    "--spreadsheet-token",
                    self.token,
                    "--writes",
                    "-",
                ],
                input_text=json.dumps(writes[offset : offset + 80], ensure_ascii=False),
                retry_safe=True,
            )

    def upsert_rows(
        self,
        rows: list[dict[str, str]],
        *,
        existed: bool,
        remote_rows: dict[str, dict[str, str]],
        last_row: int,
    ) -> dict[str, Any]:
        created = not existed
        if created:
            self._run(
                [
                    "sheets",
                    "+sheet-create",
                    "--spreadsheet-token",
                    self.token,
                    "--title",
                    self.title,
                    "--row-count",
                    str(max(10_000, len(rows) + 250)),
                    "--col-count",
                    str(len(HEADERS)),
                ]
            )
            cursor = 1
            for offset in range(0, len(rows), 400):
                batch = rows[offset : offset + 400]
                self._table_put(batch, start_row=cursor, header=offset == 0)
                cursor += len(batch) + (1 if offset == 0 else 0)
            last_row = len(rows) + 1
            self._styles(rows, last_row)
            written = len(rows)
        else:
            existing_keys = set(remote_rows)
            new_rows = [row for row in rows if row["同步鍵"] not in existing_keys]
            cursor = last_row + 1
            writes: list[dict[str, Any]] = []
            for row in new_rows:
                writes.extend(self._row_writes(row, row_number=cursor, remote=None))
                cursor += 1
            for row in rows:
                remote = remote_rows.get(row["同步鍵"])
                if remote is None:
                    continue
                row_number = int(remote["__row_number"])
                writes.extend(
                    self._row_writes(row, row_number=row_number, remote=remote)
                )
            self._write_batches(writes)
            updated_keys = {
                row["同步鍵"]
                for row in rows
                if row["同步鍵"] in remote_rows
                and any(
                    _text(remote_rows[row["同步鍵"]].get(header), 800)
                    != _text(row.get(header), 800)
                    for header in HEADERS
                )
            }
            written = len(new_rows) + len(updated_keys)
            last_row = max(last_row, cursor - 1)
            if new_rows:
                self._styles(rows, last_row)
        _, readback, readback_last = self.read_rows()
        missing = [row["同步鍵"] for row in rows if row["同步鍵"] not in readback]
        if missing:
            raise RuntimeError(f"飛書回讀缺少 {len(missing)} 個同步鍵；首個：{missing[0]}")
        samples = [rows[0], rows[len(rows) // 2], rows[-1]] if rows else []
        for row in samples:
            actual = readback[row["同步鍵"]]
            for header in ("資料集", "本地值", "人工修訂值", "人工備註", "版本／快照"):
                if _text(actual.get(header), 800) != _text(row.get(header), 800):
                    raise RuntimeError(f"飛書回讀不一致：{row['同步鍵']} / {header}")
        return {
            "ok": True,
            "created": created,
            "written": written,
            "row_count": len(rows),
            "sheet_title": self.title,
            "sheet_url": f"https://cmhk-try.feishu.cn/sheets/{self.token}",
            "last_row": readback_last,
            "readback_verified": True,
            "extra_column_count": max(0, len(self.sheet_headers) - len(HEADERS)),
            "ignored_manual_rows": self.ignored_manual_rows,
            "ignored_duplicate_rows": self.ignored_duplicate_rows,
            "identity": self.identity,
        }


def sync_producer_database_sheet(
    dataset_dir: str | Path,
    *,
    release_id: str = "",
    gateway: LarkSheetGateway | None = None,
    state_path: Path = STATE_PATH,
) -> dict[str, Any]:
    """Pull governed edits, apply them locally, then incrementally mirror all rows."""

    if not _enabled():
        return {"ok": True, "status": "disabled", "message": "飛書資料庫同步已停用。"}
    dataset_path = Path(dataset_dir).expanduser().resolve()
    sheet = gateway or LarkSheetGateway()
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        existed, remote_rows, last_row = sheet.read_rows()
        state = _read_state(state_path)
        records, files = _read_sources(dataset_path)
        if not records:
            raise RuntimeError("沒有可同步的競對資料列。")
        audit = _reconcile_editable(records, remote_rows, state)
        changed_files = _apply_overrides(records, files, state)
        if changed_files:
            records, files = _read_sources(dataset_path)
            for record in records:
                row_state = state["rows"].get(record["同步鍵"], {})
                record["人工修訂值"] = _text(row_state.get("override_value"), 160)
                record["人工備註"] = _text(row_state.get("note"), 800)
        else:
            for record in records:
                row_state = state["rows"].get(record["同步鍵"], {})
                record["人工修訂值"] = _text(row_state.get("override_value"), 160)
                record["人工備註"] = _text(row_state.get("note"), 800)
        _stamp_records(records, state)
        local_keys = {row["同步鍵"] for row in records}
        for key, remote in remote_rows.items():
            if key in local_keys:
                continue
            orphan = {header: _text(remote.get(header), 800) for header in HEADERS}
            if orphan["資料狀態"] != "本地已下線":
                orphan["資料狀態"] = "本地已下線"
                orphan["同步時間"] = _now()
            records.append(orphan)
        records.sort(key=lambda row: (row["資料狀態"] == "本地已下線", row["資料集"], row["主體"], row["期間"], row["指標"], row["同步鍵"]))
        state["audit"] = (state.get("audit") or [])[-999:] + audit
        state["last_pull_at"] = _now()
        state["release_id"] = release_id
        _atomic_json(state_path, state)
        result = sheet.upsert_rows(
            records,
            existed=existed,
            remote_rows=remote_rows,
            last_row=last_row,
        )
        state["last_sync_at"] = _now()
        state["last_readback_verified"] = bool(result.get("readback_verified"))
        state["last_row_count"] = int(result.get("row_count") or 0)
        _atomic_json(state_path, state)
        return {
            **result,
            "status": "synced",
            "changed_source_files": changed_files,
            "edit_audit_count": len(audit),
            "release_id": release_id,
            "message": SUCCESS_MESSAGE,
        }


__all__ = [
    "HEADERS",
    "LarkSheetGateway",
    "SHEET_TITLE",
    "SUCCESS_MESSAGE",
    "sync_producer_database_sheet",
]
