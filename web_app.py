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
from urllib.parse import unquote, urlparse

import crawl
from ai_config import load_ai_config, save_ai_config
from crawl_settings import SETTINGS_PATH, load_settings, save_settings
from extractors import row_fields
from rag_llm import ask_llm_with_rag, stream_llm_with_rag


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "web" / "static"
RESULTS_DIR = ROOT / "results"
LOCAL_TEMPLATE_PATH = Path("/Users/liaowang/Downloads/模板.docx")
REPO_TEMPLATE_PATH = ROOT / "weekly_report_template.docx"
TEMPLATE_PATH = LOCAL_TEMPLATE_PATH if LOCAL_TEMPLATE_PATH.exists() else REPO_TEMPLATE_PATH
OUTPUT_FILES = [
    "weekly_report.docx",
    "weekly_report_from_word_template.docx",
    "weekly_report.html",
    "weekly_report.md",
]
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
        available_entities = list(source_row.get("entities") or [])
        available_fields = list(row_fields(int(row_no)))
        cfg = configured.get(row_no, {}) if isinstance(configured, dict) else {}
        selected_entities = [item for item in cfg.get("entities", []) if item in available_entities]
        selected_fields = [item for item in cfg.get("fields", []) if item in available_fields]
        rows.append(
            {
                "row": row_no,
                "block": source_row.get("block", ""),
                "object": source_row.get("object", ""),
                "package": source_row.get("package", ""),
                "need": source_row.get("need", ""),
                "sources": source_row.get("sources", ""),
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
        available_entities = list(source_rows[row_no].get("entities") or [])
        available_fields = list(row_fields(int(row_no)))
        entity_set = set(available_entities)
        field_set = set(available_fields)
        entities = [value for value in item.get("selectedEntities", []) if value in entity_set]
        fields = [value for value in item.get("selectedFields", []) if value in field_set]
        next_rows[row_no] = {
            "enabled": bool(item.get("enabled", True)),
            "entities": entities or available_entities,
            "fields": fields or available_fields,
        }
    save_settings(next_rows)
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


def file_info(path: Path, url: str = None) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtimeText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "url": url or f"/outputs/{path.name}",
        "path_str": str(path.relative_to(ROOT)),
    }


def build_status() -> dict:
    result_files = sorted(RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    outputs = [file_info(ROOT / name) for name in OUTPUT_FILES if (ROOT / name).exists()]
    ok_count = 0
    partial_count = 0
    for path in result_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "ok":
            ok_count += 1
        elif data.get("status") == "partial":
            partial_count += 1
    latest = max((item["mtime"] for item in outputs), default=None)
    settings = build_settings_payload()
    
    archive_dir = ROOT / "archives"
    if archive_dir.exists():
        for sub in archive_dir.iterdir():
            if sub.is_dir():
                for p in sub.glob("*"):
                    if p.is_file():
                        info = file_info(p, url=f"/archives/{sub.name}/{p.name}")
                        info["is_archive"] = True
                        info["archive_batch"] = sub.name
                        outputs.append(info)
                        
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
    return {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "durationMs": round((time.time() - started) * 1000),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "status": status,
    }


def report_overview() -> str:
    md_path = ROOT / "weekly_report.md"
    if not md_path.exists():
        return "当前还没有生成周报。你可以先点击“生成周报”，系统会按 Word 模板输出 Word、HTML 和 Markdown 文件。"
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
        return "当前还没有输出文件。点击“生成周报”后会生成 Word、HTML 和 Markdown。"
    names = "、".join(item["name"] for item in outputs)
    return f"当前可用输出文件有：{names}。Word 文件用于正式提交，HTML 用于浏览器预览，Markdown 用于快速查看或二次编辑。"


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
                "content": "已按 Word 模板重新生成周报。右侧输出区可以打开或下载 Word 文件，也可以看 HTML 预览。",
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
                "当前生成流程会直接读取 /Users/liaowang/Downloads/模板.docx，"
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
            if name in OUTPUT_FILES and (ROOT / name).exists():
                self.serve_head(ROOT / name, download=name.endswith(".docx"))
                return
        if parsed.path.startswith("/references/"):
            target = reference_path(unquote(parsed.path.removeprefix("/references/")))
            if target and target.exists():
                self.serve_head(target)
                return
        if parsed.path.startswith("/archives/"):
            target = ROOT / unquote(parsed.path.lstrip("/"))
            if target.exists() and target.is_file():
                self.serve_head(target, download=target.name.endswith(".docx"))
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
        if path == "/api/status":
            json_response(self, {"ok": True, "status": build_status()})
            return
        if path == "/api/settings":
            json_response(self, {"ok": True, "settings": build_settings_payload()})
            return
        if path == "/api/ai-config":
            json_response(self, {"ok": True, "config": load_ai_config(include_key=False)})
            return
        if path.startswith("/outputs/"):
            name = Path(unquote(path.removeprefix("/outputs/"))).name
            if name not in OUTPUT_FILES:
                json_response(self, {"ok": False, "error": "file not allowed"}, 404)
                return
            self.serve_file(ROOT / name, download=name.endswith(".docx"))
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
        if parsed.path == "/api/generate":
            json_response(self, run_report_generation())
            return
        if parsed.path == "/api/delete-files":
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = json.loads(self.rfile.read(length))
                paths_to_delete = body.get("paths", [])
                deleted = 0
                for rel_path in paths_to_delete:
                    if ".." in rel_path or rel_path.startswith("/"):
                        continue
                    target = ROOT / rel_path
                    if target.is_relative_to(ROOT) and target.exists() and target.is_file():
                        target.unlink()
                        deleted += 1
                json_response(self, {"ok": True, "deleted": deleted, "status": build_status()})
            else:
                json_response(self, {"ok": False, "error": "Empty body"}, 400)
            return
        if parsed.path == "/api/settings":
            try:
                json_response(self, {"ok": True, "settings": save_settings_payload(read_request_json(self))})
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
                for event in stream_llm_with_rag(message):
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
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
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
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()


def main() -> None:
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print(f"Weekly report UI: http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
