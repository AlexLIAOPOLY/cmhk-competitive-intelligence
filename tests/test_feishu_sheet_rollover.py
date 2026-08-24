from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cmhk.integrations.feishu_sheet_rollover import (
    capacity_decision,
    read_registry,
    record_active_part,
    timestamped_part_title,
)


class FeishuSheetRolloverTests(unittest.TestCase):
    def test_cell_limit_is_converted_to_effective_row_limit(self) -> None:
        decision = capacity_decision(used_rows=321_428, incoming_rows=1, column_count=14)
        self.assertEqual(decision.hard_row_limit, 357_142)
        self.assertTrue(decision.should_rollover)
        self.assertEqual(decision.reason, "row_or_cell_limit_near")

    def test_operational_limit_can_trigger_earlier_rollover(self) -> None:
        decision = capacity_decision(
            used_rows=2_690,
            incoming_rows=10,
            column_count=14,
            operational_max_rows=3_000,
        )
        self.assertTrue(decision.should_rollover)
        self.assertEqual(decision.soft_row_limit, 2_700)

    def test_workbook_sheet_limit_has_safety_margin(self) -> None:
        decision = capacity_decision(
            used_rows=1,
            incoming_rows=1,
            column_count=6,
            sheet_count=270,
        )
        self.assertTrue(decision.should_rollover)
        self.assertEqual(decision.reason, "workbook_sheet_limit_near")

    def test_timestamped_title_is_unique_and_safe(self) -> None:
        now = datetime(2026, 8, 21, 9, 5, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        first = "项目_错误_20260821_0905"
        self.assertEqual(
            timestamped_part_title("项目:错误", now=now, existing_titles={first}),
            first + "_2",
        )

    def test_registry_updates_backend_pointer_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = record_active_part(
                root,
                "news_review",
                spreadsheet_token="token",
                sheet_id="sheet2",
                sheet_title="候选池_20260821_0905",
                previous={"sheet_id": "sheet1", "sheet_title": "候选池"},
            )
            registry = read_registry(root)
            self.assertEqual(registry["targets"]["news_review"]["sheet_id"], "sheet2")
            self.assertEqual(entry["previous_part"]["sheet_id"], "sheet1")
            json.loads((root / "var" / "feishu_sheet_rollovers.json").read_text())


if __name__ == "__main__":
    unittest.main()
