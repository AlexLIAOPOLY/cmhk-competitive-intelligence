from __future__ import annotations

import json
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

    def test_each_domain_exposes_four_distinct_data_backed_focuses(self):
        for domain in self.snapshot["domains"]:
            focuses = domain["focuses"]
            self.assertEqual(len(focuses), 4, domain["id"])
            self.assertEqual(len({focus["id"] for focus in focuses}), 4, domain["id"])
            signatures = {
                json.dumps(
                    {
                        "label": focus["metric"]["label"],
                        "visual": focus["visual"],
                        "items": [
                            (item["name"], item.get("value"), item.get("unit"))
                            for item in focus["items"]
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for focus in focuses
            }
            self.assertEqual(len(signatures), 4, domain["id"])
            for focus in focuses:
                self.assertTrue(focus["items"], f"{domain['id']}:{focus['id']}")
                self.assertTrue(focus["insight"])
                self.assertTrue(focus["metric"]["label"])
                for item in focus["items"]:
                    self.assertTrue(item["analysis"])
                    self.assertTrue(item["source_url"].startswith(("https://", "http://")))

    def test_focuses_preserve_their_real_measurement_semantics(self):
        domains = {domain["id"]: domain for domain in self.snapshot["domains"]}
        local = {focus["id"]: focus for focus in domains["local"]["focuses"]}
        self.assertEqual([local[key]["visual"] for key in ("scale", "track", "price", "overlap")],
                         ["columns", "rows", "ranges", "network"])
        self.assertTrue(all("low" in item and "high" in item for item in local["price"]["items"]))

        international = {focus["id"]: focus for focus in domains["international"]["focuses"]}
        self.assertNotEqual(
            [item["value"] for item in international["growth"]["items"]],
            [item["value"] for item in international["momentum"]["items"]],
        )
        self.assertTrue(all("trend" in item for item in international["momentum"]["items"]))
        self.assertEqual(min(item["value"] for item in international["gap"]["items"]), 0)

        cloud = {focus["id"]: focus for focus in domains["cloud"]["focuses"]}
        self.assertTrue(all("trend" in item for item in cloud["trend"]["items"]))
        self.assertTrue(any(item["value"] is None for item in cloud["profit"]["items"]))

        macro = {focus["id"]: focus for focus in domains["macro"]["focuses"]}
        name_sets = {tuple(item["name"] for item in focus["items"]) for focus in macro.values()}
        self.assertEqual(len(name_sets), 4)


if __name__ == "__main__":
    unittest.main()
