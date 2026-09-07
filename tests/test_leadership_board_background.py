import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LeadershipBoardBackgroundTests(unittest.TestCase):
    def test_international_panel_uses_visible_background_mask(self) -> None:
        html = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
        styles = (ROOT / "web/static/leadership-board.css").read_text(encoding="utf-8")

        self.assertIn('href="/static/leadership-board.css?v=23"', html)
        self.assertIn("--domain-mask-mid: .62;", styles)
        self.assertIn("--domain-mask-bottom: .18;", styles)
        self.assertIn("grid-template-rows: 70px minmax(0, 1fr);", styles)
        self.assertIn("min-height: 70px;\n  padding: 6px 16px;", styles)
        self.assertIn("grid-template-columns: minmax(0, 1.15fr) minmax(230px, .85fr);", styles)
        self.assertIn("gap: clamp(18px, 2vw, 36px);", styles)


if __name__ == "__main__":
    unittest.main()
