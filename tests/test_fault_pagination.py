from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")


class FaultScrollTests(unittest.TestCase):
    def test_alarm_ledger_renders_all_rows_without_pagination(self):
        self.assertIn("body.innerHTML = rows.length ? rows.map", SCRIPT)
        self.assertNotIn("faultPageSize", SCRIPT)
        self.assertNotIn('id="faultPagination"', SCRIPT)
        self.assertNotIn("data-fault-page", SCRIPT)
        self.assertIn('fetch("/api/project-incidents?limit=500"', SCRIPT)

    def test_status_footer_remains_without_page_controls(self):
        self.assertIn(".fault-monitor-footer { display: flex;", STYLE)
        self.assertNotIn(".fault-pagination", STYLE)

    def test_alarm_table_is_bounded_to_the_viewport_and_scrolls(self):
        self.assertIn(".fault-workbench { display: flex; height: calc(100dvh - 106px); min-height: 0;", STYLE)
        self.assertIn(".fault-table-wrap { min-height: 0; max-height: none; flex: 1; overflow: auto;", STYLE)
        self.assertIn(".fault-table th { position: sticky;", STYLE)


if __name__ == "__main__":
    unittest.main()
