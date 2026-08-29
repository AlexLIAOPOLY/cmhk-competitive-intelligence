from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cmhk.data_releases import (
    publish_quarterly_release,
    publish_quarterly_release_task,
    resolve_release_request,
    sha256_file,
    validate_quarterly_dataset,
)


FIELDS = [
    "subject",
    "period",
    "grain",
    "metric_key",
    "period_end",
    "value",
    "unit",
    "verification_status",
    "verification_count",
    "official_source_url",
]


class DataReleaseTests(unittest.TestCase):
    def _dataset(self, root: Path, *, value: str = "2846") -> Path:
        dataset = root / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
        dataset.mkdir(parents=True)
        csv_path = dataset / "quarterly_metrics.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(
                {
                    "subject": "3HK / Hutchison",
                    "period": "H1 2026",
                    "grain": "half_year",
                    "metric_key": "revenue",
                    "period_end": "2026-06-30",
                    "value": value,
                    "unit": "millions HKD",
                    "verification_status": "official_match",
                    "verification_count": "2",
                    "official_source_url": "https://example.test/h1-2026.pdf",
                }
            )
        (dataset / "README.md").write_text("official evidence\n", encoding="utf-8")
        (dataset / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "quarterly_competitor_metrics_2026-06-18",
                    "row_count": 1,
                    "entrypoints": ["README.md", "quarterly_metrics.csv"],
                }
            ),
            encoding="utf-8",
        )
        global_operators = dataset.parent / "global_top5_operators_2016_2025"
        global_operators.mkdir()
        global_entrypoints = [
            "annual_metrics.csv",
            "annual_metrics.json",
            "sources.json",
            "quality_audit.json",
            "conflicts_and_scope_breaks.csv",
            "conflicts_and_scope_breaks.json",
        ]
        for name in global_entrypoints:
            content = (
                "operator_id,period,grain,metric_key,official_value,unit,verification_status\n"
                "reliance_jio,FY2018,annual,mobile_arpu,137,INR_per_user_month,official_single_source\n"
                if name == "annual_metrics.csv"
                else "{}\n"
                if name.endswith(".json")
                else "value\n"
            )
            (global_operators / name).write_text(content, encoding="utf-8")
        (global_operators / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "global_top5_operators_2016_2025",
                    "row_count": 1,
                    "entrypoints": global_entrypoints,
                    "quality": {
                        "status": "backlog_open",
                        "available_value_rows": 1,
                        "source_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        related = dataset.parent / "local_hk_operator_operating_metrics_2016_2025"
        related.mkdir()
        related_entrypoints = [
            "annual_metrics.csv",
            "quality_audit.json",
            "full_metric_audit_2016_2025.csv",
            "full_metric_audit_2016_2025.json",
        ]
        for name in related_entrypoints:
            (related / name).write_text("{}\n" if name.endswith(".json") else "value\n", encoding="utf-8")
        (related / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "local_hk_operator_operating_metrics_2016_2025",
                    "row_count": 4,
                    "entrypoints": related_entrypoints,
                    "quality": {
                        "status": "pass",
                        "available_value_rows": 2,
                        "source_count": 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        tariffs = dataset.parent / "competitor_product_tariffs"
        tariffs.mkdir()
        tariff_entrypoints = [
            "product_tariffs_agent_context.md",
            "product_tariffs_formal_agent_records.csv",
            "product_tariffs_source_gaps_agent_records.csv",
            "product_tariffs_followup_agent_records.csv",
        ]
        for name in tariff_entrypoints:
            content = (
                "record_class,月费_HKD\nformal_product_tariff,98\n"
                if name.endswith("formal_agent_records.csv")
                else "value\n"
            )
            (tariffs / name).write_text(content, encoding="utf-8")
        (tariffs / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "competitor_product_tariffs",
                    "entrypoints": [
                        *tariff_entrypoints,
                        "agent_knowledge/hkt_product_tariffs/summary.md",
                    ],
                    "quality": {"status": "virtual_combined_entry"},
                }
            ),
            encoding="utf-8",
        )
        return dataset

    def test_publish_is_content_addressed_idempotent_and_keeps_old_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = self._dataset(root)
            releases = root / "releases-output"

            first = publish_quarterly_release(dataset, releases, project_root=root)
            second = publish_quarterly_release(dataset, releases, project_root=root)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["release_id"], second["release_id"])
            old_release = Path(first["release_dir"])
            self.assertTrue(old_release.is_dir())

            with (dataset / "quarterly_metrics.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["value"] = "2900"
            with (dataset / "quarterly_metrics.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            third = publish_quarterly_release(dataset, releases, project_root=root)

            self.assertNotEqual(first["release_id"], third["release_id"])
            self.assertTrue(old_release.is_dir())
            current = json.loads((releases / "current.json").read_text())
            self.assertEqual(current["release_id"], third["release_id"])
            self.assertEqual(
                current["release_manifest_sha256"],
                sha256_file(Path(third["release_dir"]) / "release.json"),
            )

    def test_validation_rejects_manifest_drift_and_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = self._dataset(root)
            manifest = json.loads((dataset / "manifest.json").read_text())
            manifest["row_count"] = 2
            (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "row count mismatch"):
                validate_quarterly_dataset(dataset)

            manifest["row_count"] = 2
            (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with (dataset / "quarterly_metrics.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            with (dataset / "quarterly_metrics.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows([rows[0], rows[0]])
            with self.assertRaisesRegex(RuntimeError, "duplicate natural key"):
                validate_quarterly_dataset(dataset)

    def test_http_file_resolution_is_read_only_and_traversal_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "current.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                resolve_release_request(
                    root, "/data-releases/quarterly/current.json"
                ),
                (root / "current.json").resolve(),
            )
            self.assertIsNone(
                resolve_release_request(
                    root, "/data-releases/quarterly/../../private.json"
                )
            )
            self.assertIsNone(
                resolve_release_request(root, "/data-releases/quarterly/missing.json")
            )

    def test_publish_emits_detailed_quality_hash_file_and_pointer_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events: list[tuple[str, str, str, dict]] = []

            result = publish_quarterly_release(
                self._dataset(root),
                root / "releases-output",
                project_root=root,
                event_sink=lambda phase, message, level, data: events.append(
                    (phase, message, level, data)
                ),
            )

        phases = [event[0] for event in events]
        self.assertEqual(phases[:3], ["读取输入", "数据门禁", "内容指纹"])
        self.assertIn("文件固化", phases)
        self.assertEqual(phases[-2:], ["不可变版本", "发布指针"])
        quality = next(event[3] for event in events if event[0] == "数据门禁")
        self.assertEqual(quality["row_count"], 1)
        self.assertEqual(quality["data_as_of"], "2026-06-30")
        pointer = events[-1][3]
        self.assertEqual(pointer["release_id"], result["release_id"])
        self.assertEqual(len(pointer["release_manifest_sha256"]), 64)

    def test_publish_bundles_governed_local_hk_operating_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = publish_quarterly_release(
                self._dataset(root), root / "releases-output", project_root=root
            )

            release = json.loads(
                (Path(result["release_dir"]) / "release.json").read_text()
            )

        self.assertEqual(release["bundle_contract_version"], 4)
        self.assertEqual(
            [item["id"] for item in release["related_packages"]],
            [
                "global_top5_operators_2016_2025",
                "local_hk_operator_operating_metrics_2016_2025",
                "competitor_product_tariffs",
            ],
        )
        paths = {item["path"] for item in release["artifacts"]}
        self.assertIn(
            "related_packages/global_top5_operators_2016_2025/annual_metrics.csv",
            paths,
        )
        self.assertIn(
            "related_packages/local_hk_operator_operating_metrics_2016_2025/annual_metrics.csv",
            paths,
        )
        self.assertIn(
            "related_packages/competitor_product_tariffs/product_tariffs_formal_agent_records.csv",
            paths,
        )

    def test_publish_task_is_independent_and_links_parent_by_release_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events: list[dict] = []
            with (
                mock.patch(
                    "cmhk.crawl.run_registry.start_crawl_run",
                    return_value={
                        "crawl_run_id": "release-task-1",
                        "stream_log_path": str(root / "release-task-1.jsonl"),
                    },
                ) as start,
                mock.patch("cmhk.crawl.run_registry.heartbeat_crawl_run"),
                mock.patch(
                    "cmhk.crawl.run_registry.append_crawl_run_event",
                    side_effect=lambda _path, payload: events.append(payload),
                ),
                mock.patch(
                    "cmhk.crawl.run_registry.finalize_operational_crawl_run"
                ) as finalize,
            ):
                result = publish_quarterly_release_task(
                    self._dataset(root),
                    root / "releases-output",
                    project_root=root,
                    parent_crawl_run_id="refresh-parent-1",
                    trigger_kind="四库刷新",
                )

        self.assertEqual(result["task_id"], "crawl:release-task-1")
        self.assertEqual(start.call_args.kwargs["task_kind"], "quarterly-data-release")
        self.assertEqual(
            start.call_args.kwargs["parent_crawl_run_id"], "refresh-parent-1"
        )
        self.assertEqual(events[0]["phase"], "任务启动")
        self.assertEqual(events[-1]["phase"], "任务完成")
        self.assertEqual(events[-1]["data"]["release_id"], result["release_id"])
        self.assertTrue(finalize.call_args.kwargs["ok"])


if __name__ == "__main__":
    unittest.main()
