import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")


class NewsArchiveFilterExclusivityTests(unittest.TestCase):
    def test_news_archive_uses_one_single_date_selector(self):
        self.assertEqual(SCRIPT.count('type="date" data-news-date-select'), 1)
        self.assertNotIn('name="news-archive-filter"', SCRIPT)
        self.assertNotIn("data-news-run-option", SCRIPT)
        self.assertNotIn("data-news-date-option", SCRIPT)
        self.assertIn('params.get("newsDate")', SCRIPT)
        self.assertIn("state.newsSelectedDate = newsDate.value", SCRIPT)


if __name__ == "__main__":
    unittest.main()
