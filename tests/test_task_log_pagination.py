from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")


class TaskLogPaginationTests(unittest.TestCase):
    def test_task_sidebar_uses_six_item_pages(self):
        self.assertIn("crawlRunPage: 1", APP)
        self.assertIn("crawlRunPageSize: 6", APP)
        self.assertIn("visibleTasks.slice(pageStart, pageStart + state.crawlRunPageSize)", APP)
        self.assertIn('class="crawl-run-pagination"', APP)
        self.assertIn('data-crawl-run-page="', APP)
        self.assertIn("state.crawlRunPage = 1", APP)

    def test_selected_task_can_reveal_its_page(self):
        self.assertIn("Math.floor(targetIndex / state.crawlRunPageSize) + 1", APP)

    def test_task_pagination_stays_at_sidebar_bottom(self):
        self.assertIn(".crawl-run-list {", STYLES)
        self.assertIn(".crawl-run-page { display: grid;", STYLES)
        self.assertIn(".crawl-run-pagination { display: flex;", STYLES)
        self.assertIn("margin-top: auto;", STYLES[STYLES.index(".crawl-run-pagination {"):STYLES.index(".crawl-run-pagination nav")])


if __name__ == "__main__":
    unittest.main()
