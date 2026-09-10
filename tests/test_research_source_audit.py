import copy
import unittest
from unittest.mock import patch

from data_curation.research_source_audit import attach_source_audit, annotate_snapshot
from data_curation.six_agent_research import collect_sources, page_mentions_metric, merge_results
from data_curation.workflow import _company_research_profile


class SourceAuditTests(unittest.TestCase):
    def report(self):
        return {"company": "HKT", "items": [], "searches": [
            {"metric": "企业专线", "query": "HKT leased line", "provider": "test", "results": [{"url": "https://www.hkt.com/product"}]}],
            "pages": {"https://www.hkt.com/product": {"opened": True, "official": True,
                "text": "HKT offers an International Ethernet Private Line (IEPL)."}}}

    def test_failure_keeps_trace_separate_from_accepted_evidence(self):
        item = {"company": "HKT", "metric": "企业专线", "status": "error", "value": "", "reason": "Budget has been exceeded", "sources": []}
        before = copy.deepcopy(item)
        output = attach_source_audit(item, self.report())
        self.assertEqual(item, before)
        self.assertEqual(output["sources"], [])
        self.assertEqual(output["value"], "")
        self.assertEqual(output["status"], "error")
        self.assertEqual(output["source_diagnostics"]["stage"], "model_quota")
        self.assertIn("HKT leased line", output["basis"])
        self.assertIn("https://www.hkt.com/product", output["basis"])
        self.assertIn("不是已核准", output["basis"])

    def test_accepted_and_existing_citations_are_unchanged(self):
        for state in ("verified", "no_update"):
            item = {"metric": "企业专线", "status": state, "source_url": "https://www.hkt.com/product", "quote": "literal"}
            self.assertEqual(attach_source_audit(item, self.report()), item)

    def test_no_archived_search_never_claims_exhaustive_review(self):
        item = {"metric": "ARPU", "status": "error"}
        output = attach_source_audit(item, {})
        self.assertEqual(output["source_diagnostics"]["stage"], "source_read_failed")
        self.assertIn("不能宣称已充分检索", output["basis"])

    def test_all_nodes_receive_diagnostics_and_original_quotes_survive(self):
        report = self.report()
        report["items"] = [{"company": "HKT", "metric": "企业专线", "status": "error", "quote": "existing original"}]
        data = {"agents": [{"reports": [report]}], "result_items": [{"company": "HKT", "metric": "企业专线", "decision": "review", "sources": []}]}
        output = annotate_snapshot(data)
        self.assertEqual(output["agents"][0]["reports"][0]["items"][0]["quote"], "existing original")
        self.assertIn("basis", output["result_items"][0])
        self.assertEqual(output["result_items"][0]["sources"], [])

    def test_english_product_terms_are_not_falsely_screened_out(self):
        self.assertTrue(page_mentions_metric("企业专线", self.report()["pages"]))
        for metric, text in (("合约期", "contract term"), ("数据中心", "data centre"), ("网络API", "Open Gateway")):
            self.assertTrue(page_mentions_metric(metric, {"p": {"opened": True, "official": True, "text": text}}))

    def test_product_search_reads_its_result_even_after_eight_financial_results(self):
        product = "https://official.test/products/private-line"
        queries, reads = [], []
        def search(query, **kwargs):
            queries.append(query)
            if "企业专线" in query:
                return [{"url": product, "title": "Leased Line"}], "test"
            return [{"url": f"https://official.test/2026-results-{len(queries)}-{i}", "title": "2026 financial results"} for i in range(5)], "test"
        def read(url, **kwargs):
            reads.append(url)
            return {"opened": True, "text": "private line", "disclosure_links": []}
        with patch("data_curation.workflow._company_research_profile", return_value={"official_hosts": ["official.test"], "seed_urls": []}), \
             patch("data_curation.workflow._public_web_search", side_effect=search), \
             patch("data_curation.workflow._read_source_page", side_effect=read):
            collect_sources("HKT", ["企业专线"], lambda *args: None)
        self.assertIn(product, reads)
        query = next(q for q in queries if "企业专线" in q)
        self.assertNotIn("results", query)
        self.assertNotIn("2026", query)
        self.assertIn("leased line", query)

    def test_verified_hkt_service_hosts_are_in_governed_profile(self):
        self.assertIn("hkt-enterprise.com", _company_research_profile("HKT")["official_hosts"])

    def test_merged_failure_persists_process_without_fabricated_citation(self):
        report = self.report()
        report["metrics"] = ["企业专线"]
        report["items"] = [{"company": "HKT", "metric": "企业专线", "status": "error", "reason": "Budget exceeded"}]
        item = merge_results([{"key": "hong-kong", "reports": [report]}], "test")[0]
        self.assertEqual(item["decision"], "review")
        self.assertEqual(item["sources"], [])
        self.assertIn("核查过程", item["basis"])


if __name__ == "__main__":
    unittest.main()
