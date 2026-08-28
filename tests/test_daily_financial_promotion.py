from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmhk.data.daily_financial_promotion import promote_daily_financial_facts


class DailyFinancialPromotionTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path, Path]:
        database = root / "quarterly_metrics.json"
        local = root / "cmhk.data.local_financial_results.json"
        verified = root / "verified_facts.jsonl"
        database.write_text(
            json.dumps(
                {
                    "rows": [],
                    "subjects": [
                        {"subject": "HKT / csl / 1O1O", "periods": [], "metrics": {}},
                        {"subject": "中国移动", "periods": [], "metrics": {}},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "manifest.json").write_text(
            json.dumps({"quality": {"row_count": 0, "notes": []}, "row_count": 0}), encoding="utf-8"
        )
        local.write_text(
            json.dumps(
                {
                    "reports": [
                        {
                            "row": 2,
                            "company": "HKT",
                            "period": "H1 2026",
                            "source_url": "https://www.hkt.com/results/h1-2026.pdf",
                            "source_title": "HKT H1 2026",
                            "content_hash": "hkt-hash",
                            "metrics": [
                                {"metric_key": "revenue", "value": "HK$18,685 million", "evidence": "Total revenue HK$18,685 million"}
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        verified.write_text(
            json.dumps(
                {
                    "company": "中国移动",
                    "metric": "收入",
                    "value": "2026年上半年营业收入538,035百万元人民币",
                    "basis": "2026年上半年营业收入538,035百万元人民币",
                    "decision": "accepted",
                    "status": "ok",
                    "entity_supported": True,
                    "metric_supported": True,
                    "value_supported": True,
                    "sources": ["https://example.test/zh-report.pdf", "https://example.test/en-report.pdf"],
                    "row_ref": "row_49",
                    "evidence_hash": "cm-hash",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return database, local, verified

    def test_daily_official_facts_are_promoted_into_primary_rows_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database, local, verified = self._paths(Path(temp_dir))

            result = promote_daily_financial_facts(
                database_path=database,
                local_financial_path=local,
                verified_facts_path=verified,
                generated_at="2026-08-28T12:00:00+08:00",
            )

            payload = json.loads(database.read_text(encoding="utf-8"))
            keyed = {(row["subject"], row["period"], row["metric_key"]): row for row in payload["rows"]}
            self.assertEqual(result["added_rows"], 2)
            self.assertEqual(keyed[("HKT / csl / 1O1O", "H1 2026", "revenue")]["official_value"], 18685)
            self.assertEqual(keyed[("中国移动", "H1 2026", "revenue")]["official_value"], 538035)
            self.assertTrue((database.with_suffix(".csv")).exists())
            self.assertTrue((database.with_name("quarterly_metrics_human_readable.csv")).exists())
            manifest = json.loads((database.with_name("manifest.json")).read_text(encoding="utf-8"))
            self.assertEqual(manifest["row_count"], 2)
            self.assertIn("H1 2026", {item["period"] for item in payload["subjects"][0]["periods"]})

    def test_existing_stronger_official_row_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database, local, verified = self._paths(Path(temp_dir))
            payload = json.loads(database.read_text(encoding="utf-8"))
            payload["rows"] = [
                {
                    "subject": "HKT / csl / 1O1O",
                    "period": "H1 2026",
                    "metric_key": "revenue",
                    "official_value": 19000,
                    "value": 19000,
                    "verification_status": "official_match",
                }
            ]
            database.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            result = promote_daily_financial_facts(
                database_path=database,
                local_financial_path=local,
                verified_facts_path=verified,
            )

            current = json.loads(database.read_text(encoding="utf-8"))
            hkt = next(row for row in current["rows"] if row["subject"] == "HKT / csl / 1O1O")
            self.assertEqual(hkt["official_value"], 19000)
            self.assertEqual(result["preserved_stronger_rows"], 1)


if __name__ == "__main__":
    unittest.main()
