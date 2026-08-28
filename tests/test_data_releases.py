from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from cmhk.data_releases import (
    publish_quarterly_release,
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


if __name__ == "__main__":
    unittest.main()
