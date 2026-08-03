from __future__ import annotations

import unittest

from executive_intelligence import build_executive_intelligence_snapshot


class ExecutiveIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_executive_intelligence_snapshot()

    def test_four_domains_are_present_and_backed_by_entities(self):
        domains = self.snapshot["domains"]
        self.assertEqual([item["id"] for item in domains], ["local", "international", "cloud", "macro"])
        self.assertTrue(all(item["entities"] for item in domains))
        self.assertGreaterEqual(domains[0]["metric"]["value"], 100)

    def test_relationships_connect_different_domains_and_are_typed(self):
        relations = self.snapshot["relations"]
        self.assertGreaterEqual(len(relations), 4)
        self.assertTrue(all(item["from"] != item["to"] for item in relations))
        self.assertTrue(all(item["kind"] and item["detail"] for item in relations))

    def test_source_links_are_public_http_urls(self):
        for domain in self.snapshot["domains"]:
            self.assertTrue(domain["sources"])
            for source in domain["sources"]:
                self.assertTrue(source["url"].startswith(("https://", "http://")))


if __name__ == "__main__":
    unittest.main()
