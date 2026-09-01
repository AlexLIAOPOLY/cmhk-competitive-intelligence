import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import daily_crawl_and_write as daily


class DailyCrawlAndWritePayloadTests(unittest.TestCase):
    def test_current_crawl_scope_keeps_rows_beyond_legacy_range(self) -> None:
        with mock.patch.dict(os.environ, {"CMHK_ROWS": "17,47,58"}, clear=False):
            self.assertEqual(
                daily.current_crawl_scope(),
                "指定行（第17行、第47行、第58行）",
            )

    def test_scheduled_rows_rebuild_payload_with_explicit_row_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results = root / "results"
            results.mkdir()
            (results / "row_47.json").write_text(
                json.dumps(
                    {
                        "row": "47",
                        "entities": ["AWS"],
                        "source_urls": ["https://example.com/aws"],
                        "attempted_urls": ["https://example.com/aws"],
                        "raw_records": [],
                        "extracted": {},
                        "missing_fields": [],
                        "entity_missing": [],
                        "entity_results": [],
                        "status": "ok",
                        "fetched_at": "2026-08-26T11:00:00+08:00",
                        "fetched_at_hkt": "2026-08-26T11:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )
            (root / "sources.json").write_text(
                json.dumps(
                    [
                        {"row": "2", "entities": ["HKT", "csl"]},
                        {"row": "47", "entities": ["AWS"]},
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.object(daily, "ROOT", root), mock.patch.dict(
                os.environ, {"CMHK_ROWS": "47"}
            ):
                payload = daily.payload_for_scheduled_rows(
                    {"successful_sources_payload": [["stale"]]}
                )
                validation = daily.validate_payload(payload)

            self.assertEqual(payload["row_numbers"], [47])
            self.assertEqual(len(payload["successful_sources_payload"]), 1)
            self.assertTrue(validation["ok"], validation["problems"])

    def test_regenerate_payload_preserves_authoritative_audit_and_extended_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results_dir = root / "results"
            results_dir.mkdir()
            for row_no in (47, 58):
                (results_dir / f"row_{row_no}.json").write_text(
                    json.dumps(
                        {
                            "row": row_no,
                            "entities": [f"entity-{row_no}"],
                            "source_urls": [f"https://example.com/{row_no}"],
                            "attempted_urls": [f"https://example.com/{row_no}"],
                            "raw_records": [],
                            "extracted": {},
                            "missing_fields": [],
                            "entity_missing": [],
                            "entity_results": [],
                            "status": "ok",
                            "fetched_at": "2026-09-02T03:00:00+08:00",
                            "fetched_at_hkt": "2026-09-02T03:00:00+08:00",
                        }
                    ),
                    encoding="utf-8",
                )
            audit_path = root / "final_audit.md"
            run_log_path = root / "run_log.json"
            audit_path.write_text("authoritative 47-58 audit\n", encoding="utf-8")
            run_log_path.write_text('[{"row":47},{"row":58}]\n', encoding="utf-8")

            with mock.patch.object(daily, "ROOT", root), mock.patch.dict(
                os.environ,
                {"CMHK_ROWS": "47,58"},
                clear=False,
            ), mock.patch.object(daily.crawl, "write_outputs") as write_outputs:
                daily.regenerate_payload_with_log_title("log title", "https://example.com/log")

            payload = json.loads((root / "write_payload.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["row_numbers"], [47, 58])
            self.assertEqual(audit_path.read_text(encoding="utf-8"), "authoritative 47-58 audit\n")
            self.assertEqual(
                json.loads(run_log_path.read_text(encoding="utf-8")),
                [{"row": 47}, {"row": 58}],
            )
            write_outputs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
