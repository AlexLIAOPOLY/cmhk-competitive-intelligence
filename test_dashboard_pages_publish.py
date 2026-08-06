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
        later_payload = {
            **payload,
            "generated_at": "2026-07-29T10:05:00+08:00",
        }
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            publisher,
            "_public_news_payload",
            side_effect=[payload, later_payload],
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
            self.assertIn('href="./executive-dashboard-demo.css?v=8"', html)
            self.assertIn(
                'href="./executive-responsive-hardening.css?v=1"',
                html,
            )
            self.assertIn('src="./assets/executive-dashboard/', html)
            self.assertNotIn("executive-dashboard-relations.js", html)
            self.assertNotIn("executive-dashboard-drilldown.js", html)
            self.assertIn('data-network-view="fixed"', html)
            self.assertIn('data-finance-view="cash"', html)
            self.assertIn('fetch("./strategic-briefs.json"', script)
            self.assertNotIn("/api/strategic-briefs", script)
            self.assertFalse((first / "executive-dashboard-relations.js").exists())
            self.assertFalse((first / "executive-dashboard-drilldown.js").exists())
            css = (first / "executive-dashboard-demo.css").read_text(
                encoding="utf-8"
            )
            self.assertIn(".panel-tabs button.is-active", css)
            self.assertTrue((first / "executive-responsive-hardening.css").exists())
            intelligence_html = (first / "intelligence" / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                'href="./responsive-layout-hardening.css?v=1"',
                intelligence_html,
            )
            self.assertTrue(
                (first / "intelligence" / "responsive-layout-hardening.css").exists()
            )
            self.assertTrue((first / ".nojekyll").exists())

    def test_build_site_preserves_static_intelligence_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "snapshot"
            snapshot.mkdir()
            (snapshot / "index.html").write_text(
                "<title>四库竞争情报驾驶舱</title>",
                encoding="utf-8",
            )
            payload = {"ok": True, "generated_at": "", "items": []}
            with mock.patch.object(publisher, "INTELLIGENCE_STATIC_DIR", snapshot), mock.patch.object(
                publisher,
                "_public_news_payload",
                return_value=payload,
            ):
                destination = Path(temp) / "site"
                publisher._build_site(destination)

            self.assertEqual(
                (destination / "intelligence" / "index.html").read_text(encoding="utf-8"),
                "<title>四库竞争情报驾驶舱</title>",
            )

    def test_static_intelligence_snapshot_keeps_frontend_interactions_without_api(self):
        static_dir = Path(__file__).resolve().parent / "web" / "static" / "intelligence-public"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        script = (static_dir / "intelligence.js").read_text(encoding="utf-8")

        self.assertIn('<script src="./intelligence.js"></script>', html)
        self.assertIn('id="intelligenceDrawerBackdrop"', html)
        self.assertIn('data-intelligence-focus', script)
        self.assertIn('function selectFocus', script)
        self.assertIn('function selectEntity', script)
        self.assertIn('function openDrawer', script)
        self.assertIn('strategy-ticker-track', script)
        self.assertNotIn("/api/", script)
        self.assertNotRegex(script, r"127\.0\.0\.1|localhost|10\.0\.|192\.168\.")


if __name__ == "__main__":
    unittest.main()
