import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class CompetitorChartShellTests(unittest.TestCase):
    def test_trend_chart_uses_the_outer_result_panel_without_a_nested_card(self):
        rule = re.search(r"\.competitor-chart-card\s*\{([^}]*)\}", STYLE)
        self.assertIsNotNone(rule)
        declarations = rule.group(1)
        self.assertIn("border: 0", declarations)
        self.assertIn("border-radius: 0", declarations)
        self.assertIn("background: transparent", declarations)
        self.assertIn("box-shadow: none", declarations)
        self.assertNotIn(
            ".dashboard-page:not(.workspace-dashboard-active) .competitor-chart-card,",
            STYLE,
        )


if __name__ == "__main__":
    unittest.main()
