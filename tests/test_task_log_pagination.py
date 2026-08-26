from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")


class TaskLogScrollTests(unittest.TestCase):
    def test_task_sidebar_renders_all_filtered_items(self):
        self.assertIn("const taskItems = visibleTasks.map", APP)
        self.assertNotIn("crawlRunPageSize", APP)
        self.assertNotIn("data-crawl-run-page", APP)
        self.assertNotIn('class="crawl-run-pagination"', APP)

    def test_task_list_uses_wheel_scrolling_inside_the_sidebar(self):
        self.assertIn(".crawl-run-list {", STYLES)
        block = STYLES[STYLES.index(".crawl-run-list {"):STYLES.index(".crawl-run-item {")]
        self.assertIn("overflow-y: auto;", block)
        self.assertIn("overscroll-behavior: contain;", block)
        self.assertIn("scrollbar-gutter: stable;", block)


if __name__ == "__main__":
    unittest.main()
