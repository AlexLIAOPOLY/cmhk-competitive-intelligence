from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STYLES = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")


class IntelligenceChartMaterialTests(unittest.TestCase):
    def test_homepage_bars_share_dimensional_material(self):
        self.assertIn("Give every comparison bar the same dimensional material language", STYLES)
        self.assertIn(".intelligence-domain-bars i b {", STYLES)
        self.assertIn(".intelligence-viz-rows li > i b {", STYLES)
        self.assertIn(".intelligence-financial-chart-bar > i > b {", STYLES)
        self.assertIn("rgba(231, 253, 255, .48)", STYLES)
        self.assertIn("color-mix(in srgb, var(--domain-accent) 66%, #d8f7fb)", STYLES)

    def test_bar_reveal_is_staggered_and_accessible(self):
        self.assertIn("--chart-sequence: 7", STYLES)
        self.assertIn("animation: intelligence-bar-grow .72s calc(120ms + var(--chart-sequence) * 65ms)", STYLES)
        self.assertIn("animation-delay: calc(120ms + var(--chart-sequence) * 65ms);", STYLES)
        self.assertIn(".intelligence-financial-chart.is-columns .intelligence-financial-chart-bar > i > b", STYLES)
        self.assertIn(".intelligence-domain.is-content-switching .intelligence-viz-rows li > i b", STYLES)
        self.assertIn("animation-name: intelligence-column-regrow;", STYLES)
        self.assertIn("animation: none !important; transform: none !important;", STYLES)

    def test_homepage_loads_new_chart_styles(self):
        self.assertIn('/static/styles.css?v=294', INDEX)


if __name__ == "__main__":
    unittest.main()
