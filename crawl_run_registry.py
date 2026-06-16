from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import crawl


ROOT = Path(__file__).resolve().parent
REGISTRY_DIR = ROOT / "agent_knowledge" / "crawl_run_logs"
RUNS_DIR = REGISTRY_DIR / "runs"
INDEX_JSON = REGISTRY_DIR / "index.json"
LATEST_JSON = REGISTRY_DIR / "latest.json"
INDEX_MD = REGISTRY_DIR / "index.md"
MANIFEST_JSON = REGISTRY_DIR / "manifest.json"
README_MD = REGISTRY_DIR / "README.md"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_id(value: str) -> str:
    clean = re.sub(r"^爬虫日志[_-]?", "", value)
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", clean).strip("._-")
    return clean or datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d_%H%M%S")


def _line_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def load_final_audit_summary() -> dict[str, Any]:
    path = ROOT / "final_audit.md"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    return {
        "generated_at": _line_value(text, "Generated at"),
        "rows_crawled": _line_value(text, "Rows crawled"),
        "ok_rows": _line_value(text, "OK rows"),
        "partial_rows": _line_value(text, "Partial rows"),
        "failed_rows": _line_value(text, "Failed/no extraction rows"),
        "fulfilled": _line_value(text, "Information requirements fulfilled"),
        "live_url_success": _line_value(text, "Live URL success"),
        "live_url_failures": _line_value(text, "Live URL failures"),
        "restored_from_previous_evidence": _line_value(text, "URLs restored from previous evidence"),
    }


def load_run_log_summary() -> dict[str, Any]:
    path = ROOT / "run_log.tsv"
    if not path.exists():
        return {"rows": 0, "success_urls": 0, "failed_urls": 0, "fallback_urls": 0}
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    success_urls = 0
    fallback_urls = 0
    failed_urls = 0
    for row in rows:
        status = int(row.get("http_status") or 0)
        fallback = str(row.get("evidence_fallback_used") or "").lower() in {"1", "true", "yes"}
        if fallback:
            fallback_urls += 1
            failed_urls += 1
        elif 200 <= status < 400:
            success_urls += 1
        else:
            failed_urls += 1
    return {
        "rows": len(rows),
        "success_urls": success_urls,
        "failed_urls": failed_urls,
        "fallback_urls": fallback_urls,
    }


def load_curation_summary() -> dict[str, Any]:
    latest = _read_json(ROOT / "curation_data" / "latest.json", {})
    if not isinstance(latest, dict):
        return {}
    return {
        "agent_run_id": latest.get("run_id", ""),
        "started_at": latest.get("started_at", ""),
        "completed_at": latest.get("completed_at", ""),
        "tasks": latest.get("tasks", 0),
        "accepted": latest.get("accepted", 0),
        "rejected": latest.get("rejected", 0),
        "review": latest.get("review", 0),
        "gaps": latest.get("gaps", 0),
        "recrawl_rows": latest.get("recrawl_rows", []),
        "agent_trace": (latest.get("extra") or {}).get("agent_trace", ""),
        "search_verification": (latest.get("extra") or {}).get("search_verification", {}),
    }


def ensure_registry_docs() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": "crawl-run-logs",
        "title": "爬虫运行日志索引",
        "summary": "记录每次全量爬虫对应的本地审计文件、飞书日志页、Agent 数据整理运行 ID 和质量摘要，供小竞 AI 调度、追溯和回答运行状态问题。",
        "source_type": "internal_operational_log",
        "scope": "运行审计与调度索引；完整逐 URL 日志以飞书日志子表和 run_log.tsv 为准。",
        "updated_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat(),
        "tags": ["爬虫日志", "运行审计", "Agent调度", "飞书日志", "数据质量"],
        "keywords": ["爬虫日志", "运行记录", "飞书日志", "Agent trace", "覆盖率", "失败链接", "缺口", "调度"],
        "entrypoints": ["README.md", "index.md", "latest.json", "index.json"],
        "quality": "index.json/latest.json 为调度索引；飞书日志页保存完整 run_log.tsv 和 Agent trace，若本地索引与飞书不一致，以飞书日志页和 daily_validation.json 为准。",
    }
    _write_json(MANIFEST_JSON, manifest)
    README_MD.write_text(
        """# 爬虫运行日志索引

这个数据集用于让小竞 AI 明确知道每次爬虫日志在哪里、如何追溯、如何调度使用。

## 保存策略

- 飞书日志子表：保存完整逐 URL 爬虫日志，并在 Agent 数据整理完成后追加 Agent 处理流程与结果。
- 本地运行索引：保存轻量摘要、飞书日志页链接、本地审计文件路径和 Agent run_id，供 Agent 快速检索。

## 主要文件

- `index.md`：最近运行的人类可读索引。
- `index.json`：最近多次运行的结构化索引。
- `latest.json`：最新一次运行摘要。
- `runs/<crawl_run_id>.json`：单次运行详情。

## Agent 使用规则

当用户询问爬虫运行、失败链接、覆盖率、飞书日志、Agent 调度或上次爬虫结果时，先读取本数据集，再按需要读取 `/references/run_log.tsv`、`/references/coverage_report.tsv`、`/references/final_audit.md` 或打开飞书日志页。
""",
        encoding="utf-8",
    )


def render_index_markdown(runs: list[dict[str, Any]]) -> str:
    lines = [
        "# 爬虫运行日志索引",
        "",
        f"- 更新时间：{datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds')}",
        "- 完整逐 URL 日志在飞书日志子表；本地保留轻量索引用于 Agent 检索和调度。",
        "",
        "| 运行ID | 时间 | 覆盖率 | URL成功/失败 | 飞书日志 | Agent运行 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in runs[:20]:
        audit = item.get("final_audit") or {}
        run_log = item.get("run_log") or {}
        feishu = item.get("feishu") or {}
        curation = item.get("curation") or {}
        feishu_label = feishu.get("log_sheet_title") or feishu.get("log_sheet_id") or "未写入"
        feishu_url = feishu.get("url") or ""
        feishu_cell = f"[{feishu_label}]({feishu_url})" if feishu_url else feishu_label
        lines.append(
            "| {run_id} | {time} | {fulfilled} | {ok}/{failed} | {feishu} | {agent} |".format(
                run_id=item.get("crawl_run_id", ""),
                time=item.get("completed_at_hkt") or item.get("started_at_hkt") or "",
                fulfilled=audit.get("fulfilled") or "",
                ok=run_log.get("success_urls", 0),
                failed=run_log.get("failed_urls", 0),
                feishu=feishu_cell,
                agent=curation.get("agent_run_id") or "",
            )
        )
    return "\n".join(lines).strip() + "\n"


def load_index() -> list[dict[str, Any]]:
    data = _read_json(INDEX_JSON, [])
    return data if isinstance(data, list) else []


def register_crawl_run(
    *,
    crawl_return_code: int | None = None,
    duration_ms: int | None = None,
    sync_result: dict[str, Any] | None = None,
    metrics_refresh: dict[str, Any] | None = None,
    trace_sync: dict[str, Any] | None = None,
    trigger: str = "web",
) -> dict[str, Any]:
    ensure_registry_docs()
    validation = _read_json(ROOT / "daily_validation.json", {})
    curation = load_curation_summary()
    log_sheet_id = str((sync_result or {}).get("log_sheet_id") or validation.get("log_sheet_id") or "")
    log_sheet_title = str((sync_result or {}).get("log_sheet_title") or validation.get("log_sheet_title") or "")
    crawl_run_id = _safe_id(log_sheet_title or curation.get("agent_run_id") or datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat())
    now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
    feishu_url = (
        f"https://cmhk-try.feishu.cn/sheets/{crawl.SPREADSHEET_TOKEN}?sheet={log_sheet_id}"
        if log_sheet_id
        else ""
    )
    record = {
        "crawl_run_id": crawl_run_id,
        "trigger": trigger,
        "started_at_hkt": validation.get("checked_at_hkt", ""),
        "completed_at_hkt": now,
        "crawl_return_code": crawl_return_code,
        "duration_ms": duration_ms,
        "feishu": {
            "spreadsheet_token": crawl.SPREADSHEET_TOKEN,
            "main_sheet_id": crawl.MAIN_SHEET_ID,
            "log_sheet_id": log_sheet_id,
            "log_sheet_title": log_sheet_title,
            "url": feishu_url,
            "sync_ok": bool(validation.get("ok")) if validation else bool(log_sheet_id),
            "result_columns": validation.get("result_columns") if isinstance(validation, dict) else {},
            "compliance_gaps": validation.get("compliance_gaps", []) if isinstance(validation, dict) else [],
        },
        "local_files": {
            "final_audit": "final_audit.md",
            "coverage_report": "coverage_report.tsv",
            "run_log_tsv": "run_log.tsv",
            "run_log_json": "run_log.json",
            "daily_validation": "daily_validation.json",
            "curation_latest": "curation_data/latest.json",
            "agent_trace": curation.get("agent_trace", ""),
        },
        "final_audit": load_final_audit_summary(),
        "run_log": load_run_log_summary(),
        "curation": curation,
        "metrics_refresh": metrics_refresh or {},
        "agent_trace_feishu_sync": trace_sync or {},
    }
    _write_json(RUNS_DIR / f"{crawl_run_id}.json", record)
    runs = [item for item in load_index() if item.get("crawl_run_id") != crawl_run_id]
    runs.insert(0, record)
    runs = runs[:50]
    _write_json(INDEX_JSON, runs)
    _write_json(LATEST_JSON, record)
    INDEX_MD.write_text(render_index_markdown(runs), encoding="utf-8")
    return record


def latest_crawl_run_summary(limit: int = 5) -> str:
    ensure_registry_docs()
    runs = load_index()[:limit]
    if not runs:
        return "当前还没有记录到爬虫运行索引。"
    lines = ["最近爬虫运行索引："]
    for item in runs:
        audit = item.get("final_audit") or {}
        run_log = item.get("run_log") or {}
        feishu = item.get("feishu") or {}
        curation = item.get("curation") or {}
        lines.append(
            "\n".join(
                [
                    f"- 运行ID：{item.get('crawl_run_id')}",
                    f"  时间：{item.get('completed_at_hkt')}",
                    f"  覆盖率：{audit.get('fulfilled') or '未记录'}",
                    f"  URL：成功 {run_log.get('success_urls', 0)}，失败/兜底 {run_log.get('failed_urls', 0)}",
                    f"  飞书日志：{feishu.get('log_sheet_title') or feishu.get('log_sheet_id') or '未写入'} {feishu.get('url') or ''}",
                    f"  Agent运行：{curation.get('agent_run_id') or '未记录'}，发布 {curation.get('accepted', 0)}，缺口 {curation.get('gaps', 0)}",
                ]
            )
        )
    return "\n".join(lines)
