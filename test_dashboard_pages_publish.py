from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parent
    / "scripts"
    / "publish_executive_dashboard_pages.py"
)
SPEC = importlib.util.spec_from_file_location("dashboard_pages_publish", SCRIPT_PATH)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class DashboardPagesPublishTests(unittest.TestCase):
    def test_build_site_is_static_sanitized_and_stable(self):
        payload = {
            "ok": True,
            "generated_at": "2026-07-29T10:00:00+08:00",
            "items": [
                {
                    "id": "NEWS-1",
                    "title": "公开新闻",
                    "summary": "公开摘要",
                    "category": "行业动态",
                    "source_url": "https://example.com/news",
                    "published_at": "2026-07-29",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            publisher,
            "_public_news_payload",
            return_value=payload,
        ):
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            first_version, first_payload = publisher._build_site(first)
            second_version, second_payload = publisher._build_site(second)

            self.assertEqual(first_version, second_version)
            self.assertEqual(
                first_payload["site_version"],
                second_payload["site_version"],
            )
            html = (first / "index.html").read_text(encoding="utf-8")
            script = (first / "executive-dashboard-demo.js").read_text(
                encoding="utf-8"
            )
            self.assertIn('href="./executive-dashboard-demo.css"', html)
            self.assertIn('src="./assets/executive-dashboard/', html)
            self.assertIn('fetch("./strategic-briefs.json"', script)
            self.assertNotIn("/api/strategic-briefs", script)
            self.assertTrue((first / ".nojekyll").exists())


if __name__ == "__main__":
    unittest.main()
