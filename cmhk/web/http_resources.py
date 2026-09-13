from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from pathlib import Path



def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    class ResourceResponses:
        @staticmethod
        def download_disposition(path: Path) -> str:
            encoded_name = app.quote(app.report_display_name(path.name), safe="")
            fallback_name = f"weekly-report{path.suffix.lower() or '.docx'}"
            return f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}"

        def log_message(self, fmt: str, *args) -> None:
            print(f"[web] {self.address_string()} - {fmt % args}")

        def authorize_data_release(self) -> bool:
            """Allow loopback by default and bearer-authenticated server consumers."""

            configured = app.os.environ.get("CMHK_DATA_RELEASE_TOKEN", "").strip()
            if configured:
                authorization = str(self.headers.get("Authorization") or "")
                supplied = (
                    authorization.removeprefix("Bearer ").strip()
                    if authorization.startswith("Bearer ")
                    else ""
                )
                if app.secrets.compare_digest(supplied, configured):
                    return True
                app.json_response(self, {"ok": False, "error": "release authorization failed"}, 401)
                return False
            if app.is_loopback_client(str(self.client_address[0])):
                return True
            app.json_response(
                self,
                {"ok": False, "error": "remote release access requires CMHK_DATA_RELEASE_TOKEN"},
                403,
            )
            return False

        def serve_file(self, path: Path, download: bool = False) -> None:
            if not path.exists() or not path.is_file():
                app.json_response(self, {"ok": False, "error": "file not found"}, 404)
                return
            body = path.read_bytes()
            content_type = app.mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or path.suffix.lower() in {".md", ".tsv", ".json"}:
                content_type = f"{content_type}; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if path.suffix.lower() == ".html":
                self.send_header("Cache-Control", "no-store")
            elif path.suffix.lower() in {".css", ".js"}:
                self.send_header("Cache-Control", "no-cache, must-revalidate")
            if download:
                self.send_header("Content-Disposition", self.download_disposition(path))
            self.end_headers()
            self.wfile.write(body)

        def serve_audio(self, path: Path, head_only: bool = False) -> None:
            """Serve report audio with byte ranges so browsers can seek while paused."""
            if not path.is_file():
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            with path.open("rb") as stream:
                stat = app.os.fstat(stream.fileno())
                size = stat.st_size
                etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
                modified = self.date_time_string(stat.st_mtime)
                start, end = 0, size - 1
                status = 200
                requested = "" if head_only else self.headers.get("Range", "").strip()
                if_range = self.headers.get("If-Range", "")
                if if_range and if_range not in {etag, modified}:
                    requested = ""
                # Browsers request one span. Ignore malformed/multipart ranges and
                # return the complete representation instead of inventing a span.
                match = app.re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", requested)
                if match and any(match.groups()):
                    first, last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                    else:
                        start = max(0, size - int(last))
                    if start >= size or start > end:
                        self.send_response(416)
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                length = max(0, end - start + 1)
                self.send_response(status)
                self.send_header("Content-Type", app.mimetypes.guess_type(str(path))[0] or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", modified)
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head_only:
                    return
                stream.seek(start)
                try:
                    while length:
                        chunk = stream.read(min(length, 64 * 1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        length -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    # A new seek cancels the previous browser request.
                    return

        def serve_reference(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                app.json_response(self, {"ok": False, "error": "file not found"}, 404)
                return
            suffix = path.suffix.lower()
            if suffix in {".md", ".tsv", ".json", ".txt", ".docx", ".pdf"}:
                raw = app.read_display_text(path)
                title = path.name
                raw_ref = app.quote(path.relative_to(app.ROOT).as_posix(), safe="/")
                body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{app.escape(title)}</title>
  <style>
    body {{ margin: 0; padding: 24px; background: #f8fafc; color: #172033; font: 14px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .bar {{ position: sticky; top: 0; margin: -24px -24px 18px; padding: 14px 24px; background: rgba(248, 250, 252, 0.96); border-bottom: 1px solid #d8e3ee; backdrop-filter: blur(8px); }}
    h1 {{ margin: 0 0 4px; font-size: 18px; }}
    a {{ color: #0067b1; font-weight: 700; text-decoration: none; }}
    pre {{ margin: 0; padding: 18px; overflow: auto; white-space: pre-wrap; word-break: break-word; background: #fff; border: 1px solid #d8e3ee; border-radius: 8px; box-shadow: 0 1px 4px rgba(15, 29, 46, 0.06); font: 13px/1.75 ui-monospace, SFMono-Regular, Menlo, Consolas, "PingFang SC", "Microsoft YaHei", monospace; }}
  </style>
</head>
<body>
  <div class="bar">
    <h1>{app.escape(title)}</h1>
    <a href="/references-raw/{raw_ref}" target="_blank" rel="noopener noreferrer">打开原始文件</a>
  </div>
  <pre>{app.escape(raw)}</pre>
</body>
</html>""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.serve_file(path)

        def serve_reference_head(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            if path.suffix.lower() in {".md", ".tsv", ".json", ".txt", ".docx", ".pdf"}:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                return
            self.serve_head(path)

        def serve_head(self, path: Path, download: bool = False) -> None:
            if not path.exists() or not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            content_type = app.mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or path.suffix.lower() in {".md", ".tsv", ".json"}:
                content_type = f"{content_type}; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(path.stat().st_size))
            if path.suffix.lower() == ".html":
                self.send_header("Cache-Control", "no-store")
            elif path.suffix.lower() in {".css", ".js"}:
                self.send_header("Cache-Control", "no-cache, must-revalidate")
            if download:
                self.send_header("Content-Disposition", self.download_disposition(path))
            self.end_headers()

    app.ResourceResponses = ResourceResponses
