import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class LeadershipBoardBackgroundTests(unittest.TestCase):
    def test_international_panel_uses_visible_background_mask(self) -> None:
        html = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (ROOT / "web/static/leadership-board.css").read_text(encoding="utf-8")

        self.assertIn('href="/static/leadership-board.css?v=3"', html)
        self.assertIn("--domain-mask-mid: .62;", styles)
        self.assertIn("--domain-mask-bottom: .18;", styles)


if __name__ == "__main__":
    unittest.main()
