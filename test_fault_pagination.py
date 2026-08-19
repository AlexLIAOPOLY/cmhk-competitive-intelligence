from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")


class FaultPaginationTests(unittest.TestCase):
    def test_alarm_ledger_uses_real_hundred_row_pages(self):
        self.assertIn("faultPageSize: 100", SCRIPT)
        self.assertIn("rows.slice(pageStart, pageStart + state.faultPageSize)", SCRIPT)
        self.assertIn('id="faultPagination"', SCRIPT)
        self.assertIn('data-fault-page="${page}"', SCRIPT)
        self.assertIn("每页 ${state.faultPageSize} 条 · 共 ${number(rows.length)} 条", SCRIPT)
        self.assertIn('fetch("/api/project-incidents?limit=500"', SCRIPT)
        self.assertNotIn("当前显示最新 ${number(state.tasks.length)} 条", SCRIPT)

    def test_pagination_is_rendered_below_the_table(self):
        self.assertIn(".fault-monitor-footer { display: flex;", STYLE)
        self.assertIn(".fault-pagination button.is-active", STYLE)

    def test_pagination_stays_in_document_flow(self):
        self.assertIn(".fault-workbench { min-height: 100%; overflow: visible; }", STYLE)
        self.assertIn(".fault-table-wrap { min-height: 0; overflow-x: auto; overflow-y: visible; }", STYLE)
        self.assertNotIn(".fault-table-wrap { min-height: 0; flex: 1; overflow: auto", STYLE)


if __name__ == "__main__":
    unittest.main()
