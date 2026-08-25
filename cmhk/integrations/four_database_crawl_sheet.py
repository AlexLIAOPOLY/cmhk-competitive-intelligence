from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
HKT = ZoneInfo("Asia/Hong_Kong")
SPREADSHEET_TOKEN = os.environ.get("CMHK_FOUR_DATABASE_LOG_SPREADSHEET_TOKEN", "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA")
SHEET_TITLE = os.environ.get("CMHK_FOUR_DATABASE_LOG_SHEET_TITLE", "四库爬虫明细日志")
STATE_PATH = ROOT / "var" / "four_database_crawl_sheet" / "state.json"
LOCK_PATH = ROOT / "var" / "four_database_crawl_sheet" / "write.lock"
LARK_CLI = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"

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
    event_id = _event_id((run_id, stage, domain, subject, action, url, metric, discriminator))
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


def _run(args: list[str], *, input_text: str = "") -> dict[str, Any]:
    completed = subprocess.run([LARK_CLI, *args], cwd=ROOT, env=_env(), text=True, input=input_text,
                               capture_output=True, timeout=180, check=False)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[-1200:])
    payload = json.loads(completed.stdout)
    if not payload.get("ok"):
        raise RuntimeError(_text(payload.get("error")))
    return payload


def _sheet_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    sheets = data.get("sheets") or []
    return sheets if isinstance(sheets, list) else []


def append_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return {"ok": True, "written": 0, "skipped": 0}
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            logged = set(state.get("event_ids") or [])
            pending = [row for row in rows if row["事件ID"] not in logged]
            if not pending:
                return {"ok": True, "written": 0, "skipped": len(rows), "sheet_title": SHEET_TITLE}
            info = _run(["sheets", "+workbook-info", "--spreadsheet-token", SPREADSHEET_TOKEN])
            sheet = next((item for item in _sheet_items(info) if _text(item.get("sheet_name") or item.get("title")) == SHEET_TITLE), None)
            created = sheet is None
            if created:
                _run(["sheets", "+sheet-create", "--spreadsheet-token", SPREADSHEET_TOKEN, "--title", SHEET_TITLE,
                      "--row-count", "5000", "--col-count", str(len(HEADERS))])
            start_cell = "A1"
            if not created:
                existing = _run([
                    "sheets", "+csv-get", "--spreadsheet-token", SPREADSHEET_TOKEN,
                    "--sheet-name", SHEET_TITLE,
                ])
                current_region = _text((existing.get("data") or {}).get("current_region"), 120)
                match = re.search(r":?[A-Z]+(\d+)$", current_region)
                start_cell = f"A{int(match.group(1)) + 1}" if match else "A1"
            sheet_payload = {
                "sheets": [{
                    "name": SHEET_TITLE, "mode": "overwrite", "start_cell": start_cell,
                    "header": created, "allow_overwrite": False,
                    "columns": HEADERS, "dtypes": {header: "object" for header in HEADERS},
                    "data": [[_text(row.get(header)) for header in HEADERS] for row in pending],
                }]
            }
            _run(["sheets", "+table-put", "--spreadsheet-token", SPREADSHEET_TOKEN, "--sheets", "-"],
                 input_text=json.dumps(sheet_payload, ensure_ascii=False))
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
                _run(["sheets", "+styles-put", "--spreadsheet-token", SPREADSHEET_TOKEN, "--styles", "-"],
                     input_text=json.dumps(styles, ensure_ascii=False))
            logged.update(row["事件ID"] for row in pending)
            state.update({
                "sheet_title": SHEET_TITLE, "event_ids": sorted(logged)[-20000:],
                "last_written_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"), "last_written": len(pending),
            })
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATE_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(STATE_PATH)
            return {"ok": True, "written": len(pending), "skipped": len(rows) - len(pending), "created": created, "sheet_title": SHEET_TITLE}
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
