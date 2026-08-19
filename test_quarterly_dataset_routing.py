from __future__ import annotations

import unittest

import agent
import rag_llm


class QuarterlyDatasetRoutingTests(unittest.TestCase):
    def test_registry_hides_superseded_august_snapshot(self) -> None:
        dataset_ids = {item["id"] for item in rag_llm.list_knowledge_datasets()}

        self.assertIn("quarterly_competitor_metrics_2026-06-18", dataset_ids)
        self.assertNotIn("quarterly_competitor_metrics_2026-08-18", dataset_ids)

    def test_registry_rejects_explicit_superseded_august_snapshot(self) -> None:
        datasets = rag_llm.list_knowledge_datasets(
            dataset_ids={"quarterly_competitor_metrics_2026-08-18"}
        )

        self.assertEqual(datasets, [])

    def test_rag_exact_selector_uses_canonical_active_package(self) -> None:
        path = rag_llm._selected_quarterly_metrics_csv()

        self.assertIsNotNone(path)
        self.assertEqual(path.parent.name, "quarterly_competitor_metrics_2026-06-18")

    def test_rag_exact_selector_rejects_superseded_august_snapshot(self) -> None:
        path = rag_llm._selected_quarterly_metrics_csv(
            dataset_ids={"quarterly_competitor_metrics_2026-08-18"}
        )

        self.assertIsNone(path)

    def test_forecast_selector_uses_canonical_active_package(self) -> None:
        token = agent.SELECTED_DATASET_IDS.set(None)
        try:
            path = agent._selected_quarterly_metrics_path()
        finally:
            agent.SELECTED_DATASET_IDS.reset(token)

        self.assertIsNotNone(path)
        self.assertEqual(path.parent.name, "quarterly_competitor_metrics_2026-06-18")

    def test_forecast_selector_rejects_superseded_august_snapshot(self) -> None:
        token = agent.SELECTED_DATASET_IDS.set(
            {"quarterly_competitor_metrics_2026-08-18"}
        )
        try:
            path = agent._selected_quarterly_metrics_path()
        finally:
            agent.SELECTED_DATASET_IDS.reset(token)

        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
