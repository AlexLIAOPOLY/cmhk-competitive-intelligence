from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import crawl_run_registry


class CrawlRunHistoryTests(unittest.TestCase):
    def test_history_scans_authoritative_records_before_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_dir = root / "runs"
            runs_dir.mkdir()
            latest = {
                "crawl_run_id": "latest-refresh",
                "task_kind": "executive-intelligence-refresh",
                "started_at_hkt": "2026-08-19T09:00:00+08:00",
            }
            (root / "index.json").write_text(json.dumps([latest]), encoding="utf-8")
            strategic = [
                {
                    "crawl_run_id": f"strategic-{day}",
                    "task_kind": "strategic-news",
                    "started_at_hkt": f"2026-08-{day:02d}T07:00:00+08:00",
                }
                for day in (17, 18)
            ]
            for item in [latest, *strategic]:
                (runs_dir / f"{item['crawl_run_id']}.json").write_text(json.dumps(item), encoding="utf-8")
            with (
                mock.patch.object(crawl_run_registry, "INDEX_JSON", root / "index.json"),
                mock.patch.object(crawl_run_registry, "RUNS_DIR", runs_dir),
            ):
                history = crawl_run_registry.load_run_history(task_kind="strategic-news")

        self.assertEqual([item["crawl_run_id"] for item in history], ["strategic-18", "strategic-17"])


if __name__ == "__main__":
    unittest.main()
