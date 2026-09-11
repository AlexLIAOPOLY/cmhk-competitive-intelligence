import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_curation.research_kpi import (CARRIER_PATH, CLOUD_PATH, exact_amount, formal_period,
                                      normalize_fact, prepare_facts, write_formal_facts)
from data_curation.research_storage import audit_storage, DOMAIN_PATHS
from data_curation.repair_research_storage import repair
from tests.test_research_storage import fact


def tables(root, carrier=None):
    for relative, rows in [(CARRIER_PATH, carrier or []), (CLOUD_PATH, [])]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rows": rows, "subjects": []}))


class FormalResearchTests(unittest.TestCase):
    def test_explicit_currencies_scales_and_no_coercion_of_bounds(self):
        for value, unit, expected in [("5,606 S$ million", "S$ million", (5606, "SGD")),
                                      ("197.0 Billions of yen", "Billions of yen", (197000, "JPY")),
                                      ("19,654 £m", "£m", (19654, "GBP")),
                                      ("14,409,121", "Millions of yen", (14409121, "JPY")),
                                      ("524,742", "$000 (Hong Kong dollars)", (524.742, "HKD")),
                                      ("6.8", "billion euros", (6800, "EUR")),
                                      ("0 USD million", "USD million", (0, "USD"))]:
            self.assertEqual(exact_amount(value, unit), expected)
        self.assertEqual(exact_amount("$220 Hong Kong dollars", "Hong Kong dollars", per_customer=True), (220, "HKD"))
        self.assertEqual(exact_amount("32.4", "€/month", per_customer=True), (32.4, "EUR"))
        self.assertEqual(exact_amount("40.9", "GBP per month", per_customer=True), (40.9, "GBP"))
        self.assertIsNone(exact_amount("HKD 220 million", "HKD million", per_customer=True))
        for value in ["surpassed $100 billion USD billions", "USD 20-30 million", "22,937 $m", "USD 12,34 million", "USD 2 million billion", "USD 10 million EUR"]:
            self.assertIsNone(exact_amount(value, ""), value)

    def test_native_fiscal_periods_keep_actual_ends(self):
        for company, period, expected in [
            ("SmarTone", "For the year ended 30 June 2026", ("FY2026", "2026-06-30", "annual", "2026")),
            ("BT", "Year ended 31 March 2026", ("FY2026", "2026-03-31", "annual", "2026")),
            ("NTT Docomo", "FY2026/1Q", ("Q1 FY2026", "2026-06-30", "quarter", "2026")),
            ("SoftBank", "Q1 FY2026", ("Q1 FY2026", "2026-06-30", "quarter", "2026")),
            ("BT", "First quarter to 30 June 2026", ("Q1 FY2027", "2026-06-30", "quarter", "2027")),
            ("NTT Docomo", "Three Months ended June 30, 2026", ("Q1 FY2026", "2026-06-30", "quarter", "2026")),
            ("SmarTone", "Six months ended December 31, 2025", ("H1 FY2026", "2025-12-31", "half_year", "2026")),
        ]:
            self.assertEqual(formal_period(company, period), expected)
        for company, period in [("SmarTone", "Q1 2026"), ("BT", "FY2026"), ("BT", "Six months ended May 31, 2026")]:
            self.assertIsNone(formal_period(company, period))

    def test_operating_scopes_do_not_merge_or_convert_to_financial_millions(self):
        cases = [
            (dict(metric="客户数/用户数", company="中国移动", value="10.11 亿户", unit="亿户"), "subscribers", 1011000000, "subscribers"),
            (dict(metric="后付费用户数", company="SmarTone", period="For the year ended 30 June 2026", value="3.1", unit="million postpaid customers"), "postpaid_subscribers", 3100000, "subscribers"),
            (dict(metric="站址数", company="中国铁塔", value="2,172 千", unit="千"), "tower_sites", 2172000, "sites"),
            (dict(metric="ARPU", company="SK Telecom", value="29,098 KRW", unit="KRW", reasons=["excluding MVNO"]), "mobile_arpu_excluding_mvno", 29098, "KRW"),
            (dict(metric="ARPU", company="Telefonica", value="91.1 €", unit="€", reasons=["Telefónica España"]), "spain_arpu", 91.1, "EUR"),
            (dict(metric="Open RAN", company="AT&T", value="45%", unit="% of wireless traffic", basis="45% of wireless traffic"), "open_ran_traffic_share", 45, "percent"),
            (dict(metric="AI", company="SK Telecom", value="KRW 136.2 billion", unit="KRW billion", basis="AIDC revenue"), "ai_data_center_revenue", 136200, "millions KRW"),
        ]
        for update, key, value, unit in cases:
            row, _, error = normalize_fact(fact(**update))
            self.assertFalse(error, error)
            self.assertEqual((row["metric_key"], row["value"], row["unit"]), (key, value, unit))
        for update in [dict(metric="EBITDA或经营利润"), dict(metric="家宽套餐", value="1G至50G", unit="G"), dict(source_tier="media")]:
            self.assertIsNone(normalize_fact(fact(**update))[0])

    def test_existing_aliases_conflicts_and_rerun_are_resolved_before_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables(root)
            inputs = [fact(id="a"), fact(id="b", metric="运营收入/总收益")]
            output, gate = prepare_facts(root, inputs, "research_test")
            self.assertEqual(gate["counts"], {"ready": 1, "duplicate": 1})
            accepted = [f for f in output if f["decision"] == "accepted"]
            self.assertEqual(write_formal_facts(root, accepted)["added_rows"], 1)
            self.assertEqual(write_formal_facts(root, accepted)["added_rows"], 0)
            self.assertEqual(prepare_facts(root, inputs, "research_next")[1]["counts"], {"existing": 2})
            retry = prepare_facts(root, output, "research_test", allow_replay=True)[0]
            self.assertEqual(sum(f["decision"] == "accepted" for f in retry), 1)
            tables(root)
            conflict = prepare_facts(root, inputs + [fact(id="c", value="HKD 300 million"), fact(id="d")], "research_conflict")[0]
            self.assertTrue(all(f["decision"] == "review" and f["write_preflight"]["status"] == "rejected" for f in conflict))

    def test_only_formal_rows_prove_success_and_concurrent_conflicts_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables(root)
            prepared = prepare_facts(root, [fact()], "research_test")[0]
            old = normalize_fact(fact(value="HKD 999 million", evidence_hash="other"))[0]
            tables(root, [old])
            write = write_formal_facts(root, prepared)
            self.assertEqual((write["written"], write["not_written"]), (0, 1))
            self.assertEqual(json.loads((root / CARRIER_PATH).read_text())["rows"], [old])
            readback = audit_storage(root, prepared)
            self.assertFalse(readback["ok"])
            self.assertEqual(readback["items"][0]["status"], "not_written")
            tables(root)
            with patch("cmhk.data.daily_financial_promotion._atomic_text"):
                with self.assertRaisesRegex(ValueError, "回读"):
                    write_formal_facts(root, prepared)
            self.assertFalse(audit_storage(root, prepared)["ok"])

    def test_cloud_writes_use_the_real_cloud_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables(root)
            source = fact(company="Microsoft Azure", metric="云收入", period="fiscal year ended June 30, 2026", value="USD 110 billion", unit="USD billion")
            prepared = prepare_facts(root, [source], "research_cloud")[0]
            self.assertTrue(write_formal_facts(root, prepared)["ok"])
            saved = json.loads((root / CLOUD_PATH).read_text())["rows"][0]
            self.assertEqual((saved["vendor"], saved["fiscal_year"], saved["currency"], saved["unit"], saved["value"]), ("Microsoft Azure", "2026", "USD", "millions", 110000))
            self.assertTrue(audit_storage(root, prepared)["ok"])
            self.assertEqual(json.loads((root / CARRIER_PATH).read_text())["rows"], [])

    def test_source_only_archive_cannot_be_an_existing_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables(root)
            sidecar = root / DOMAIN_PATHS["local"]
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text(json.dumps({"facts": [fact()]}))
            revised, _ = prepare_facts(root, [fact(decision="unchanged", research_status="no_update")], "research_test")
            self.assertEqual(revised[0]["decision"], "review")
            self.assertIn("未查到相应期间的正式指标", revised[0]["reasons"][0])

    def test_canonical_baseline_matches_written_revenue_but_not_newer_source_only_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = normalize_fact(fact())[0]
            tables(root, [row])
            source = fact(decision="unchanged", research_status="no_update", period="", baseline=[{"period": "H1 2026"}])
            self.assertEqual(prepare_facts(root, [source], "research_test")[0][0]["write_preflight"]["status"], "existing")
            source["baseline"] = [{"period": "Q3 2026"}]
            self.assertEqual(prepare_facts(root, [source], "research_test")[0][0]["write_preflight"]["status"], "rejected")

    def test_backed_up_repair_updates_agents_and_binary_receipt_idempotently(self):
        from data_curation.review_store import ReviewStore, load_review
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables(root)
            directory = root / "curation_data/research_runs/research_test"
            directory.mkdir(parents=True)
            facts = [fact(id="first", research_status="verified"), fact(id="alias", metric="运营收入/总收益", research_status="verified"), fact(id="bad", metric="家宽套餐", value="1G至50G", unit="G", research_status="verified")]
            task = {"key": "hong-kong", "title": "香港", "companies": ["HKT"]}
            manifest = {"run_id": "research_test", "architecture": "six_research_agents_v1", "status": "partial", "accepted": 3, "plan": [task]}
            (directory / "manifest.json").write_text(json.dumps(manifest))
            (directory / "verified_facts.jsonl").write_text('\n'.join(json.dumps(f) for f in facts))
            report = {"company": "HKT", "items": [{"metric": f["metric"], "status": "verified"} for f in facts], "review_completed": True, "pages": {}}
            (directory / "hong-kong.json").write_text(json.dumps({**task, "reports": [report]}))
            store = ReviewStore(directory, {"key": "final-review"}, "research_test", ["HKT"], 1)
            store.save(report, evidence_changed=True)
            store.complete()
            self.assertEqual(repair(root, "research_test")["would_submit"], 1)
            self.assertEqual(json.loads((directory / "manifest.json").read_text()), manifest)
            result = repair(root, "research_test", apply=True)
            self.assertTrue(result["readback"]["ok"])
            self.assertEqual((result["readback"]["written"], result["readback"]["not_written"]), (1, 0))
            self.assertTrue((Path(result["backup_path"]) / "research-archive/manifest.json").exists())
            self.assertEqual([i["write_preflight"]["status"] for i in load_review(directory)["reports"][0]["items"]], ["ready", "duplicate", "rejected"])
            self.assertEqual(repair(root, "research_test", apply=True)["main_table"]["added_rows"], 0)


if __name__ == "__main__":
    unittest.main()
