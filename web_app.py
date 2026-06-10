from __future__ import annotations

import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import crawl
from ai_config import load_ai_config, save_ai_config
from crawl_settings import SETTINGS_PATH, load_settings, save_settings
from company_metrics import build_company_metrics_payload
from extractors import row_fields
from rag_llm import ask_llm_with_rag, stream_llm_with_rag
from agent import stream_agent
from tts_service import (
    AUDIO_DIR,
    audio_info_for_report,
    delete_audio_for_report,
    rename_audio_for_report,
    synthesize_report_audio,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "web" / "static"
RESULTS_DIR = ROOT / "results"
CURATION_LATEST_PATH = ROOT / "curation_data" / "latest.json"
CURATION_CANDIDATE_FACTS_PATH = ROOT / "curation_data" / "candidate_facts.jsonl"
CURATION_AGENT_TRACE_PATH = ROOT / "curation_data" / "agent_trace.jsonl"
LOCAL_TEMPLATE_PATH = Path("/Users/liaowang/Downloads/模板.docx")
REPO_TEMPLATE_PATH = ROOT / "weekly_report_template.docx"
TEMPLATE_PATH = LOCAL_TEMPLATE_PATH if LOCAL_TEMPLATE_PATH.exists() else REPO_TEMPLATE_PATH
REPORT_FILE_RE = re.compile(r"^\d{1,2}月\d{1,2}日周报(?: \(\d+\))?\.docx$")
REPORT_METADATA_PATH = ROOT / "report_file_metadata.json"
EXCLUDED_REPORT_NAMES = {
    "weekly_report.docx",
    "weekly_report_from_word_template.docx",
    "weekly_report_template.docx",
    "carrier_performance_template.docx",
    "模板.docx",
}
REFERENCE_FILES = {"final_audit.md", "coverage_report.tsv", "run_log.tsv"}


def reference_path(name: str) -> Path | None:
    clean = Path(name).name
    if clean in REFERENCE_FILES:
        return ROOT / clean
    if re.fullmatch(r"row_\d+\.json", clean):
        return RESULTS_DIR / clean
    return None


def settings_rows() -> list[dict]:
    settings = load_settings()
    configured = settings.get("rows", {})
    rows = []
    for source_row in crawl.parse_latest_sheet():
        row_no = str(source_row["row"])
        cfg = configured.get(row_no, {}) if isinstance(configured, dict) else {}
        cfg_entities = [str(item).strip() for item in cfg.get("entities", []) if str(item).strip()]
        cfg_fields = [str(item).strip() for item in cfg.get("fields", []) if str(item).strip()]
        cfg_urls = [str(item).strip() for item in cfg.get("sourceUrls", []) if str(item).strip()]
        available_entities = list(dict.fromkeys([*(source_row.get("entities") or []), *cfg_entities]))
        available_fields = list(dict.fromkeys([*list(row_fields(int(row_no))), *cfg_fields]))
        cfg = configured.get(row_no, {}) if isinstance(configured, dict) else {}
        selected_entities = [item for item in cfg_entities if item in available_entities]
        selected_fields = [item for item in cfg_fields if item in available_fields]
        rows.append(
            {
                "row": row_no,
                "block": source_row.get("block", ""),
                "object": source_row.get("object", ""),
                "package": source_row.get("package", ""),
                "need": source_row.get("need", ""),
                "sources": source_row.get("sources", ""),
                "sourceUrls": cfg_urls,
                "entities": available_entities,
                "fields": available_fields,
                "enabled": bool(cfg.get("enabled", True)),
                "selectedEntities": selected_entities or available_entities,
                "selectedFields": selected_fields or available_fields,
            }
        )
    return rows


def build_settings_payload() -> dict:
    rows = settings_rows()
    enabled = [row for row in rows if row["enabled"]]
    return {
        "path": str(SETTINGS_PATH),
        "exists": SETTINGS_PATH.exists(),
        "rows": rows,
        "summary": {
            "totalRows": len(rows),
            "enabledRows": len(enabled),
            "selectedEntities": sum(len(row["selectedEntities"]) for row in enabled),
            "selectedFields": sum(len(row["selectedFields"]) for row in enabled),
        },
    }


def save_settings_payload(payload: dict) -> dict:
    source_rows = {str(row["row"]): row for row in crawl.parse_latest_sheet()}
    incoming = payload.get("rows", [])
    if not isinstance(incoming, list):
        raise ValueError("rows must be a list")
    next_rows: dict[str, dict] = {}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        row_no = str(item.get("row") or "").strip()
        if row_no not in source_rows:
            continue
        source_entities = list(source_rows[row_no].get("entities") or [])
        source_fields = list(row_fields(int(row_no)))
        incoming_entities = [str(value).strip() for value in item.get("selectedEntities", []) if str(value).strip()]
        incoming_fields = [str(value).strip() for value in item.get("selectedFields", []) if str(value).strip()]
        entities = list(dict.fromkeys(incoming_entities))
        fields = list(dict.fromkeys(incoming_fields))
        source_urls = []
        for value in item.get("sourceUrls", []):
            url = str(value).strip()
            if not url:
                continue
            if not re.match(r"^https?://", url):
                raise ValueError("目标链接必须以 http:// 或 https:// 开头")
            if url not in source_urls:
                source_urls.append(url)
        next_rows[row_no] = {
            "enabled": bool(item.get("enabled", True)),
            "entities": entities or source_entities,
            "fields": fields or source_fields,
            "sourceUrls": source_urls,
        }
    save_settings(next_rows)
    return build_settings_payload()


def save_settings_row_payload(payload: dict) -> dict:
    row_no = str(payload.get("row") or "").strip()
    if not row_no:
        raise ValueError("row is required")
    source_rows = {str(row["row"]): row for row in crawl.parse_latest_sheet()}
    if row_no not in source_rows:
        raise ValueError("row not found")

    settings = load_settings()
    rows = settings.get("rows", {})
    if not isinstance(rows, dict):
        rows = {}

    source_entities = list(source_rows[row_no].get("entities") or [])
    source_fields = list(row_fields(int(row_no)))
    incoming_entities = [str(value).strip() for value in payload.get("selectedEntities", []) if str(value).strip()]
    incoming_fields = [str(value).strip() for value in payload.get("selectedFields", []) if str(value).strip()]
    source_urls = []
    for value in payload.get("sourceUrls", []):
        url = str(value).strip()
        if not url:
            continue
        if not re.match(r"^https?://", url):
            raise ValueError("目标链接必须以 http:// 或 https:// 开头")
        if url not in source_urls:
            source_urls.append(url)

    rows[row_no] = {
        "enabled": bool(payload.get("enabled", True)),
        "entities": list(dict.fromkeys(incoming_entities)) or source_entities,
        "fields": list(dict.fromkeys(incoming_fields)) or source_fields,
        "sourceUrls": source_urls,
    }
    save_settings(rows)
    return build_settings_payload()


def reset_settings() -> dict:
    if SETTINGS_PATH.exists():
        SETTINGS_PATH.unlink()
    return build_settings_payload()


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def load_curation_status() -> dict:
    if not CURATION_LATEST_PATH.exists():
        return {}
    try:
        payload = json.loads(CURATION_LATEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_curation_rejection_visuals() -> dict:
    status = load_curation_status()
    accepted = int(status.get("accepted") or 0)
    rejected = int(status.get("rejected") or 0)
    total = accepted + rejected
    reasons: dict[str, int] = {}
    if CURATION_CANDIDATE_FACTS_PATH.exists():
        try:
            for line in CURATION_CANDIDATE_FACTS_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("decision") != "rejected":
                    continue
                for reason in item.get("reasons") or []:
                    reason_text = str(reason or "").strip()
                    if reason_text:
                        reasons[reason_text] = reasons.get(reason_text, 0) + 1
        except Exception:
            reasons = {}
    top_reasons = sorted(
        [{"label": key, "value": value} for key, value in reasons.items()],
        key=lambda item: item["value"],
        reverse=True,
    )[:6]
    return {
        "accepted": accepted,
        "rejected": rejected,
        "total": total,
        "rejectRate": round((rejected / total) * 100) if total else 0,
        "reasons": top_reasons,
        "runId": status.get("run_id", ""),
        "completedAt": status.get("completed_at", ""),
    }


def build_crawl_result_visuals() -> dict:
    run_log_path = ROOT / "run_log.json"
    if not run_log_path.exists():
        return {
            "success": 0,
            "failed": 0,
            "total": 0,
            "successRate": 0,
            "completedAt": "",
        }
    try:
        rows = json.loads(run_log_path.read_text(encoding="utf-8"))
    except Exception:
        rows = []
    if not isinstance(rows, list):
        rows = []

    success = 0
    failed = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        status = int(item.get("http_status") or 0)
        if 200 <= status < 400:
            success += 1
        else:
            failed += 1
    total = success + failed
    return {
        "success": success,
        "failed": failed,
        "total": total,
        "successRate": round((success / total) * 100) if total else 0,
        "completedAt": time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(run_log_path.stat().st_mtime),
        ),
    }


def load_agent_trace(limit: int = 300) -> list[dict]:
    if not CURATION_AGENT_TRACE_PATH.exists():
        return []
    rows: list[dict] = []
    try:
        lines = CURATION_AGENT_TRACE_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def read_request_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8") or "{}")


def load_report_metadata() -> dict:
    if not REPORT_METADATA_PATH.exists():
        return {}
    try:
        data = json.loads(REPORT_METADATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_report_metadata(data: dict) -> None:
    REPORT_METADATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_report_path(path: Path) -> bool:
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".docx":
        return False
    if path.name in EXCLUDED_REPORT_NAMES:
        return False
    try:
        path.relative_to(ROOT)
    except ValueError:
        return False
    return path.parent == ROOT or ROOT / "archives" in path.parents


def file_info(path: Path, url: str = None) -> dict:
    stat = path.stat()
    rel_path = str(path.relative_to(ROOT))
    metadata = load_report_metadata().get(rel_path, {})
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtimeText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "url": url or f"/outputs/{quote(path.name)}",
        "path_str": rel_path,
        "note": metadata.get("note", "") if isinstance(metadata, dict) else "",
        "reportType": "carrier-performance" if "业绩摘要" in path.name else "weekly",
        "audio": audio_info_for_report(path),
    }


def is_report_file_name(name: str) -> bool:
    return name.endswith(".docx") and "/" not in name and "\\" not in name and name not in EXCLUDED_REPORT_NAMES


def current_report_files() -> list[Path]:
    files = [path for path in ROOT.glob("*.docx") if is_report_path(path)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def report_target_from_rel(path_str: str) -> Path | None:
    if not path_str or path_str.startswith("/") or ".." in Path(path_str).parts:
        return None
    target = ROOT / path_str
    try:
        target.relative_to(ROOT)
    except ValueError:
        return None
    return target if is_report_path(target) else None


def update_report_file(payload: dict) -> dict:
    target = report_target_from_rel(str(payload.get("path") or ""))
    if not target:
        raise ValueError("文件不存在或不允许修改")
    new_name = Path(str(payload.get("name") or "").strip()).name
    if not new_name:
        raise ValueError("文件名不能为空")
    if not new_name.endswith(".docx"):
        new_name += ".docx"
    if not is_report_file_name(new_name):
        raise ValueError("文件名只能是 Word 文档，不能包含路径字符")
    new_note = re.sub(r"\s+", " ", str(payload.get("note") or "")).strip()[:500]
    new_target = target.with_name(new_name)
    if new_target != target and new_target.exists():
        raise ValueError("同名文件已存在")

    metadata = load_report_metadata()
    old_rel = str(target.relative_to(ROOT))
    if new_target != target:
        target.rename(new_target)
        rename_audio_for_report(target, new_target)
        existing = metadata.pop(old_rel, {})
    else:
        existing = metadata.get(old_rel, {})
    new_rel = str(new_target.relative_to(ROOT))
    if not isinstance(existing, dict):
        existing = {}
    existing["note"] = new_note
    existing["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    metadata[new_rel] = existing
    save_report_metadata(metadata)
    return build_status()


def delete_report_files(paths: list[str]) -> dict:
    metadata = load_report_metadata()
    deleted = 0
    for path_str in paths:
        target = report_target_from_rel(str(path_str))
        if not target:
            continue
        rel_path = str(target.relative_to(ROOT))
        target.unlink()
        delete_audio_for_report(target)
        metadata.pop(rel_path, None)
        deleted += 1
    save_report_metadata(metadata)
    return {"deleted": deleted, "status": build_status()}


def build_status() -> dict:
    result_files = sorted(RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    
    outputs = [file_info(path) for path in current_report_files()]
    
    settings = build_settings_payload()
    enabled_rows = {str(r["row"]) for r in settings["rows"] if r.get("enabled")}
    
    ok_count = 0
    partial_count = 0
    failed_count = 0
    block_counts: dict[str, int] = {}
    source_type_counts: dict[str, int] = {}
    jurisdiction_counts: dict[str, int] = {}
    method_counts: dict[str, int] = {}
    entity_counts: dict[str, int] = {}
    field_total = 0
    missing_total = 0
    raw_total = 0
    
    valid_results_count = 0
    for path in result_files:
        row_str = path.stem.split("_")[1] if "_" in path.stem else ""
        if row_str not in enabled_rows:
            continue
        valid_results_count += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "ok":
            ok_count += 1
        elif data.get("status") == "partial":
            partial_count += 1
        else:
            failed_count += 1
        block = str(data.get("need") or data.get("block") or "未分类")
        if "香港" in block:
            block = "香港本地"
        elif any(token in block for token in ["国际", "全球", "欧盟", "国家"]):
            block = "国际监管"
        elif any(token in block for token in ["收入", "ARPU", "EBITDA", "利润", "客户"]):
            block = "经营指标"
        elif any(token in block for token in ["套餐", "资费", "产品", "服务"]):
            block = "产品资费"
        else:
            block = "运营动态"
        block_counts[block] = block_counts.get(block, 0) + 1
        selected_fields = data.get("selected_fields") or []
        missing_fields = data.get("missing_fields") or []
        if isinstance(selected_fields, list):
            field_total += len(selected_fields)
        if isinstance(missing_fields, list):
            missing_total += len(missing_fields)
        for entity in data.get("entities") or []:
            name = str(entity).strip()
            if name:
                entity_counts[name] = entity_counts.get(name, 0) + 1
        for record in data.get("raw_records") or []:
            if not isinstance(record, dict):
                continue
            raw_total += 1
            source_type = str(record.get("source_type") or "unknown")
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
            jurisdiction = str(record.get("jurisdiction") or "unknown")
            jurisdiction_counts[jurisdiction] = jurisdiction_counts.get(jurisdiction, 0) + 1
            method = str(record.get("method") or "unknown")
            method_counts[method] = method_counts.get(method, 0) + 1
            
    # Calculate latest timestamp from crawler output rather than HTML reports
    latest_crawl_time = max((path.stat().st_mtime for path in result_files if path.exists()), default=None)
    settings = build_settings_payload()
    
    # Sort outputs by mtime descending
    outputs.sort(key=lambda x: x["mtime"], reverse=True)
        
    return {
        "template": {
            "path": str(TEMPLATE_PATH),
            "exists": TEMPLATE_PATH.exists(),
            "mtimeText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(TEMPLATE_PATH.stat().st_mtime))
            if TEMPLATE_PATH.exists()
            else "",
        },
        "results": {
            "count": valid_results_count,
            "ok": ok_count,
            "partial": partial_count,
        },
        "visuals": {
            "crawl": build_crawl_result_visuals(),
            "quality": {
                "ok": ok_count,
                "partial": partial_count,
                "failed": failed_count,
                "fieldTotal": field_total,
                "missingFields": missing_total,
                "rawSources": raw_total,
            },
            "blocks": sorted(
                [{"label": key, "value": value} for key, value in block_counts.items()],
                key=lambda item: item["value"],
                reverse=True,
            ),
            "sourceTypes": sorted(
                [{"label": key, "value": value} for key, value in source_type_counts.items()],
                key=lambda item: item["value"],
                reverse=True,
            )[:6],
            "jurisdictions": sorted(
                [{"label": key, "value": value} for key, value in jurisdiction_counts.items()],
                key=lambda item: item["value"],
                reverse=True,
            )[:6],
            "methods": sorted(
                [{"label": key, "value": value} for key, value in method_counts.items()],
                key=lambda item: item["value"],
                reverse=True,
            )[:6],
            "rejection": build_curation_rejection_visuals(),
            "entities": sorted(
                [{"label": key, "value": value} for key, value in entity_counts.items()],
                key=lambda item: item["value"],
                reverse=True,
            )[:8],
            "outputs": [
                {
                    "name": item["name"],
                    "mtime": item["mtime"],
                    "mtimeText": item["mtimeText"],
                    "audio": bool(item.get("audio", {}).get("exists")),
                }
                for item in outputs[:8]
            ],
        },
        "outputs": outputs,
        "settings": settings["summary"],
        "ai": load_ai_config(include_key=False),
        "latestOutputText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_crawl_time)) if latest_crawl_time else "未生成",
    }


def run_crawl() -> dict:
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "crawl.py")],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=1200,
    )
    main_sync = None
    performance_sync = None
    metrics_refresh = None
    agent_trace_sync = None
    if proc.returncode == 0 and (ROOT / "write_payload.json").exists():
        main_sync = subprocess.run(
            [sys.executable, str(ROOT / "daily_crawl_and_write.py"), "--sync-only"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=600,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "update_sources_from_crawl.py")],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        performance_sync = run_carrier_performance_sync()
        metrics_refresh = run_company_metrics_refresh()
        if main_sync.returncode == 0 and metrics_refresh["ok"]:
            sync_result = json_object_from_output(main_sync.stdout)
            log_sheet_id = str(sync_result.get("log_sheet_id") or "")
            agent_run_id = str(load_curation_status().get("run_id") or "")
            if log_sheet_id and agent_run_id:
                agent_trace_sync = append_agent_trace_to_feishu_log(log_sheet_id, agent_run_id)
    return {
        "ok": proc.returncode == 0
        and (main_sync is None or main_sync.returncode == 0)
        and (performance_sync is None or performance_sync["ok"])
        and (metrics_refresh is None or metrics_refresh["ok"])
        and (agent_trace_sync is None or agent_trace_sync["ok"]),
        "returnCode": proc.returncode,
        "durationMs": round((time.time() - started) * 1000),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "mainFeishuSync": None
        if main_sync is None
        else {
            "ok": main_sync.returncode == 0,
            "stdout": main_sync.stdout.strip(),
            "stderr": main_sync.stderr.strip(),
        },
        "carrierPerformanceSync": performance_sync,
        "companyMetricsRefresh": metrics_refresh,
        "agentTraceFeishuSync": agent_trace_sync,
        "status": build_status(),
    }


def run_company_metrics_refresh() -> dict:
    started = time.time()
    # Keep the web-triggered full crawl deterministic: publish one complete
    # curation pass and persist gap tasks, but do not recursively recrawl inside
    # the same HTTP request. Targeted recrawl can still be run from the CLI with
    # --recrawl-gaps after reviewing the generated gaps.
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "run_data_curation.py"),
            "--max-recrawl-rounds",
            "0",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=2400,
    )
    payload = build_company_metrics_payload()
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "durationMs": round((time.time() - started) * 1000),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "summary": payload.get("summary", {}),
    }


def stream_company_metrics_refresh(
    handler: BaseHTTPRequestHandler,
    extra_args: list[str] | None = None,
) -> dict:
    started = time.time()
    command = [
        sys.executable,
        "-u",
        str(ROOT / "run_data_curation.py"),
        "--max-recrawl-rounds",
        "0",
        *(extra_args or []),
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    write_sse(
        handler,
        {
            "type": "agent_trace",
            "trace": {
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "node": "多 Agent 编排器",
                "phase": "tool_call",
                "event_type": "tool_call",
                "message": "启动 LangGraph 多 Agent 数据整理进程。",
                "tool": "run_data_curation.py",
                "input": {
                    "command": command,
                    "workflow": [
                        "证据接收",
                        "来源分类",
                        "事实抽取",
                        "主体校验",
                        "质量审计",
                        "冲突仲裁",
                        "缺口规划",
                        "发布",
                    ],
                },
            },
        },
    )
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    line_queue: queue.Queue[str | None] = queue.Queue()
    output_lines: list[str] = []

    def read_output() -> None:
        if proc.stdout:
            for raw_line in proc.stdout:
                line_queue.put(raw_line.rstrip("\n"))
        line_queue.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    finished_reading = False
    while not finished_reading:
        try:
            line = line_queue.get(timeout=10)
        except queue.Empty:
            elapsed = round(time.time() - started)
            write_sse(
                handler,
                {
                    "type": "agent_trace",
                    "trace": {
                        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "node": "多 Agent 编排器",
                        "phase": "observe",
                        "event_type": "agent",
                        "message": f"Agent 仍在处理，已运行 {elapsed} 秒；正在等待当前工具或模型返回。",
                        "output": {"elapsedSeconds": elapsed, "processId": proc.pid},
                    },
                },
            )
            continue
        if line is None:
            finished_reading = True
            continue
        if not line:
            continue
        output_lines.append(line)
        write_sse(handler, sse_payload_from_process_line(line))

    proc.wait()
    payload = build_company_metrics_payload()
    duration_ms = round((time.time() - started) * 1000)
    write_sse(
        handler,
        {
            "type": "agent_trace",
            "trace": {
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "node": "多 Agent 编排器",
                "phase": "tool_result",
                "event_type": "tool_result",
                "message": "LangGraph 多 Agent 数据整理进程已结束。",
                "tool": "run_data_curation.py",
                "result": {
                    "returnCode": proc.returncode,
                    "durationMs": duration_ms,
                    "summary": payload.get("summary", {}),
                },
            },
        },
    )
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "durationMs": duration_ms,
        "stdout": "\n".join(output_lines),
        "stderr": "",
        "summary": payload.get("summary", {}),
    }


def run_carrier_performance_sync() -> dict:
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "sync_carrier_performance_feishu.py")],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def run_report_generation() -> dict:
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_weekly_report.py")],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
    )
    status = build_status()
    audio_result = None
    if proc.returncode == 0 and status.get("outputs"):
        try:
            latest_path = latest_output_path(status, "weekly")
            audio_result = synthesize_report_audio(latest_path, force=True)
            status = build_status()
        except Exception as exc:
            audio_result = {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "durationMs": round((time.time() - started) * 1000),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "audio": audio_result,
        "status": status,
    }


def run_carrier_performance_generation() -> dict:
    started = time.time()
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_carrier_performance_report.py")],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
    )
    status = build_status()
    audio_result = None
    if proc.returncode == 0 and status.get("outputs"):
        try:
            latest_path = latest_output_path(status, "carrier-performance")
            audio_result = synthesize_report_audio(latest_path, force=True)
            status = build_status()
        except Exception as exc:
            audio_result = {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "durationMs": round((time.time() - started) * 1000),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "audio": audio_result,
        "status": status,
    }


def latest_output_path(status: dict, report_type: str) -> Path:
    output = next((item for item in status.get("outputs", []) if item.get("reportType") == report_type), None)
    if not output:
        raise FileNotFoundError(f"未找到最新输出：{report_type}")
    return ROOT / output["path_str"]


def write_sse(handler: BaseHTTPRequestHandler, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False)
    handler.wfile.write(f"data: {body}\n\n".encode("utf-8"))
    handler.wfile.flush()


def json_object_from_output(output: str) -> dict:
    match = re.search(r"\{.*\}\s*$", output, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def append_agent_trace_to_feishu_log(sheet_id: str, run_id: str) -> dict:
    env = os.environ.copy()
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "daily_crawl_and_write.py"),
            "--append-agent-trace",
            sheet_id,
            run_id,
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
    )
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "result": json_object_from_output(proc.stdout),
    }


def sse_payload_from_process_line(text: str) -> dict:
    if text.startswith("AGENT_TRACE="):
        try:
            return {"type": "agent_trace", "trace": json.loads(text.split("=", 1)[1])}
        except Exception:
            return {"type": "log", "text": text}
    return {"type": "log", "text": text}


def stream_report_generation(
    handler: BaseHTTPRequestHandler,
    script_name: str,
    report_type: str,
    script_args: list[str] | None = None,
) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()

    started = time.time()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / script_name), *(script_args or [])],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    created_path = None
    if proc.stdout:
        for line in proc.stdout:
            text = line.strip()
            write_sse(handler, sse_payload_from_process_line(text))
            if text.startswith("->"):
                candidate = Path(text[2:].strip())
                if candidate.exists() and candidate.name.endswith(".docx") and "template" not in candidate.name:
                    created_path = candidate
    proc.wait()

    status = build_status()
    audio_result = None
    if proc.returncode == 0 and status.get("outputs"):
        try:
            latest_path = created_path if created_path and created_path.exists() else latest_output_path(status, report_type)
            write_sse(handler, {"type": "log", "text": "报告生成完成。开始生成语音摘要..."})
            code = "import sys, json\nfrom pathlib import Path\nfrom tts_service import synthesize_report_audio\ntry:\n    res = synthesize_report_audio(Path(sys.argv[1]), force=sys.argv[2] == 'True')\n    print(json.dumps({'ok': True, 'result': res}))\nexcept Exception as e:\n    print(json.dumps({'ok': False, 'error': str(e)}))"
            proc_audio = subprocess.run([sys.executable, "-c", code, str(latest_path), "True"], capture_output=True, text=True)
            try:
                out = json.loads(proc_audio.stdout)
                if not out.get("ok"):
                    raise Exception(out.get("error"))
                audio_result = out.get("result")
                if not audio_result.get("ok"):
                    raise Exception(audio_result.get("error"))
            except Exception as e:
                raise Exception(f"Audio generation failed: {proc_audio.stderr} | {e}")
            status = build_status()
            write_sse(handler, {"type": "log", "text": "✅ 语音摘要生成完成。"})
        except Exception as exc:
            audio_result = {"ok": False, "error": str(exc)}
            write_sse(handler, {"type": "log", "text": f"❌ 语音摘要生成失败: {exc}"})

    write_sse(
        handler,
        {
            "type": "done",
            "ok": proc.returncode == 0,
            "durationMs": round((time.time() - started) * 1000),
            "audio": audio_result,
            "status": status,
        },
    )


def report_overview() -> str:
    md_path = ROOT / "weekly_report.md"
    if not md_path.exists():
        return "当前还没有生成周报。你可以先点击“生成周报”，系统会按 Word 模板输出正式 Word 周报。"
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    lines = [line.strip("#- 　\t ") for line in text.splitlines() if line.strip()]
    useful = [line for line in lines if line and not line.startswith("来源")][:8]
    status = build_status()
    intro = (
        "这里的周报是“战略内参周报”：把公开信息监测数据按模板整理成正式汇报文件，"
        "主要用于快速查看政策、行业、社会和国际资讯中的重点变化。"
    )
    if not useful:
        return f"{intro} 当前已有输出文件，最近生成时间是 {status['latestOutputText']}。"
    return f"{intro} 当前最近生成时间是 {status['latestOutputText']}。报告开头内容包括：" + "；".join(useful[:5]) + "。"


def output_overview() -> str:
    status = build_status()
    outputs = status.get("outputs", [])
    if not outputs:
        return "当前还没有输出文件。点击“生成周报”后会生成正式 Word 周报。"
    names = "、".join(item["name"] for item in outputs)
    return f"当前可用输出文件有：{names}。这里仅展示正式 Word 周报，用于下载和提交。"


def check_local_action(message: str) -> dict | None:
    text = message.strip()
    lowered = text.lower()
    if any(key in text for key in ["爬虫", "爬取", "抓取", "重新爬", "跑数据", "更新数据"]):
        result = run_crawl()
        if result["ok"]:
            return {
                "content": "已按当前设置重新爬取公开信息。现在可以继续生成周报，输出会按设置范围使用数据。",
                "crawl": result,
            }
        return {
            "content": f"爬取失败，退出码 {result['returnCode']}。错误信息：{result['stderr'] or '无'}",
            "crawl": result,
        }

    if any(key in text for key in ["生成", "输出", "周报", "word", "Word"]) and any(
        key in text for key in ["生成", "重新", "跑", "做"]
    ):
        result = run_report_generation()
        if result["ok"]:
            return {
                "content": "已按 Word 模板重新生成正式 Word 周报。你可以在输出区下载最新文件。",
                "generation": result,
            }
        return {
            "content": f"生成失败，退出码 {result['returnCode']}。错误信息：{result['stderr'] or '无'}",
            "generation": result,
        }

    if any(key in text for key in ["下载", "打开", "输出在哪", "文件在哪", "word在哪", "html在哪"]):
        return {"content": output_overview()}

    if any(key in text for key in ["设置", "范围", "公司", "字段", "数据内容"]) and not any(
        key in text for key in ["建议", "总结", "分析", "为什么"]
    ):
        settings = build_settings_payload()
        summary = settings["summary"]
        return {
            "content": (
                f"当前设置启用 {summary['enabledRows']} / {summary['totalRows']} 个表格行，"
                f"覆盖 {summary['selectedEntities']} 个公司/主体选择、{summary['selectedFields']} 个数据字段。"
                "可以进入“爬取设置”子页面逐项调整，保存后爬虫和周报生成都会按新范围执行。"
            ),
        }

    status = build_status()
    if any(key in text for key in ["状态", "检查", "现在", "文件"]):
        return {
            "content": (
                f"当前已有 {status['results']['count']} 个结果文件，"
                f"ok {status['results']['ok']} 个，partial {status['results']['partial']} 个。"
                f"模板文件{'存在' if status['template']['exists'] else '不存在'}，"
                f"最近输出时间是 {status['latestOutputText']}。"
            ),
        }

    if "模板" in text or "格式" in text:
        return {
            "content": (
                "当前生成流程会优先读取本地上传的模板，若无则使用库里的默认模板 weekly_report_template.docx，"
                "保留封面、目录位置、页眉页脚和图片资源，只替换目录与正文段落文字。"
            ),
        }

    if "openai" in lowered or "api" in lowered or "ai" in lowered:
        return {
            "content": (
                "这个助手已接入 OpenAI Responses API 的调用代码，并会先对本地周报、爬取结果和审计文件做 RAG 检索。"
                "当前运行环境需要设置 OPENAI_API_KEY 后才能真正调用模型。"
            ),
        }

    return None


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WeeklyReportUI/1.0"

    @staticmethod
    def download_disposition(path: Path) -> str:
        encoded_name = quote(path.name, safe="")
        fallback_name = f"weekly-report{path.suffix.lower() or '.docx'}"
        return f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}"

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_head(STATIC_DIR / "index.html")
            return
        if parsed.path in {"/settings", "/settings.html"}:
            self.serve_head(STATIC_DIR / "settings.html")
            return
        if parsed.path in {"/company-data", "/company-data.html"}:
            self.serve_head(STATIC_DIR / "company-data.html")
            return
        if parsed.path.startswith("/static/"):
            self.serve_head(STATIC_DIR / parsed.path.removeprefix("/static/"))
            return
        if parsed.path.startswith("/outputs/"):
            name = Path(unquote(parsed.path.removeprefix("/outputs/"))).name
            target = ROOT / name
            if is_report_path(target):
                self.serve_head(target, download=True)
                return
        if parsed.path.startswith("/audio/"):
            name = Path(unquote(parsed.path.removeprefix("/audio/"))).name
            target = AUDIO_DIR / name
            if target.exists() and target.suffix.lower() in {".wav", ".mp3"}:
                self.serve_head(target)
                return
        if parsed.path.startswith("/references/"):
            target = reference_path(unquote(parsed.path.removeprefix("/references/")))
            if target and target.exists():
                self.serve_head(target)
                return
        if parsed.path.startswith("/archives/"):
            target = ROOT / unquote(parsed.path.lstrip("/"))
            if is_report_path(target):
                self.serve_head(target, download=True)
                return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html")
            return
        if path in {"/settings", "/settings.html"}:
            self.serve_file(STATIC_DIR / "settings.html")
            return
        if path in {"/company-data", "/company-data.html"}:
            self.serve_file(STATIC_DIR / "company-data.html")
            return
        if path in {"/schedule", "/schedule.html"}:
            self.serve_file(STATIC_DIR / "schedule.html")
            return
        if path == "/api/status":
            json_response(self, {"ok": True, "status": build_status()})
            return
        if path == "/api/settings":
            json_response(self, {"ok": True, "settings": build_settings_payload()})
            return
        if path == "/api/company-metrics":
            json_response(
                self,
                {
                    "ok": True,
                    "data": build_company_metrics_payload(),
                    "curation": load_curation_status(),
                },
            )
            return
        if path == "/api/data-curation":
            json_response(self, {"ok": True, "curation": load_curation_status()})
            return
        if path == "/api/agent-trace":
            query = parse_qs(parsed.query)
            try:
                limit = max(1, min(1000, int(query.get("limit", ["300"])[0])))
            except Exception:
                limit = 300
            json_response(self, {"ok": True, "trace": load_agent_trace(limit=limit)})
            return
        if path == "/api/dashboard":
            try:
                # Check cache first
                cache_path = ROOT / "results" / "_dashboard_cache.json"
                results_dir = ROOT / "results"
                # Build a hash of all row files to detect changes
                import hashlib
                row_files = sorted(results_dir.glob("row_*.json")) if results_dir.exists() else []
                hash_input = ""
                for rf in row_files:
                    hash_input += rf.name + str(rf.stat().st_mtime)
                current_hash = hashlib.md5(hash_input.encode()).hexdigest()

                # Collect raw data per company
                companies_raw = {}
                for f in row_files:
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        for entity_result in data.get("entity_results", []):
                            entity = entity_result.get("entity")
                            if not entity:
                                continue
                            if entity_result.get("status") == "no_extraction":
                                continue
                            if entity not in companies_raw:
                                companies_raw[entity] = {"fields": {}, "confidences": [], "reasons": []}
                            extracted = entity_result.get("extracted", {})
                            for k, v in extracted.items():
                                if v and isinstance(v, str):
                                    if k not in companies_raw[entity]["fields"]:
                                        companies_raw[entity]["fields"][k] = v
                                    else:
                                        companies_raw[entity]["fields"][k] += " | " + v
                            conf = entity_result.get("confidence_score", 0.0)
                            companies_raw[entity]["confidences"].append(conf)
                            reason = entity_result.get("verification_reason", "")
                            if reason:
                                companies_raw[entity]["reasons"].append(reason)
                    except Exception:
                        pass

                # Filter companies that have data
                companies_with_data = {k: v for k, v in companies_raw.items() if v["fields"]}
                if not companies_with_data:
                    json_response(self, {"ok": False, "error": "暂无提取的数据，请先运行爬取。"}, 400)
                    return

                # Cache check
                cleaned = None
                if cache_path.exists():
                    try:
                        cached = json.loads(cache_path.read_text(encoding="utf-8"))
                        if cached.get("hash") == current_hash:
                            cleaned = cached["stats"]
                    except Exception:
                        pass

                if not cleaned:
                    # Call DeepSeek to clean up the data
                    from verification import get_verification_llm
                    from langchain_core.messages import SystemMessage, HumanMessage
                    llm = get_verification_llm()
    
                    # Build batches for concurrent LLM extraction
                    import concurrent.futures

                    def process_batch(batch_dict):
                        # Ensure fields are truncated
                        raw_dump = {}
                        for comp, info in batch_dict.items():
                            raw_dump[comp] = {k: v[:2000] for k, v in info["fields"].items()}

                        prompt = f"""你是一个数据提取专家。下面是从网页提取的各企业原始文本。
请你从这些文本中严格提取出**最新的单一纯数字/数值**（可带单位，如“5.2亿”、“30%”），以及**来源链接**，填入JSON。

规则：
1. 每个字段提取一个对象，包含 "value" (纯数字/数值) 和 "source" (来源链接，通常以 SOURCE: 开头)。
2. "value" 绝对不要包含长篇描述，也不要有多个数值并列。**只能提取最新的一个核心数字**（如：12.5亿港元、450万）。如果遇到大段文字说明或多个数字，只摘出一个最相关的核心数字，其余一律丢弃。
3. 如果原文找不到具体数值，"value" 填 ""。找不到 SOURCE 链接，"source" 填 ""。
4. 保持字段名不变，输出严格的JSON格式。

原始数据：
{json.dumps(raw_dump, ensure_ascii=False)}

输出格式示例：
{{
  "公司A": {{"字段1": {{"value": "5.2亿", "source": "https://..."}}, "字段2": {{"value": "", "source": ""}}}}
}}
"""
                        try:
                            # Re-instantiate LLM for safety in threads
                            from verification import get_verification_llm
                            from langchain_core.messages import SystemMessage, HumanMessage
                            batch_llm = get_verification_llm()
                            resp = batch_llm.invoke([
                                SystemMessage(content="You are a JSON-only response bot. Only output valid JSON without any markdown."),
                                HumanMessage(content=prompt)
                            ])
                            content = resp.content.strip()
                            if content.startswith("```json"):
                                content = content[7:-3].strip()
                            elif content.startswith("```"):
                                content = content[3:-3].strip()
                            return json.loads(content)
                        except Exception as e:
                            print("Batch error:", e)
                            return {}

                    items = list(companies_with_data.items())
                    batch_size = 5
                    batches = [dict(items[i:i + batch_size]) for i in range(0, len(items), batch_size)]
                    
                    cleaned = {}
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        results = list(executor.map(process_batch, batches))
                    
                    for res in results:
                        cleaned.update(res)
                    
                    # Fill missing companies with raw fields as fallback just in case
                    for comp in companies_with_data:
                        if comp not in cleaned:
                            cleaned[comp] = companies_with_data[comp]["fields"]

                    # Save cache
                    try:
                        cache_path.write_text(json.dumps({"hash": current_hash, "stats": cleaned}, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass

                # Build headers and data payload for Feishu
                # 1. Collect all unique fields
                field_set = set()
                for comp, fields in cleaned.items():
                    for k in fields.keys():
                        field_set.add(k)
                field_list = sorted(list(field_set))
                
                headers = ["公司"] + field_list + ["置信度", "校验原因"]
                
                data_payload = []
                for comp, info in companies_with_data.items():
                    avg_conf = sum(info["confidences"]) / len(info["confidences"]) if info["confidences"] else 0
                    reason_str = " | ".join(info["reasons"][:2])
                    comp_data = cleaned.get(comp, {})
                    
                    row = [comp]
                    for f in field_list:
                        val_obj = comp_data.get(f, {})
                        if isinstance(val_obj, dict):
                            val = val_obj.get("value", "")
                            src = val_obj.get("source", "")
                            if val:
                                if src:
                                    if src.startswith("SOURCE: "):
                                        src = src[8:].strip()
                                    val = f"{val}\n(来源: {src})"
                            else:
                                val = ""
                            row.append(val)
                        else:
                            row.append(str(val_obj))
                    row.append(str(avg_conf))
                    row.append(reason_str)
                    data_payload.append(row)
                
                # Feishu CLI integration
                import datetime
                FEISHU_SPREADSHEET_TOKEN = "VLzwsCBZzhMPbztyrLMcAy7Fn4e"
                
                # 1. Create a new sheet with timestamp
                sheet_title = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
                import os
                env = os.environ.copy()
                
                cmd_create = ["lark-cli", "sheets", "+create-sheet", "--spreadsheet-token", FEISHU_SPREADSHEET_TOKEN, "--title", sheet_title]
                res_create = subprocess.run(cmd_create, capture_output=True, text=True, env=env)
                
                if res_create.returncode != 0:
                    json_response(self, {"ok": False, "error": f"Failed to create Feishu sheet: {res_create.stderr} {res_create.stdout}"}, 500)
                    return
                    
                create_out = json.loads(res_create.stdout)
                sheet_id = create_out.get("data", {}).get("sheet_id")
                
                # Expand columns to make sure it fits our headers
                cmd_add_col = [
                    "lark-cli", "sheets", "+add-dimension",
                    "--spreadsheet-token", FEISHU_SPREADSHEET_TOKEN,
                    "--sheet-id", sheet_id,
                    "--dimension", "COLUMNS",
                    "--length", str(len(headers))
                ]
                res_add_col = subprocess.run(cmd_add_col, capture_output=True, text=True, env=env)
                if res_add_col.returncode != 0:
                    json_response(self, {"ok": False, "error": f"Failed to add columns: {res_add_col.stderr} {res_add_col.stdout}"}, 500)
                    return
                
                # Calculate exact range (e.g. A1:Z10)
                def get_col_letter(n):
                    res = ""
                    n += 1
                    while n > 0:
                        n, rem = divmod(n - 1, 26)
                        res = chr(65 + rem) + res
                    return res
                
                matrix = [headers] + data_payload
                
                # 2. Write data to the new sheet (chunked if > 90 columns)
                # Feishu API limits writes to 100 columns per append/write
                chunk_size = 90
                num_chunks = (len(headers) + chunk_size - 1) // chunk_size
                
                for i in range(num_chunks):
                    start_col = i * chunk_size
                    end_col = min((i + 1) * chunk_size, len(headers))
                    
                    chunk = [row[start_col:end_col] for row in matrix]
                    
                    # Calculate range e.g. A1:Z10 or AA1:BZ10
                    range_str = f"{sheet_id}!{get_col_letter(start_col)}1:{get_col_letter(end_col-1)}{len(matrix)}"
                    
                    cmd_write = [
                        "lark-cli", "sheets", "+write", 
                        "--spreadsheet-token", FEISHU_SPREADSHEET_TOKEN, 
                        "--sheet-id", sheet_id, 
                        "--range", range_str,
                        "--values", json.dumps(chunk, ensure_ascii=False)
                    ]
                    res_write = subprocess.run(cmd_write, capture_output=True, text=True, env=env)
                    
                    if res_write.returncode != 0:
                        json_response(self, {"ok": False, "error": f"Failed to write chunk to Feishu sheet: {res_write.stderr} {res_write.stdout}"}, 500)
                        return
                
                # Return the URL to the frontend
                spreadsheet_url = f"https://cmhk-try.feishu.cn/sheets/{FEISHU_SPREADSHEET_TOKEN}?sheet={sheet_id}"
                json_response(self, {"ok": True, "url": spreadsheet_url})
            except Exception as exc:
                import traceback
                traceback.print_exc()
                json_response(self, {"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/schedule":
            try:
                rows = crawl.parse_latest_sheet()
                for r in rows:
                    res_path = ROOT / "results" / f"row_{r['row']}.json"
                    if res_path.exists():
                        try:
                            data = json.loads(res_path.read_text(encoding="utf-8"))
                            r["last_fetched"] = data.get("fetched_at_hkt")
                        except Exception:
                            pass
                json_response(self, {"ok": True, "rows": rows})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/ai-config":
            json_response(self, {"ok": True, "config": load_ai_config(include_key=False)})
            return
        if path.startswith("/outputs/"):
            name = Path(unquote(path.removeprefix("/outputs/"))).name
            target = ROOT / name
            if not is_report_path(target):
                json_response(self, {"ok": False, "error": "file not allowed"}, 404)
                return
            self.serve_file(target, download=True)
            return
        if path.startswith("/audio/"):
            name = Path(unquote(path.removeprefix("/audio/"))).name
            target = AUDIO_DIR / name
            if not target.exists() or target.suffix.lower() not in {".wav", ".mp3"} or target.parent != AUDIO_DIR:
                json_response(self, {"ok": False, "error": "audio not found"}, 404)
                return
            self.serve_file(target)
            return
        if path.startswith("/references/"):
            target = reference_path(unquote(path.removeprefix("/references/")))
            if not target:
                json_response(self, {"ok": False, "error": "reference not allowed"}, 404)
                return
            self.serve_file(target)
            return
        if path.startswith("/static/"):
            self.serve_file(STATIC_DIR / path.removeprefix("/static/"))
            return
        json_response(self, {"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/crawl":
            json_response(self, run_crawl())
            return
        if parsed.path == "/api/crawl-stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            
            started = time.time()
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "crawl.py")],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                payload = json.dumps(sse_payload_from_process_line(line.strip()), ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

            proc.wait()
            log_sheet_id = ""
            log_sheet_title = ""
            crawl_failed_count = 0

            # Sync to Feishu after full crawl
            if proc.returncode == 0 and (ROOT / "write_payload.json").exists():
                sync_proc = subprocess.run([sys.executable, str(ROOT / "daily_crawl_and_write.py"), "--sync-only"], capture_output=True, text=True)
                if sync_proc.returncode != 0:
                    payload = json.dumps({"type": "log", "text": f"同步飞书失败: {sync_proc.stderr[-500:]}"}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    proc.returncode = sync_proc.returncode
                else:
                    sync_result = json_object_from_output(sync_proc.stdout)
                    log_sheet_id = str(sync_result.get("log_sheet_id") or "")
                    log_sheet_title = str(sync_result.get("log_sheet_title") or "")
                    payload = json.dumps(
                        {
                            "type": "log",
                            "text": "✅ 飞书表格同步成功！"
                            + (f" 日志页：{log_sheet_title}" if log_sheet_title else ""),
                        },
                        ensure_ascii=False,
                    )
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()

                # Update supplementary JSON configs with newly extracted data
                update_proc = subprocess.run([sys.executable, str(ROOT / "update_sources_from_crawl.py")], capture_output=True, text=True)
                if update_proc.returncode != 0:
                    payload = json.dumps({"type": "log", "text": f"⚠️ 业绩补充桥接更新异常: {update_proc.stderr[-200:]}"}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                else:
                    if update_proc.stdout.strip():
                        payload = json.dumps({"type": "log", "text": f"ℹ️ 业绩补充配置同步：{update_proc.stdout.strip()}"}, ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()

                performance_sync = run_carrier_performance_sync()
                if performance_sync["ok"]:
                    payload = json.dumps(
                        {"type": "log", "text": "✅ 运营商业绩摘要补充页已同步并通过五类字段校验。"},
                        ensure_ascii=False,
                    )
                else:
                    payload = json.dumps(
                        {
                            "type": "log",
                            "text": "运营商业绩摘要补充页同步失败: "
                            + (performance_sync["stderr"] or performance_sync["stdout"])[-500:],
                        },
                        ensure_ascii=False,
                    )
                    proc.returncode = proc.returncode or performance_sync["returnCode"]
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

                payload = json.dumps(
                    {
                        "type": "log",
                        "text": "开始多 Agent 数据整理：来源分类、事实抽取、主体校验、质量审计、冲突仲裁和缺口补爬...",
                    },
                    ensure_ascii=False,
                )
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                metrics_refresh = stream_company_metrics_refresh(self)
                if metrics_refresh["ok"]:
                    summary = metrics_refresh["summary"]
                    payload = json.dumps(
                        {
                            "type": "log",
                            "text": (
                                "✅ 公司指标页已更新："
                                f"{summary.get('companies', 0)} 家公司、"
                                f"{summary.get('metrics', 0)} 类指标、"
                                f"{summary.get('records', 0)} 条通过校验的记录。"
                            ),
                        },
                        ensure_ascii=False,
                    )
                else:
                    payload = json.dumps(
                        {
                            "type": "log",
                            "text": "❌ 公司指标页 AI 整理失败: "
                            + (metrics_refresh["stderr"] or metrics_refresh["stdout"])[-500:],
                        },
                        ensure_ascii=False,
                    )
                    proc.returncode = proc.returncode or metrics_refresh["returnCode"]
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

                if metrics_refresh["ok"] and log_sheet_id:
                    latest_curation = load_curation_status()
                    agent_run_id = str(latest_curation.get("run_id") or "")
                    write_sse(
                        self,
                        {
                            "type": "agent_trace",
                            "trace": {
                                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                                "run_id": agent_run_id,
                                "node": "飞书审计日志",
                                "phase": "tool_call",
                                "event_type": "tool_call",
                                "message": f"将 Agent 处理流程和结果写入飞书日志页 {log_sheet_title or log_sheet_id}。",
                                "tool": "daily_crawl_and_write.py --append-agent-trace",
                                "input": {
                                    "sheetId": log_sheet_id,
                                    "sheetTitle": log_sheet_title,
                                    "runId": agent_run_id,
                                },
                            },
                        },
                    )
                    trace_sync = append_agent_trace_to_feishu_log(log_sheet_id, agent_run_id)
                    trace_result = trace_sync.get("result") or {}
                    write_sse(
                        self,
                        {
                            "type": "agent_trace",
                            "trace": {
                                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                                "run_id": agent_run_id,
                                "node": "飞书审计日志",
                                "phase": "tool_result",
                                "event_type": "tool_result",
                                "message": (
                                    f"Agent 流程已写入飞书，共 {trace_result.get('trace_rows', 0)} 条并完成回读校验。"
                                    if trace_sync["ok"]
                                    else "Agent 流程写入飞书失败。"
                                ),
                                "tool": "daily_crawl_and_write.py --append-agent-trace",
                                "result": {
                                    "ok": trace_sync["ok"],
                                    "sheetId": log_sheet_id,
                                    "sheetTitle": log_sheet_title,
                                    "range": trace_result.get("range", ""),
                                    "traceRows": trace_result.get("trace_rows", 0),
                                    "error": (trace_sync["stderr"] or trace_sync["stdout"])[-500:]
                                    if not trace_sync["ok"]
                                    else "",
                                },
                            },
                        },
                    )
                    if not trace_sync["ok"]:
                        proc.returncode = proc.returncode or trace_sync["returnCode"]
                elif metrics_refresh["ok"]:
                    write_sse(
                        self,
                        {
                            "type": "log",
                            "text": "⚠️ Agent 已完成，但未取得本次飞书日志页 ID，未能追加 Agent 审计区块。",
                        },
                    )

            try:
                run_log_path = ROOT / "run_log.json"
                if run_log_path.exists():
                    with run_log_path.open("r", encoding="utf-8") as f:
                        run_log_data = json.load(f)
                    success_items = []
                    failure_items = []
                    for item in run_log_data:
                        url = item.get("url", "")
                        status = int(item.get("http_status") or 0)
                        if 200 <= status < 400:
                            success_items.append({"url": url, "reason": "OK"})
                        else:
                            reason = item.get("error") or item.get("skip_reason") or f"HTTP {status}"
                            failure_items.append({"url": url, "reason": reason})
                    crawl_failed_count = len(failure_items)
                    summary_payload = json.dumps({
                        "type": "crawl_summary",
                        "success": success_items,
                        "failed": failure_items,
                        "total": len(run_log_data)
                    }, ensure_ascii=False)
                    self.wfile.write(f"data: {summary_payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except Exception as e:
                pass

            duration_ms = round((time.time() - started) * 1000)
            payload = json.dumps({
                "type": "done",
                "ok": proc.returncode == 0 and crawl_failed_count == 0,
                "durationMs": duration_ms,
                "status": build_status()
            }, ensure_ascii=False)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()
            return
        if parsed.path == "/api/generate-stream":
            stream_report_generation(self, "generate_weekly_report.py", "weekly")
            return

        if parsed.path == "/api/generate-carrier-performance-stream":
            stream_report_generation(
                self,
                "generate_carrier_performance_report.py",
                "carrier-performance",
            )
            return

        if parsed.path == "/api/generate":
            json_response(self, run_report_generation())
            return

        if parsed.path == "/api/generate-carrier-performance":
            json_response(self, run_carrier_performance_generation())
            return

        if parsed.path == "/api/audio/generate":
            try:
                body = read_request_json(self)
                target = report_target_from_rel(str(body.get("path") or ""))
                if not target:
                    raise ValueError("文件不存在或不允许生成音频")
                force_str = str(bool(body.get("force", False)))
                code = "import sys, json\nfrom pathlib import Path\nfrom tts_service import synthesize_report_audio\ntry:\n    res = synthesize_report_audio(Path(sys.argv[1]), force=sys.argv[2] == 'True')\n    print(json.dumps({'ok': True, 'result': res}))\nexcept Exception as e:\n    print(json.dumps({'ok': False, 'error': str(e)}))"
                proc_audio = subprocess.run([sys.executable, "-c", code, str(target), force_str], capture_output=True, text=True)
                try:
                    out = json.loads(proc_audio.stdout)
                    if not out.get("ok"):
                        raise Exception(out.get("error"))
                    result = out.get("result")
                except Exception as e:
                    raise Exception(f"Audio generation failed: {proc_audio.stderr} | {e}")
                json_response(self, {"ok": bool(result.get("ok")), "result": result, "status": build_status()}, 200 if result.get("ok") else 500)
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/report-file":
            try:
                json_response(self, {"ok": True, "status": update_report_file(read_request_json(self))})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/delete-files":
            try:
                body = read_request_json(self)
                result = delete_report_files(body.get("paths", []))
                json_response(self, {"ok": True, **result})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/settings":
            try:
                json_response(self, {"ok": True, "settings": save_settings_payload(read_request_json(self))})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/settings/row":
            try:
                json_response(self, {"ok": True, "settings": save_settings_row_payload(read_request_json(self))})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/schedule":
            try:
                payload = read_request_json(self)
                rows = payload.get("rows", [])
                freq_map = {str(r["row"]): r.get("frequency", "") for r in rows}
                values = [[freq_map.get(str(idx), "")] for idx in range(2, 35)]
                
                import daily_crawl_and_write
                headers = daily_crawl_and_write.current_headers()
                freq_col = "H"
                for name in ["每隔多长时间收集一轮", "收集频率", "排期频率"]:
                    try:
                        freq_col = daily_crawl_and_write.col_to_a1(headers.index(name) + 1)
                        break
                    except ValueError:
                        pass

                cmd = [
                    crawl.LARK_CLI, "sheets", "+write",
                    "--spreadsheet-token", crawl.SPREADSHEET_TOKEN,
                    "--range", f"{crawl.MAIN_SHEET_ID}!{freq_col}2:{freq_col}34",
                    "--values", json.dumps(values, ensure_ascii=False)
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if proc.returncode != 0:
                    json_response(self, {"ok": False, "error": f"Feishu API failed: {proc.stderr}"}, 500)
                    return
                json_response(self, {"ok": True, "feishu_result": json.loads(proc.stdout)})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/crawl-row":
            try:
                payload = read_request_json(self)
                row_id = str(payload.get("row"))
                if not row_id.isdigit():
                    raise ValueError("Invalid row ID")
                env = os.environ.copy()
                env["CMHK_ROWS"] = row_id
                proc = subprocess.run([sys.executable, str(ROOT / "crawl.py")], env=env, capture_output=True, text=True)
                if proc.returncode != 0:
                    json_response(self, {"ok": False, "error": f"Crawl failed: {proc.stderr[-500:]}"}, 500)
                    return
                # Trigger Feishu sync after crawling
                result_text = ""
                if (ROOT / "write_payload.json").exists():
                    sync_proc = subprocess.run([sys.executable, str(ROOT / "daily_crawl_and_write.py"), "--sync-only"], capture_output=True, text=True)
                    if sync_proc.returncode != 0:
                        json_response(self, {"ok": False, "error": f"Sync failed: {sync_proc.stderr[-500:]}"}, 500)
                        return
                    try:
                        payload_data = json.loads((ROOT / "write_payload.json").read_text(encoding="utf-8"))
                        ij_payload = payload_data.get("results_payload") or payload_data.get("I2:K34", [])
                        if len(ij_payload) == 1:
                            i_cell = ij_payload[0][0]
                        else:
                            row_idx = int(row_id) - 2
                            i_cell = ij_payload[row_idx][0]
                        result_text = i_cell
                    except Exception as e:
                        result_text = f"读取爬虫结果失败: {e}"
                json_response(self, {"ok": True, "result_text": result_text})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/settings/reset":
            json_response(self, {"ok": True, "settings": reset_settings()})
            return
        if parsed.path == "/api/ai-config":
            try:
                json_response(self, {"ok": True, "config": save_ai_config(read_request_json(self)), "status": build_status()})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/ai-test":
            result = ask_llm_with_rag("请用一句话确认 RAG 助手已连接，并说明你会基于哪些本地文件回答。")
            json_response(self, {"ok": bool(result.get("ok")), "result": result, "status": build_status()})
            return
        if parsed.path == "/api/chat":
            json_response(self, {"ok": False, "error": "deprecated API, use stream"}, 404)
            return
        if parsed.path == "/api/chat-stream":
            payload = read_request_json(self)
            message = str(payload.get("message") or "")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            
            action = check_local_action(message)
            if action:
                body = json.dumps({"type": "delta", "text": action["content"]}, ensure_ascii=False)
                self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                if "crawl" in action:
                    body = json.dumps({"type": "action_result", "crawl": action["crawl"]}, ensure_ascii=False)
                    self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                if "generation" in action:
                    body = json.dumps({"type": "action_result", "generation": action["generation"]}, ensure_ascii=False)
                    self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                body = json.dumps({"type": "done"}, ensure_ascii=False)
                self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                self.wfile.flush()
            else:
                for event in stream_agent(message):
                    body = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                    self.wfile.flush()
            return
        json_response(self, {"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")

    def serve_file(self, path: Path, download: bool = False) -> None:
        if not path.exists() or not path.is_file():
            json_response(self, {"ok": False, "error": "file not found"}, 404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", self.download_disposition(path))
        self.end_headers()
        self.wfile.write(body)

    def serve_head(self, path: Path, download: bool = False) -> None:
        if not path.exists() or not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        if download:
            self.send_header("Content-Disposition", self.download_disposition(path))
        self.end_headers()


def main() -> None:
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Weekly report UI: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
