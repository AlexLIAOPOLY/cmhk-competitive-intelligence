"""Behavioral contracts for the modular backend and its legacy public facade."""

import http.client
import inspect
import io
import json
import pickle
import tempfile
import threading
import types
import typing
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import web_app
from cmhk.web import http_read, http_resources, http_write, lifecycle, reports


def isolated_context():
    app = types.ModuleType("web_app_test_context")
    app.__dict__.update({k: v for k, v in vars(web_app).items() if not k.startswith("__")})
    return app


class WebAppModuleContracts(unittest.TestCase):
    def test_contexts_do_not_share_rebound_paths(self):
        first, second = isolated_context(), isolated_context()
        reports.bind(first)
        reports.bind(second)
        first.ROOT, second.ROOT = Path("/first"), Path("/second")
        self.assertEqual(first.reference_path("weekly_report.md"), Path("/first/weekly_report.md"))
        self.assertEqual(second.reference_path("weekly_report.md"), Path("/second/weekly_report.md"))
        first.ROOT = Path("/changed")
        self.assertEqual(first.reference_path("weekly_report.md"), Path("/changed/weekly_report.md"))

    def test_existing_facade_patch_reaches_same_domain_callers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.txt"
            path.write_bytes(b"original")
            with patch.object(web_app, "decode_text_bytes", return_value="replacement") as decode:
                self.assertEqual(web_app.read_display_text(path), "replacement")
                decode.assert_called_once_with(b"original")

    def test_exported_callable_keeps_signature_types_and_pickle_identity(self):
        self.assertEqual(str(inspect.signature(web_app.read_display_text)), "(path: 'Path') -> 'str'")
        self.assertEqual(typing.get_type_hints(web_app.read_display_text), {"path": Path, "return": str})
        self.assertIs(pickle.loads(pickle.dumps(web_app.read_display_text)), web_app.read_display_text)
        self.assertTrue(inspect.isgeneratorfunction(web_app.stream_agent_with_approvals))

    def test_stream_lifecycle_keeps_logging_completion_and_transport_result(self):
        app = isolated_context()
        lifecycle.bind(app)
        app.observe_task_progress = Mock()
        app.append_general_task_log = Mock()
        app.finish_general_task_run = Mock()
        app._ORIGINAL_WRITE_SSE = Mock(return_value=False)
        handler = types.SimpleNamespace(_general_task_run_id="report-1")
        payload = {"type": "done", "ok": False, "error": "cancelled"}
        self.assertFalse(app.write_sse(handler, payload))
        app.observe_task_progress.assert_called_once_with(handler, payload)
        app.finish_general_task_run.assert_called_once_with("report-1", False, "cancelled")
        app._ORIGINAL_WRITE_SSE.assert_called_once_with(handler, payload)
        self.assertTrue(handler._general_task_finished)

    def test_real_http_dispatch_keeps_auth_health_files_and_head(self):
        app = isolated_context()
        auth = Mock()
        auth.handle.return_value = False
        auth.authorize_page.return_value = True
        auth.authorize_resource.return_value = True
        auth.authorize_api.return_value = True
        app.AUTH = auth
        app.build_status = Mock(return_value={"sentinel": "current-context"})
        for domain in (http_read, http_write, http_resources):
            domain.bind(app)
        class Handler(app.ReadRoutes, app.WriteRoutes, app.ResourceResponses, web_app.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            app.STATIC_DIR = Path(directory)
            body = "<html>正常运行</html>".encode()
            (app.STATIC_DIR / "index.html").write_bytes(body)
            server = web_app.AppHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            def request(method, path):
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                try:
                    connection.request(method, path)
                    response = connection.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    connection.close()
            try:
                status, _, data = request("GET", "/api/health")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["status"], {"sentinel": "current-context"})
                self.assertEqual(request("GET", "/")[2], body)
                status, headers, data = request("HEAD", "/static/index.html")
                self.assertEqual((status, data), (200, b""))
                self.assertEqual(int(headers["Content-Length"]), len(body))
                def deny(handler, path, method):
                    app.json_response(handler, {"ok": False}, 403)
                    return False
                auth.authorize_api.side_effect = deny
                app.build_status.reset_mock()
                self.assertEqual(request("GET", "/api/health")[0], 403)
                self.assertEqual(request("POST", "/api/generate")[0], 403)
                app.build_status.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)

    def test_resource_mixin_preserves_partial_audio_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "report.mp3"
            audio.write_bytes(b"0123456789")
            handler = Mock()
            handler.headers = {"Range": "bytes=3-6"}
            handler.wfile = io.BytesIO()
            handler.date_time_string.return_value = "Sun, 13 Sep 2026 00:00:00 GMT"
            web_app.AppHandler.serve_audio(handler, audio)
            handler.send_response.assert_called_once_with(206)
            self.assertEqual(handler.wfile.getvalue(), b"3456")
            handler.send_header.assert_any_call("Content-Range", "bytes 3-6/10")


if __name__ == "__main__":
    unittest.main()
