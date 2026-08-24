from __future__ import annotations

import json
import unittest
from pathlib import Path

from cmhk.intelligence.executive import _requested_international_domain


ROOT = Path(__file__).resolve().parents[1]


class RequestedInternationalOverviewTests(unittest.TestCase):
    def test_overview_keeps_four_domain_shape_and_uses_requested_carriers(self) -> None:
        payload = json.loads((
            ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.json"
        ).read_text(encoding="utf-8"))

        domain = _requested_international_domain(payload)

        self.assertEqual(domain["title"], "国际运营商")
        self.assertEqual(
            {item["name"] for item in domain["entities"]},
            {"Verizon", "Deutsche Telekom", "AT&T", "NTT Group"},
        )
        self.assertEqual(
            [focus["id"] for focus in domain["focuses"]],
            ["scale", "connection_growth", "revenue_growth", "profit_margin"],
        )
        self.assertTrue(all(len(focus["items"]) == 4 for focus in domain["focuses"]))
        self.assertTrue(all(item["verification_count"] >= 3 for item in domain["entities"]))
        self.assertNotIn("Comcast", json.dumps(domain, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
