from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import crawl
from ai_config import load_ai_config, save_ai_config
from crawl_settings import SETTINGS_PATH, load_settings, save_settings
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
        "reportType": "carrier-performance" if "运营商业绩摘要" in path.name else "weekly",
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
    for path in result_files:
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
    latest = max((item["mtime"] for item in outputs), default=None)
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
            "count": len(result_files),
            "ok": ok_count,
            "partial": partial_count,
        },
        "visuals": {
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
        "latestOutputText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest)) if latest else "未生成",
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
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "durationMs": round((time.time() - started) * 1000),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "status": build_status(),
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


def stream_report_generation(handler: BaseHTTPRequestHandler, script_name: str, report_type: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()

    started = time.time()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / script_name)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout:
        for line in proc.stdout:
            write_sse(handler, {"type": "log", "text": line.strip()})
    proc.wait()

    status = build_status()
    audio_result = None
    if proc.returncode == 0 and status.get("outputs"):
        try:
            latest_path = latest_output_path(status, report_type)
            write_sse(handler, {"type": "log", "text": "报告生成完成。开始生成语音摘要..."})
            audio_result = synthesize_report_audio(latest_path, force=True)
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
        if path in {"/schedule", "/schedule.html"}:
            self.serve_file(STATIC_DIR / "schedule.html")
            return
        if path == "/api/status":
            json_response(self, {"ok": True, "status": build_status()})
            return
        if path == "/api/settings":
            json_response(self, {"ok": True, "settings": build_settings_payload()})
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

                if cache_path.exists():
                    try:
                        cached = json.loads(cache_path.read_text(encoding="utf-8"))
                        if cached.get("hash") == current_hash:
                            json_response(self, {"ok": True, "stats": cached["stats"]})
                            return
                    except Exception:
                        pass

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
                    json_response(self, {"ok": True, "stats": {"companies": []}})
                    return

                # Call DeepSeek to clean up the data
                from verification import get_verification_llm
                from langchain_core.messages import SystemMessage, HumanMessage
                llm = get_verification_llm()

                # Build the prompt with all companies' raw data
                raw_dump = {}
                for comp, info in companies_with_data.items():
                    truncated_fields = {}
                    for k, v in info["fields"].items():
                        truncated_fields[k] = v[:2000]
                    raw_dump[comp] = truncated_fields

                prompt = f"""你是一个数据提取专家。下面是从多个网页爬取并初步提取的各企业原始文本片段。
请你从这些文本中提取出**纯数据值**以及其**来源链接**，填入一个结构化的JSON。

规则：
1. 每个字段提取一个对象，包含 "value" (具体的数据数字/值) 和 "source" (来源链接，通常以 SOURCE: 开头)。
2. 如果原文中找不到该字段对应的具体数值，"value" 填 ""（空字符串）。
3. 如果原文中找不到 SOURCE 链接，"source" 填 ""。
4. "value" 里不要填写描述性文字、URL、网页导航文本，只保留核心数据。
5. 如果有多个时期的数据，优先填写最新的。
6. 保持字段名不变。

原始数据：
{json.dumps(raw_dump, ensure_ascii=False, indent=1)}

请输出纯JSON，格式严格如下：
{{
  "公司名1": {{"字段1": {{"value": "数据值", "source": "https://..."}}, "字段2": {{"value": "数据值", "source": ""}}}},
  "公司名2": {{"字段1": {{"value": "数据值", "source": "https://..."}}, "字段2": {{"value": "数据值", "source": ""}}}}
}}

只输出JSON，不要markdown标记。"""

                try:
                    resp = llm.invoke([
                        SystemMessage(content="You are a JSON-only response bot. Only output valid JSON without any markdown."),
                        HumanMessage(content=prompt)
                    ])
                    content = resp.content.strip()
                    if content.startswith("```json"):
                        content = content[7:-3].strip()
                    elif content.startswith("```"):
                        content = content[3:-3].strip()
                    cleaned = json.loads(content)
                except Exception as e:
                    print(f"Dashboard LLM cleanup failed: {e}")
                    # Fallback: use raw data
                    cleaned = {comp: info["fields"] for comp, info in companies_with_data.items()}

                # Save cache (still useful to cache the DeepSeek part so we don't re-run it)
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
                            if src:
                                val = f"{val}\n(来源: {src})"
                            row.append(val)
                        else:
                            row.append(str(val_obj))
                    row.append(str(avg_conf))
                    row.append(reason_str)
                    data_payload.append(row)
                
                # Feishu CLI integration
                import subprocess
                import datetime
                FEISHU_SPREADSHEET_TOKEN = "VLzwsCBZzhMPbztyrLMcAy7Fn4e"
                
                # 1. Create a new sheet with timestamp
                sheet_title = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
                import os
                env = os.environ.copy()
                env["LARK_CLI_NO_PROXY"] = "1"
                
                cmd_create = ["lark-cli", "sheets", "+create-sheet", "--spreadsheet-token", FEISHU_SPREADSHEET_TOKEN, "--title", sheet_title]
                res_create = subprocess.run(cmd_create, capture_output=True, text=True, env=env)
                
                if res_create.returncode != 0:
                    json_response(self, {"ok": False, "error": f"Failed to create Feishu sheet: {res_create.stderr} {res_create.stdout}"}, 500)
                    return
                    
                create_out = json.loads(res_create.stdout)
                sheet_id = create_out.get("data", {}).get("sheet_id")
                
                # Calculate exact range (e.g. A1:Z10)
                def get_col_letter(n):
                    res = ""
                    n += 1
                    while n > 0:
                        n, rem = divmod(n - 1, 26)
                        res = chr(65 + rem) + res
                    return res
                
                matrix = [headers] + data_payload
                range_str = f"A1:{get_col_letter(len(headers)-1)}{len(matrix)}"
                
                # 2. Write data to the new sheet
                cmd_write = [
                    "lark-cli", "sheets", "+write", 
                    "--spreadsheet-token", FEISHU_SPREADSHEET_TOKEN, 
                    "--sheet-id", sheet_id, 
                    "--range", range_str,
                    "--values", json.dumps(matrix, ensure_ascii=False)
                ]
                res_write = subprocess.run(cmd_write, capture_output=True, text=True, env=env)
                
                if res_write.returncode != 0:
                    json_response(self, {"ok": False, "error": f"Failed to write to Feishu sheet: {res_write.stderr} {res_write.stdout}"}, 500)
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
                payload = json.dumps({"type": "log", "text": line.strip()}, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

            proc.wait()

            # Sync to Feishu after full crawl
            if proc.returncode == 0 and (ROOT / "write_payload.json").exists():
                sync_proc = subprocess.run([sys.executable, str(ROOT / "daily_crawl_and_write.py"), "--sync-only"], capture_output=True, text=True)
                if sync_proc.returncode != 0:
                    payload = json.dumps({"type": "log", "text": f"同步飞书失败: {sync_proc.stderr[-500:]}"}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                else:
                    payload = json.dumps({"type": "log", "text": "✅ 飞书表格同步成功！"}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()

            try:
                run_log_path = ROOT / "run_log.json"
                if run_log_path.exists():
                    with run_log_path.open("r", encoding="utf-8") as f:
                        run_log_data = json.load(f)
                    success_items = []
                    failure_items = []
                    for item in run_log_data:
                        url = item.get("url", "")
                        status = item.get("http_status")
                        if status == 200:
                            success_items.append({"url": url, "reason": "OK"})
                        else:
                            reason = item.get("error") or item.get("skip_reason") or f"HTTP {status}"
                            failure_items.append({"url": url, "reason": reason})
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
                "ok": proc.returncode == 0,
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
            stream_report_generation(self, "generate_carrier_performance_report.py", "carrier-performance")
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
                result = synthesize_report_audio(target, force=bool(body.get("force", False)))
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
