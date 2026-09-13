from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from http.server import BaseHTTPRequestHandler

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
        body = app.json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Status polling and stopped browser requests can disconnect while a
            # response is being written.  The request is already over, so avoid
            # turning a harmless client disconnect into a server traceback.
            return

    publish(app, json_response)

    def start_ndjson_response(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        handler.send_header("Cache-Control", "no-store, no-transform")
        handler.send_header("X-Accel-Buffering", "no")
        handler.send_header("Connection", "close")
        handler.end_headers()

    publish(app, start_ndjson_response)

    def write_ndjson_event(handler: BaseHTTPRequestHandler, payload: dict) -> None:
        body = (app.json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        handler.wfile.write(body)
        handler.wfile.flush()

    publish(app, write_ndjson_event)

    def public_intelligence_error_message(exc: Exception) -> str:
        """Return a stable user-facing message without leaking model output or gates."""
        raw = str(exc or "").strip()
        internal_markers = (
            "AI分析", "AI跨库发现", "新洞察", "模型未返回", "内网模型",
            "Expecting value", "JSON", "Traceback", "SyntaxError", "内容：",
            "输入之外的数字", "必须精炼", "门禁",
        )
        if not raw or any(marker in raw for marker in internal_markers):
            return "本次AI结果未通过数据校验，已保留当前版本，请点击重试。"
        return raw[:120]

    publish(app, public_intelligence_error_message)

    def read_request_json(handler: BaseHTTPRequestHandler) -> dict:
        length = int(handler.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = handler.rfile.read(length)
        return app.json.loads(raw.decode("utf-8") or "{}")

    publish(app, read_request_json)

    def write_interactive_sse(handler: BaseHTTPRequestHandler, payload: dict) -> None:
        if not app.write_sse(handler, payload):
            raise app.AIRequestCancelled("浏览器已取消本次 AI 请求")

    publish(app, write_interactive_sse)

    def write_sse(handler: BaseHTTPRequestHandler, payload: dict) -> bool:
        body = app.json.dumps(payload, ensure_ascii=False)
        log_paths = [
            getattr(handler, "_crawl_stream_log_path", None),
            getattr(handler, "_crawl_stream_mirror_path", None),
        ]
        for log_path in dict.fromkeys(path for path in log_paths if path):
            try:
                with app.Path(log_path).open("a", encoding="utf-8") as fh:
                    fh.write(body + "\n")
            except OSError:
                pass
        try:
            handler.wfile.write(f"data: {body}\n\n".encode("utf-8"))
            handler.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The crawl and its post-processing must outlive the browser's SSE
            # connection. A refresh, navigation or laptop sleep must not skip
            # Feishu sync, curation or run registration.
            return False

    publish(app, write_sse)

    def json_object_from_output(output: str) -> dict:
        match = app.re.search(r"\{.*\}\s*$", output, app.re.S)
        if not match:
            return {}
        try:
            value = app.json.loads(match.group(0))
        except app.json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    publish(app, json_object_from_output)

    def append_agent_trace_to_feishu_log(sheet_id: str, run_id: str) -> dict:
        env = app.os.environ.copy()
        proc = app.subprocess.run(
            [
                app.sys.executable,
                str(app.ROOT / "daily_crawl_and_write.py"),
                "--append-agent-trace",
                sheet_id,
                run_id,
            ],
            cwd=str(app.ROOT),
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
            "result": app.json_object_from_output(proc.stdout),
        }

    publish(app, append_agent_trace_to_feishu_log)

    def sse_payload_from_process_line(text: str) -> dict:
        if text.startswith("AGENT_TRACE="):
            try:
                return {"type": "agent_trace", "trace": app.json.loads(text.split("=", 1)[1])}
            except Exception:
                return {"type": "log", "text": text}
        return {"type": "log", "text": text}

    publish(app, sse_payload_from_process_line)
