import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")


class NewsArchiveFilterExclusivityTests(unittest.TestCase):
    def test_date_and_run_filters_share_one_exclusive_group(self):
        self.assertEqual(SCRIPT.count('name="news-archive-filter"'), 3)
        self.assertIn('querySelectorAll(\'.news-multi-select[name="news-archive-filter"]\')', SCRIPT)
        self.assertIn("if (!filter.open) return", SCRIPT)
        self.assertIn("if (other !== filter) other.open = false", SCRIPT)


if __name__ == "__main__":
    unittest.main()
