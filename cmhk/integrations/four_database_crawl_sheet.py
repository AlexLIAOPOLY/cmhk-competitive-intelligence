from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cmhk.integrations.feishu_runtime import resolve_lark_cli


ROOT = Path(__file__).resolve().parents[2]
HKT = ZoneInfo("Asia/Hong_Kong")
SPREADSHEET_TOKEN = os.environ.get("CMHK_FOUR_DATABASE_LOG_SPREADSHEET_TOKEN", "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA")
SHEET_TITLE = os.environ.get("CMHK_FOUR_DATABASE_LOG_SHEET_TITLE", "四库爬虫明细日志")
STATE_PATH = ROOT / "var" / "four_database_crawl_sheet" / "state.json"
LOCK_PATH = ROOT / "var" / "four_database_crawl_sheet" / "write.lock"
LARK_CLI = resolve_lark_cli()

HEADERS = [
    "记录时间", "事件ID", "运行ID", "阶段", "四库", "主体／查询", "动作",
    "来源URL", "HTTP状态", "抓取结果", "内容变化", "入库决定", "指标",
    "数值／摘要", "原因／错误", "交接／父任务", "证据哈希",
]


def _text(value: Any, limit: int = 1800) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = "、".join(_text(item, 300) for item in value if _text(item, 300))
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()[:limit]


def _event_id(parts: Iterable[Any]) -> str:
    raw = "\x1f".join(_text(part, 5000) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _row(*, run_id: str, stage: str, domain: str = "", subject: str = "", action: str = "",
         url: str = "", http_status: Any = "", result: str = "", changed: Any = "",
         decision: str = "", metric: str = "", value: Any = "", reason: Any = "",
         handoff: str = "", evidence_hash: str = "", timestamp: str = "", discriminator: str = "") -> dict[str, str]:
    recorded_at = timestamp or datetime.now(HKT).isoformat(timespec="seconds")
    event_id = _event_id((
        "content-v2", run_id, stage, domain, subject, action, url, http_status,
        result, changed, decision, metric, value, reason, handoff, evidence_hash,
        discriminator,
    ))
    return dict(zip(HEADERS, [
        recorded_at, event_id, run_id, stage, domain, subject, action, url,
        http_status, result, changed, decision, metric, value, reason, handoff, evidence_hash,
    ]))


def discovery_rows(payload: dict[str, Any], *, plans: list[dict[str, Any]] | None = None,
                   search_items: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    run_id = _text(payload.get("run_id"), 120)
    timestamp = _text(payload.get("generated_at_hkt"), 80)
    rows = [_row(
        run_id=run_id, stage="01:00资料搜索", action="运行汇总", result="成功" if payload.get("ok", True) else "失败",
        value=f"查询{int(payload.get('query_count') or 0)}；搜索结果{int(payload.get('search_result_count') or 0)}；线索{int(payload.get('signal_count') or 0)}",
        reason=payload.get("errors") or "搜索结果只作线索，03:00必须追官方原文",
        handoff=f"交接日期 {payload.get('handoff_for_date') or ''}；前一日新闻参考{int(payload.get('previous_day_reference_count') or 0)}条",
        timestamp=timestamp,
    )]
    for index, plan in enumerate(plans or [], start=1):
        rows.append(_row(
            run_id=run_id, stage="01:00资料搜索", domain=_text(plan.get("module")).split("/")[-1],
            subject=_text(plan.get("query")), action="搜索查询", result="已执行",
            value=_text(plan.get("fallback_query")), handoff="03:00官方来源追踪",
            timestamp=timestamp, discriminator=f"query-{index}",
        ))
    for index, item in enumerate(search_items or [], start=1):
        rows.append(_row(
            run_id=run_id, stage="01:00资料搜索", subject=_text(item.get("title")), action="搜索结果",
            url=_text(item.get("url") or item.get("source_url")), result="仅作线索",
            value=_text(item.get("summary") or item.get("snippet")), reason="不得直接入库",
            handoff="等待03:00追官方原文", timestamp=timestamp, discriminator=f"result-{index}",
        ))
    for index, signal in enumerate(payload.get("signals") or [], start=1):
        rows.append(_row(
            run_id=run_id, stage="01:00资料搜索", domain=_text(signal.get("domain")), subject=_text(signal.get("entity")),
            action="四库线索", url=_text(signal.get("news_url")), result="需追官方原文",
            value=_text(signal.get("title")), reason=_text(signal.get("reference_origin")),
            handoff=_text(signal.get("official_followup_urls")), timestamp=timestamp, discriminator=f"signal-{index}",
        ))
    for index, reference in enumerate(payload.get("previous_day_references") or [], start=1):
        rows.append(_row(
            run_id=run_id, stage="前一日09:00／14:00新闻参考", subject=_text(reference.get("title")), action="新闻参考",
            url=_text(reference.get("url") or reference.get("source_url")), result="仅作线索",
            value=_text(reference.get("summary") or reference.get("snippet")), reason=_text(reference.get("reference_run")),
            handoff="03:00若命中四库字段则追官方原文", timestamp=timestamp, discriminator=f"news-{index}",
        ))
    return rows


def pipeline_rows(state: dict[str, Any], *, recrawl: dict[str, Any] | None = None,
                  candidates: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    run_id = _text(state.get("task_run_id") or state.get("agent_run_id"), 120)
    timestamp = _text(state.get("completed_at_hkt") or state.get("started_at_hkt"), 80)
    summary = (recrawl or {}).get("summary") or state.get("overview_source_recrawl") or {}
    rows = [_row(
        run_id=run_id, stage="03:00四库更新", action="运行汇总",
        result="成功" if state.get("ok") else _text(state.get("status")),
        value=f"官方URL{int(summary.get('official_urls') or 0)}；成功{int(summary.get('retrieved') or 0)}；失败{int(summary.get('failed') or 0)}",
        reason=state.get("error") or "搜索和新闻仅作线索；官方原文与字段门禁通过后才入库",
        handoff=_text(state.get("agent_run_id")), timestamp=timestamp,
    )]
    for index, item in enumerate((recrawl or {}).get("source_crawl") or [], start=1):
        rows.append(_row(
            run_id=run_id, stage="官方原文抓取", domain=_text(item.get("domains")), action="URL抓取",
            url=_text(item.get("url")), http_status=item.get("status"),
            result="成功" if item.get("ok") else "失败", changed="是" if item.get("content_changed") else "否",
            value=f"采样{int(item.get('bytes_sampled') or 0)}字节" if item.get("ok") else "",
            reason=item.get("error") or item.get("fingerprint_kind"), evidence_hash=_text(item.get("content_fingerprint")),
            timestamp=_text(item.get("retrieved_at") or timestamp), discriminator=f"url-{index}",
        ))
    for index, fact in enumerate(candidates or [], start=1):
        if _text(fact.get("row_ref")) not in {"row_47", "row_48", "row_49", "row_50"}:
            continue
        sources = fact.get("sources") or []
        rows.append(_row(
            run_id=run_id, stage="事实抽取与入库门禁", domain=_text(fact.get("row_ref")), subject=_text(fact.get("company")),
            action="候选事实", url=_text(sources[0] if sources else ""),
            result=_text(fact.get("status")), decision=_text(fact.get("decision")), metric=_text(fact.get("metric")),
            value=fact.get("value"), reason=fact.get("reasons") or fact.get("note") or fact.get("basis"),
            handoff=f"source_tier={_text(fact.get('source_tier'))}; quality={fact.get('quality_score', '')}",
            evidence_hash=_text(fact.get("evidence_hash")), timestamp=timestamp, discriminator=f"fact-{index}-{fact.get('id')}",
        ))
    return rows


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        env.pop(key, None)
    env.update({"LARK_CLI_NO_PROXY": "1", "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"})
    return env


def _run(
    args: list[str],
    *,
    input_text: str = "",
    retry_safe: bool = False,
) -> dict[str, Any]:
    attempts = (
        max(1, int(os.environ.get("CMHK_LARK_CLI_READ_ATTEMPTS", "5")))
        if retry_safe
        else 1
    )
    for attempt in range(attempts):
        try:
            completed = subprocess.run(
                [LARK_CLI, *args], cwd=ROOT, env=_env(), text=True,
                input=input_text, capture_output=True, timeout=180, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if retry_safe and attempt + 1 < attempts:
                time.sleep(min(8.0, 1.0 * (2**attempt)))
                continue
            raise RuntimeError(
                f"lark-cli 在 {exc.timeout} 秒内未返回；已尝试 {attempt + 1} 次"
            ) from exc
        except OSError as exc:
            if retry_safe and attempt + 1 < attempts:
                time.sleep(min(8.0, 1.0 * (2**attempt)))
                continue
            raise RuntimeError(f"lark-cli 启动失败：{type(exc).__name__}") from exc
        detail = (completed.stderr or completed.stdout).strip()
        payload: dict[str, Any] | None = None
        if not completed.returncode:
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                detail = "lark-cli 未返回有效 JSON"
            else:
                if payload.get("ok"):
                    return payload
                detail = _text(payload.get("error") or payload, 1600)
        transient = any(
            marker in detail.lower()
            for marker in (
                '"type": "network"', "timeout", "timed out", "deadline exceeded",
                "dial tcp", "connection reset", "connection refused", "connection closed",
                "temporary failure in name resolution", "no such host", "temporarily unavailable",
            )
        )
        if retry_safe and transient and attempt + 1 < attempts:
            time.sleep(min(8.0, 1.0 * (2**attempt)))
            continue
        raise RuntimeError(detail[-1600:])
    raise RuntimeError("lark-cli 调用失败")


def _sheet_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    sheets = data.get("sheets") or []
    return sheets if isinstance(sheets, list) else []


def _current_region_last_row(payload: dict[str, Any]) -> int:
    current_region = _text((payload.get("data") or {}).get("current_region"), 120)
    match = re.search(r":[A-Z]+(\d+)$", current_region)
    return int(match.group(1)) if match else 0


def _parse_event_id_cells(payload: dict[str, Any]) -> dict[str, int]:
    annotated = _text((payload.get("data") or {}).get("annotated_csv"), 8_000_000)
    result: dict[str, int] = {}
    duplicates: list[str] = []
    for raw in csv.reader(io.StringIO(annotated)):
        if not raw:
            continue
        match = re.match(r"^\[row=(\d+)\]\s?(.*)$", raw[0])
        if not match:
            continue
        row_number = int(match.group(1))
        event_id = match.group(2).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{20}", event_id):
            continue
        if event_id in result:
            duplicates.append(event_id)
        else:
            result[event_id] = row_number
    if duplicates:
        raise RuntimeError(
            f"飞书明细日志存在 {len(duplicates)} 个重复事件ID；首个：{duplicates[0]}"
        )
    return result


def _read_event_ids_range(start_row: int, end_row: int) -> dict[str, int]:
    if end_row < start_row:
        return {}
    payload = _run(
        [
            "sheets", "+csv-get", "--spreadsheet-token", SPREADSHEET_TOKEN,
            "--sheet-name", SHEET_TITLE, "--range", f"B{start_row}:B{end_row}",
        ],
        retry_safe=True,
    )
    return _parse_event_id_cells(payload)


def _read_live_event_ids() -> tuple[dict[str, int], int]:
    region_payload = _run(
        [
            "sheets", "+csv-get", "--spreadsheet-token", SPREADSHEET_TOKEN,
            "--sheet-name", SHEET_TITLE, "--range", "B1:B1",
        ],
        retry_safe=True,
    )
    last_row = _current_region_last_row(region_payload)
    if last_row <= 1:
        return {}, max(last_row, 1)
    event_rows: dict[str, int] = {}
    for start_row in range(2, last_row + 1, 1000):
        page = _read_event_ids_range(start_row, min(last_row, start_row + 999))
        duplicates = sorted(set(event_rows) & set(page))
        if duplicates:
            raise RuntimeError(
                f"飞书明细日志存在跨分页重复事件ID；首个：{duplicates[0]}"
            )
        event_rows.update(page)
    return event_rows, last_row


def _event_index_sha256(event_rows: dict[str, int]) -> str:
    payload = [[event_id, event_rows[event_id]] for event_id in sorted(event_rows)]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def append_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return {"ok": True, "written": 0, "skipped": 0}
    requested_ids = [row["事件ID"] for row in rows]
    if len(set(requested_ids)) != len(requested_ids):
        raise RuntimeError("待写入的飞书明细日志包含重复事件ID，本轮已停止。")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            info = _run(
                ["sheets", "+workbook-info", "--spreadsheet-token", SPREADSHEET_TOKEN],
                retry_safe=True,
            )
            sheet = next((item for item in _sheet_items(info) if _text(item.get("sheet_name") or item.get("title")) == SHEET_TITLE), None)
            created = sheet is None
            if created:
                _run(["sheets", "+sheet-create", "--spreadsheet-token", SPREADSHEET_TOKEN, "--title", SHEET_TITLE,
                      "--row-count", "5000", "--col-count", str(len(HEADERS))])
                live_event_rows: dict[str, int] = {}
                live_last_row = 1
            else:
                live_event_rows, live_last_row = _read_live_event_ids()
            pending = [row for row in rows if row["事件ID"] not in live_event_rows]
            if not pending:
                requested_missing = sorted(set(requested_ids) - set(live_event_rows))
                if requested_missing:
                    raise RuntimeError(
                        f"飞书明细日志全量回读缺少事件：{requested_missing[0]}"
                    )
                state.update({
                    "sheet_title": SHEET_TITLE,
                    "event_ids": sorted(live_event_rows)[-20_000:],
                    "last_checked_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
                    "last_readback_verified": True,
                    "last_live_event_count": len(live_event_rows),
                    "last_event_index_sha256": _event_index_sha256(live_event_rows),
                })
                STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                temporary = STATE_PATH.with_suffix(".tmp")
                temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(STATE_PATH)
                return {
                    "ok": True, "written": 0, "skipped": len(rows),
                    "sheet_title": SHEET_TITLE,
                    "row_start": min(live_event_rows[event_id] for event_id in requested_ids),
                    "row_end": max(live_event_rows[event_id] for event_id in requested_ids),
                    "readback_verified": True,
                    "readback_reason": "live_full_event_id_readback",
                    "readback_scope": "all_live_event_ids",
                    "live_event_count": len(live_event_rows),
                    "event_index_sha256": _event_index_sha256(live_event_rows),
                }
            start_cell = "A1" if created else f"A{live_last_row + 1}"
            sheet_payload = {
                "sheets": [{
                    "name": SHEET_TITLE, "mode": "overwrite", "start_cell": start_cell,
                    "header": created, "allow_overwrite": False,
                    "columns": HEADERS, "dtypes": {header: "object" for header in HEADERS},
                    "data": [[_text(row.get(header)) for header in HEADERS] for row in pending],
                }]
            }
            start_row = int(re.search(r"\d+", start_cell).group())
            data_start_row = start_row + (1 if created else 0)
            data_end_row = data_start_row + len(pending) - 1
            write_recovered_by_readback = False
            for write_attempt in range(3):
                try:
                    _run(
                        ["sheets", "+table-put", "--spreadsheet-token", SPREADSHEET_TOKEN, "--sheets", "-"],
                        input_text=json.dumps(sheet_payload, ensure_ascii=False),
                    )
                    break
                except RuntimeError:
                    observed: dict[str, int] = {}
                    for recovery_attempt in range(2):
                        time.sleep(1.0 * (recovery_attempt + 1))
                        observed = _read_event_ids_range(data_start_row, data_end_row)
                        if set(observed) == {row["事件ID"] for row in pending}:
                            write_recovered_by_readback = True
                            break
                        if observed:
                            raise RuntimeError(
                                "飞书明细日志疑似部分写入；已停止自动重试，避免重复审计行。"
                            )
                    if write_recovered_by_readback:
                        break
                    if write_attempt == 2:
                        raise
            if created:
                styles = {"styles": [{
                    "name": SHEET_TITLE,
                    "cell_styles": [
                        {"range": f"A1:{chr(64 + len(HEADERS))}1", "font_weight": "bold", "font_color": "#FFFFFF", "background_color": "#174A78", "horizontal_alignment": "center"},
                        {"range": f"A2:{chr(64 + len(HEADERS))}5000", "vertical_alignment": "top", "word_wrap": "auto-wrap"},
                    ],
                    "col_sizes": [
                        {"range": "A:A", "size": 170}, {"range": "B:C", "size": 165}, {"range": "D:G", "size": 145},
                        {"range": "H:H", "size": 340}, {"range": "I:M", "size": 105}, {"range": "N:Q", "size": 300},
                    ],
                    "row_sizes": [{"range": "1:1", "size": 32}], "freeze": {"rows": 1, "cols": 3},
                }]}
                try:
                    _run(["sheets", "+styles-put", "--spreadsheet-token", SPREADSHEET_TOKEN, "--styles", "-"],
                         input_text=json.dumps(styles, ensure_ascii=False))
                except RuntimeError:
                    state["last_style_warning"] = "styles_put_failed_after_data_write"
            appended_readback = _read_event_ids_range(data_start_row, data_end_row)
            expected_pending_ids = {row["事件ID"] for row in pending}
            if set(appended_readback) != expected_pending_ids:
                raise RuntimeError(
                    f"飞书明细日志写入后逐行回读不一致：range=B{data_start_row}:B{data_end_row}; "
                    f"expected={len(expected_pending_ids)}; actual={len(appended_readback)}"
                )
            live_event_rows, live_last_row = _read_live_event_ids()
            requested_missing = sorted(set(requested_ids) - set(live_event_rows))
            if requested_missing:
                raise RuntimeError(
                    f"飞书明细日志写入后全量回读缺少事件：{requested_missing[0]}"
                )
            state.update({
                "sheet_title": SHEET_TITLE, "event_ids": sorted(live_event_rows)[-20_000:],
                "last_written_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"), "last_written": len(pending),
                "last_readback_verified": True, "last_row_start": data_start_row, "last_row_end": data_end_row,
                "last_live_event_count": len(live_event_rows),
                "last_event_index_sha256": _event_index_sha256(live_event_rows),
            })
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATE_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(STATE_PATH)
            return {
                "ok": True, "written": len(pending), "skipped": len(rows) - len(pending), "created": created,
                "sheet_title": SHEET_TITLE, "sheet_url": f"https://cmhk-try.feishu.cn/sheets/{SPREADSHEET_TOKEN}",
                "row_start": data_start_row, "row_end": data_end_row,
                "readback_verified": True,
                "readback_reason": "live_full_event_id_readback",
                "readback_scope": "all_live_event_ids",
                "live_event_count": len(live_event_rows),
                "event_index_sha256": _event_index_sha256(live_event_rows),
                "write_recovered_by_readback": write_recovered_by_readback,
            }
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def append_pipeline_artifacts(state: dict[str, Any]) -> dict[str, Any]:
    recrawl_path = ROOT / "agent_knowledge" / "requested_overview_010304_2016_2025" / "official_source_recrawl.json"
    run_id = _text(state.get("agent_run_id"), 120)
    candidates_path = ROOT / "curation_data" / "runs" / f"{run_id}_candidate_facts.jsonl"
    try:
        recrawl = json.loads(recrawl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        recrawl = {}
    candidates: list[dict[str, Any]] = []
    if candidates_path.is_file():
        candidates = [json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return append_rows(pipeline_rows(state, recrawl=recrawl, candidates=candidates))
