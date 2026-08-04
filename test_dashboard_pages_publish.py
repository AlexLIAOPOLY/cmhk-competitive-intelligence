from __future__ import annotations

import importlib.util
import re
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
    def test_drilldown_catalog_contains_all_74_sheet_indicators(self):
        script = (
            Path(__file__).resolve().parent
            / "web"
            / "static"
            / "executive-dashboard-drilldown.js"
        ).read_text(encoding="utf-8")
        metric_ids = [int(value) for value in re.findall(r"metric\((\d+),", script)]

        self.assertEqual(metric_ids, list(range(1, 75)))
        self.assertIn('index: "01"', script)
        self.assertIn('index: "02"', script)
        self.assertIn('index: "03"', script)
        self.assertIn('index: "04"', script)

    def test_relationship_model_connects_all_four_carriers_to_metric_evidence(self):
        script = (
            Path(__file__).resolve().parent
            / "web"
            / "static"
            / "executive-dashboard-relations.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(len(re.findall(r"\bstory\(", script)), 8)
        self.assertEqual(len(re.findall(r"\bdriver\(", script)), 24)
        self.assertIn('carriers: ["CMHK", "HKT", "3香港", "SmarTone"]', script)
        for module_key in ("network", "business", "reach", "finance"):
            self.assertRegex(script, rf"\n\s+{module_key}: \[")
        metric_groups = re.findall(
            r"driver\([^\n]*?\[[^\]]*\], \[([^\]]+)\], \[",
            script,
        )
        metric_ids = {
            int(value.strip())
            for group in metric_groups
            for value in group.split(",")
        }
        self.assertTrue(metric_ids)
        self.assertGreaterEqual(min(metric_ids), 1)
        self.assertLessEqual(max(metric_ids), 74)
        self.assertIn(47, metric_ids)
        self.assertIn(73, metric_ids)

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
            drilldown = (first / "executive-dashboard-drilldown.js").read_text(
                encoding="utf-8"
            )
            relations = (first / "executive-dashboard-relations.js").read_text(
                encoding="utf-8"
            )
            self.assertIn('href="./executive-dashboard-demo.css?v=4"', html)
            self.assertIn('src="./assets/executive-dashboard/', html)
            self.assertIn('src="./executive-dashboard-relations.js?v=1"', html)
            self.assertIn('src="./executive-dashboard-drilldown.js?v=5"', html)
            self.assertIn('fetch("./strategic-briefs.json"', script)
            self.assertNotIn("/api/strategic-briefs", script)
            self.assertIn("const KPI_TREE", drilldown)
            self.assertIn('document.body.classList.add("has-drill-fullscreen")', drilldown)
            self.assertIn('overlay.setAttribute("aria-modal", "true")', drilldown)
            self.assertIn("CMHK_DASHBOARD_RELATIONS", relations)
            self.assertTrue((first / ".nojekyll").exists())


if __name__ == "__main__":
    unittest.main()
