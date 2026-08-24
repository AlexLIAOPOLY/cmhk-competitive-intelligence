from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")


class CompetitorInsightSurfaceTests(unittest.TestCase):
    def test_insight_content_floats_without_an_outer_card(self):
        rule = STYLE.split(".competitor-insight {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow: visible", rule)
        self.assertIn("border: 0", rule)
        self.assertIn("border-radius: 0", rule)
        self.assertIn("background: transparent", rule)
        self.assertIn("box-shadow: none", rule)
        self.assertIn("radial-gradient", STYLE)
        self.assertIn("@keyframes competitor-insight-aura", STYLE)


if __name__ == "__main__":
    unittest.main()
