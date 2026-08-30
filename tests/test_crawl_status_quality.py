from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web_app


class CrawlStatusQualityTests(unittest.TestCase):
    def test_status_separates_quality_gate_rejection_from_operational_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_files = []
            for index, status_value in enumerate(
                ("ok", "partial", "quality_rejected", "failed"), start=1
            ):
                path = root / f"row_{index}.json"
                path.write_text(
                    json.dumps({"status": status_value}), encoding="utf-8"
                )
                result_files.append(path)
            with (
                mock.patch.object(
                    web_app, "current_crawl_result_files", return_value=result_files
                ),
                mock.patch.object(web_app, "current_report_files", return_value=[]),
                mock.patch.object(web_app, "load_unified_task_index", return_value=[]),
                mock.patch.object(
                    web_app, "build_settings_payload", return_value={"summary": {}}
                ),
                mock.patch.object(web_app, "build_latest_news_funnel", return_value={}),
                mock.patch.object(web_app, "build_today_news_rounds", return_value=[]),
            ):
                quality = web_app.build_status()["visuals"]["quality"]

        self.assertEqual(quality["operationalFailed"], 1)
        self.assertEqual(quality["qualityRejected"], 1)
        self.assertEqual(quality["failed"], 1)
        self.assertEqual(quality["nonPromoted"], 2)


if __name__ == "__main__":
    unittest.main()
