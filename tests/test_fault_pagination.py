from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")


class FaultPaginationTests(unittest.TestCase):
    def test_alarm_ledger_uses_bounded_ten_row_pages(self):
        self.assertIn("faultPageSize: 10", SCRIPT)
        self.assertIn("rows.slice(pageStart, pageStart + state.faultPageSize)", SCRIPT)
        self.assertIn('id="faultPagination"', SCRIPT)
        self.assertIn('data-fault-page="${page}"', SCRIPT)
        self.assertIn("每页 ${state.faultPageSize} 条 · 共 ${number(rows.length)} 条", SCRIPT)
        self.assertIn("function faultPaginationTokens(current, total)", SCRIPT)
        self.assertIn('class="fault-pagination-ellipsis"', SCRIPT)
        self.assertIn('fetch("/api/project-incidents?limit=500"', SCRIPT)
        self.assertNotIn("当前显示最新 ${number(state.tasks.length)} 条", SCRIPT)

    def test_pagination_is_rendered_below_the_table(self):
        self.assertIn(".fault-monitor-footer { display: flex;", STYLE)
        self.assertIn(".fault-pagination button.is-active", STYLE)

    def test_pagination_stays_in_document_flow(self):
        self.assertIn(".fault-workbench { min-height: 100%; overflow: visible; }", STYLE)
        self.assertIn(".fault-table-wrap { min-height: 0; max-height: 698px; overflow-x: auto; overflow-y: hidden; }", STYLE)
        self.assertIn(".fault-table-wrap { max-height: none; overflow-x: hidden; overflow-y: visible; }", STYLE)
        self.assertNotIn(".fault-table-wrap { min-height: 0; flex: 1; overflow: auto", STYLE)


if __name__ == "__main__":
    unittest.main()
