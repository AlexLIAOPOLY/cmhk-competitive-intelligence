import json
import re
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from data_curation.research_efficiency import index_passages, ordered_network_map, pack_baseline, pack_context
from data_curation.six_agent_research import collect_sources


def unpack_context(content):
    payload = json.loads(content)
    baseline = payload["trusted_database_baseline"]
    if isinstance(baseline, dict):
        payload["trusted_database_baseline"] = [
            {**baseline["common"], **dict(zip(baseline["columns"], row))}
            for row in baseline["rows"]]
    sources = {}
    for source in payload["official_sources"]:
        if "preview_same_as_source_url" in source:
            source["preview"] = sources[source.pop("preview_same_as_source_url")]["preview"]
        sources[source["source_url"]] = source
    return payload


class ResearchEfficiencyTests(unittest.TestCase):
    def test_linear_passages_match_original_regex_at_boundaries_and_long_tokens(self):
        cases = ["", "a", "报告 revenue 100. " * 300, "字" * 3303,
                 "a" * 1100 + " b", "a" * 1101 + " b", "a" * 5000 + " b c",
                 "a " + "b" * 1101 + " c " + "d" * 2200, "a " * 1101]
        for body in cases:
            body = re.sub(r"\s+", " ", body).strip()
            expected = {f"p{i}": {"text": match.group(), "offset": match.start()}
                        for i, match in enumerate(re.finditer(r".{1,1100}(?:\s|$)", body))}
            self.assertEqual(index_passages(body), expected)

    def test_passage_index_reuses_only_exact_current_opened_official_text(self):
        from data_curation.research_harness import ResearchHarness
        from data_curation.six_agent_research import validate_fact
        from tests.test_research_harness import TASK, ToolModel, submission
        harness = ResearchHarness(TASK, ToolModel(responses=[submission()]), lambda *args: None, validate_fact)
        url = "https://official.test/report"
        pages = {url: {"opened": True, "official": True, "text": "HKT revenue HK$ 100 million in 2026."}}
        harness.extract("HKT", "收入", pages, lambda item: None)
        first = harness.current["passages"][url]
        harness.extract("HKT", "EBITDA", pages, lambda item: None)
        self.assertIs(harness.current["passages"][url], first)
        pages[url]["text"] = "HKT revenue HK$ 200 million in 2026."
        harness.extract("HKT", "收入", pages, lambda item: None)
        self.assertIsNot(harness.current["passages"][url], first)
        self.assertIn("200", harness.current["passages"][url]["p0"]["text"])
        pages[url]["official"] = False
        harness.extract("HKT", "收入", pages, lambda item: None)
        self.assertEqual(harness.current["passages"], {})
        self.assertEqual(harness._page_passages, {})

    def test_packing_round_trips_all_periods_values_scopes_and_source_text(self):
        rows = [{"period": f"FY{year}", "value": value, "unit": "HKD million",
                 "scope": "Subsidiary only; not the parent group. " * 10,
                 "source_url": f"https://official.test/{year}"}
                for year, value in zip(range(2016, 2027), [0, None, "", "about 2", *range(7)])]
        preview = "Original revenue table, 2026. " * 80
        payload = {"company": "HKT", "metric": "收入", "trusted_database_baseline": rows,
                   "official_sources": [{"source_url": url, "characters": 5000, "preview": preview}
                                        for url in ["https://official.test/a", "https://official.test/b"]],
                   "relevant_passages": [{"source_url": "https://official.test/b", "passage_id": "p7", "text": "Exact quote."}]}
        content = pack_context(payload)
        self.assertEqual(unpack_context(content), payload)
        self.assertLess(len(content), len(json.dumps(payload, ensure_ascii=False)) * .65)

    def test_different_schema_or_similar_previews_are_never_merged(self):
        rows = [{"value": 0}, {"value": None, "scope": ""}]
        self.assertEqual(pack_baseline(rows), rows)
        payload = {"trusted_database_baseline": rows, "official_sources": [
            {"source_url": "a", "preview": "x" * 200 + "1"},
            {"source_url": "b", "preview": "x" * 200 + "2"}]}
        self.assertEqual(unpack_context(pack_context(payload)), payload)

    def test_numeric_and_boolean_types_cannot_collapse_into_a_common_value(self):
        rows = [{"value": value, "scope": "same scope " * 100} for value in [0, False, 0.0, -0.0]]
        restored = unpack_context(pack_context({"trusted_database_baseline": rows, "official_sources": []}))
        self.assertEqual(json.dumps(restored["trusted_database_baseline"], sort_keys=True),
                         json.dumps(rows, sort_keys=True))

    def test_parallel_requests_keep_order_and_global_six_request_cap(self):
        lock = threading.Lock()
        active = peak = 0
        def request(value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.02 * (3 - value % 3))
            with lock:
                active -= 1
            return value
        with ThreadPoolExecutor(max_workers=6) as agents:
            results = list(agents.map(lambda _: list(ordered_network_map(request, range(6))), range(6)))
        self.assertTrue(all(result == list(range(6)) for result in results))
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 6)
        self.assertEqual(active, 0)
        with self.assertRaisesRegex(RuntimeError, "network failed"):
            list(ordered_network_map(lambda _: (_ for _ in ()).throw(RuntimeError("network failed")), [1]))
        self.assertEqual(list(ordered_network_map(lambda x: x, [1, 2])), [1, 2])

    def test_duplicate_queries_preserve_metric_records_and_retry_empty_searches(self):
        profile = {"official_hosts": ["official.test"], "seed_urls": ["https://official.test/results"]}
        root = "https://official.test/results"
        child = "https://official.test/2026-interim.pdf"
        pages = {root: {"opened": True, "text": "results", "disclosure_links": [{"url": child}]},
                 child: {"opened": True, "text": "Revenue 123 in 2026."}}
        for empty in [False, True]:
            queries, reads, events = [], [], []
            def search(query, **kwargs):
                queries.append(query)
                return ([] if empty else [{"url": root, "title": "results"}]), "test"
            def read(url, **kwargs):
                reads.append(url)
                return pages[url]
            with patch("data_curation.research_plan.frontend_metric_plan", return_value={"local": ["收入", "营业收入"]}), \
                 patch("data_curation.workflow._company_research_profile", return_value=profile), \
                 patch("data_curation.workflow._metric_evidence_terms", return_value=["revenue"]), \
                 patch("data_curation.workflow._public_web_search", side_effect=search), \
                 patch("data_curation.workflow._read_source_page", side_effect=read):
                result, searches = collect_sources("HKT", ["收入", "营业收入"],
                                                  lambda *event: events.append((threading.get_ident(), event)))
            self.assertEqual(len(queries), 4 if empty else 3)
            self.assertEqual(len(searches), 4)
            self.assertEqual([row["metric"] for row in searches][-2:], ["收入", "营业收入"])
            self.assertEqual(bool(searches[-1].get("query_reused")), not empty)
            self.assertEqual(reads, [root, child])
            self.assertTrue(result[child]["official"])
            self.assertTrue(all(tid == threading.get_ident() for tid, _ in events))


if __name__ == "__main__":
    unittest.main()
