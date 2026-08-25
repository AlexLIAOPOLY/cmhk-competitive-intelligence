import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")


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

    def test_metric_title_and_legend_share_the_only_chart_header(self):
        self.assertIn('class="workspace-panel-header competitor-result-header"', SCRIPT)
        header = re.search(
            r'<header class="workspace-panel-header competitor-result-header">(.*?)</header>',
            SCRIPT,
        )
        self.assertIsNotNone(header)
        self.assertIn("metricMeta.label", header.group(1))
        self.assertIn('class="competitor-chart-legend"', header.group(1))
        self.assertNotIn("家竞对", header.group(1))
        self.assertNotIn("多年趋势对比", SCRIPT)
        self.assertNotIn("<figcaption>", SCRIPT)

        rule = re.search(r"\.competitor-result-header\s*\{([^}]*)\}", STYLE)
        self.assertIsNotNone(rule)
        self.assertIn("min-height: 72px", rule.group(1))
        self.assertIn("padding-block: 12px", rule.group(1))

    def test_plot_has_no_inner_background_layer(self):
        rule = re.search(r"\.competitor-chart-scroll\s*\{([^}]*)\}", STYLE)
        self.assertIsNotNone(rule)
        declarations = rule.group(1)
        self.assertNotIn("background:", declarations)
        self.assertNotIn("border-radius:", declarations)

    def test_points_show_an_interactive_tooltip_and_end_labels_are_removed(self):
        self.assertIn('class="competitor-chart-tooltip"', SCRIPT)
        self.assertIn("bindCompetitorChartTooltip(host)", SCRIPT)
        self.assertIn('point.addEventListener("pointerenter"', SCRIPT)
        self.assertIn('point.addEventListener("focus"', SCRIPT)
        self.assertIn('data-chart-items=', SCRIPT)
        self.assertIn('"重合数据点 · "', SCRIPT)
        self.assertIn("共建共享网络口径，数值不可相加", SCRIPT)
        self.assertIn('.competitor-chart-tooltip-list', STYLE)
        self.assertIn('.competitor-chart-tooltip.is-below', STYLE)
        self.assertNotIn('class="competitor-chart-end-label"', SCRIPT)
        self.assertIn("right: 24", SCRIPT)
        self.assertIn(".competitor-chart-tooltip[hidden]", STYLE)

    def test_core_summary_states_a_strategic_implication_instead_of_repeating_values(self):
        self.assertIn("双方的竞争焦点不在基站数量差异", SCRIPT)
        self.assertIn("共享网络的运营效率和业务转化能力", SCRIPT)
        self.assertNotIn("两条曲线完全重合。`", SCRIPT)


if __name__ == "__main__":
    unittest.main()
