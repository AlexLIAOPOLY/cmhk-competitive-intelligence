from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from executive_intelligence_pipeline import _merge_international_candidate


class InternationalCandidateManifestMergeTests(unittest.TestCase):
    def test_preserves_existing_sidecar_entrypoints_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stage = root / "stage"
            target = root / "target"
            stage.mkdir()
            target.mkdir()
            (stage / "quarterly_metrics.json").write_text(
                json.dumps({"rows": [{"subject": "HKT", "period": "2025", "metric_key": "revenue"}]}),
                encoding="utf-8",
            )
            (target / "quarterly_metrics.json").write_text(
                json.dumps({"rows": []}), encoding="utf-8"
            )
            (stage / "manifest.json").write_text(
                json.dumps(
                    {
                        "entrypoints": ["quarterly_metrics.csv"],
                        "quality": {"status": "pass", "notes": []},
                    }
                ),
                encoding="utf-8",
            )
            (target / "annual_metrics_china_mobile.csv").write_text(
                "year,value\n2025,1\n", encoding="utf-8"
            )
            (target / "manifest.json").write_text(
                json.dumps(
                    {
                        "entrypoints": ["annual_metrics_china_mobile.csv"],
                        "quality": {"status": "pass", "source_count": 7},
                    }
                ),
                encoding="utf-8",
            )

            _merge_international_candidate(stage, target)

            manifest = json.loads((stage / "manifest.json").read_text())
            self.assertEqual(
                manifest["entrypoints"],
                ["quarterly_metrics.csv", "annual_metrics_china_mobile.csv"],
            )
            self.assertEqual(manifest["quality"]["source_count"], 7)
            self.assertEqual(
                (stage / "annual_metrics_china_mobile.csv").read_text(),
                "year,value\n2025,1\n",
            )


if __name__ == "__main__":
    unittest.main()
