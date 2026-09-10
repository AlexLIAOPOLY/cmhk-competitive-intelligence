import http.client
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from web_app import AppHandler


class AudioRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.audio = Path(cls.tmp.name) / "report.mp3"
        cls.body = bytes(range(256)) * 1024
        cls.audio.write_bytes(cls.body)

        class Handler(AppHandler):
            def do_GET(self):
                self.serve_audio(cls.audio)

            def do_HEAD(self):
                self.serve_audio(cls.audio, head_only=True)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()
        cls.tmp.cleanup()

    def request(self, headers=None, method="GET"):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, "/audio/report.mp3", headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_full_audio_and_head_advertise_seek_support(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, self.body)
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Type"], "audio/mpeg")
        status, headers, body = self.request({"Range": "bytes=100-199"}, "HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Length"], str(len(self.body)))
        self.assertEqual(body, b"")

    def test_seek_returns_exact_requested_bytes(self):
        for requested, start, end in [
            ("bytes=100-199", 100, 199),
            ("bytes=120000-", 120000, len(self.body) - 1),
            ("bytes=-100", len(self.body) - 100, len(self.body) - 1),
            ("bytes=250000-999999", 250000, len(self.body) - 1),
        ]:
            with self.subTest(requested=requested):
                status, headers, body = self.request({"Range": requested})
                self.assertEqual(status, 206)
                self.assertEqual(body, self.body[start:end + 1])
                self.assertEqual(headers["Content-Length"], str(len(body)))
                self.assertEqual(headers["Content-Range"], f"bytes {start}-{end}/{len(self.body)}")

    def test_unsatisfiable_ranges_return_empty_416(self):
        for requested in ["bytes=999999-", "bytes=100-99", "bytes=-0"]:
            with self.subTest(requested=requested):
                status, headers, body = self.request({"Range": requested})
                self.assertEqual(status, 416)
                self.assertEqual(headers["Content-Range"], f"bytes */{len(self.body)}")
                self.assertEqual(body, b"")

    def test_multipart_and_malformed_ranges_fall_back_to_full_audio(self):
        for requested in ["bytes=0-10,20-30", "bytes=abc", "items=0-1"]:
            with self.subTest(requested=requested):
                status, headers, body = self.request({"Range": requested})
                self.assertEqual(status, 200)
                self.assertNotIn("Content-Range", headers)
                self.assertEqual(body, self.body)

    def test_if_range_cannot_mix_different_audio_versions(self):
        _, headers, _ = self.request(method="HEAD")
        for validator in [headers["ETag"], headers["Last-Modified"]]:
            status, _, body = self.request({"Range": "bytes=100-199", "If-Range": validator})
            self.assertEqual(status, 206)
            self.assertEqual(body, self.body[100:200])
        status, _, body = self.request({"Range": "bytes=100-199", "If-Range": '"old-audio"'})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.body)


if __name__ == "__main__":
    unittest.main()
