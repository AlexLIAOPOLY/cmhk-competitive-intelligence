from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-responsive-system.css").read_text(
    encoding="utf-8"
)
PUBLISHER = (ROOT / "scripts" / "publish_executive_dashboard_pages.py").read_text(
    encoding="utf-8"
)


class WorkspaceResponsiveSystemTests(unittest.TestCase):
    def test_responsive_contract_is_loaded_last_and_published(self):
        href = '/static/workspace-responsive-system.css?v=5'
        self.assertIn(href, INDEX)
        self.assertGreater(INDEX.index(href), INDEX.index('/static/organization-admin.css?v=28'))
        self.assertIn('"workspace-responsive-system.css"', PUBLISHER)

    def test_compact_header_has_non_overlapping_grid_columns(self):
        self.assertIn("@media (max-width: 560px)", STYLE)
        self.assertIn("grid-template-columns: minmax(104px, 1fr) minmax(0, 1.15fr) 48px", STYLE)
        self.assertIn(".intelligence-page-identity {", STYLE)
        self.assertIn("position: static", STYLE)
        self.assertIn(".auth-user-chevron", STYLE)

    def test_competitor_labels_wrap_instead_of_overlapping(self):
        self.assertIn(".competitor-option-group label > b", STYLE)
        self.assertIn("overflow-wrap: anywhere", STYLE)
        self.assertIn("white-space: normal", STYLE)
        self.assertIn("max-height: none", STYLE)

    def test_small_medium_and_ultrawide_breakpoints_are_explicit(self):
        for breakpoint in (
            "@media (max-width: 560px)",
            "@media (min-width: 561px) and (max-width: 1180px)",
            "@media (min-width: 1800px)",
        ):
            self.assertIn(breakpoint, STYLE)
        self.assertIn(":has(.report-preview.is-placeholder)", STYLE)
        self.assertIn("clamp(340px, 22vw, 520px)", STYLE)
        self.assertIn(".competitor-option-group:not(.is-disappearing)", STYLE)

    def test_modules_adapt_to_their_usable_container_width(self):
        self.assertIn("container: workspace-module / inline-size", STYLE)
        self.assertIn("@container workspace-module (min-width: 1500px)", STYLE)
        self.assertIn("width: min(1180px, calc(100% - 96px))", STYLE)
        self.assertIn("width: min(94%, 2100px)", STYLE)
        self.assertIn("grid-template-columns: minmax(460px, 34%) minmax(0, 1fr)", STYLE)

    def test_wide_empty_states_and_dense_tables_scale_readably(self):
        self.assertIn(".competitor-empty strong", STYLE)
        self.assertIn("font-size: clamp(21px, 1.15cqi, 28px)", STYLE)
        self.assertIn(".workspace-table td", STYLE)
        self.assertIn("font-size: clamp(12px, .62cqi, 14px)", STYLE)

    def test_decision_metadata_no_longer_uses_thumbnail_sized_text(self):
        self.assertIn(".news-item-tags span", STYLE)
        self.assertIn(".news-item dt", STYLE)
        self.assertIn("font-size: 10px", STYLE)
        self.assertIn(".intelligence-viz-kpis small", STYLE)
        self.assertIn("font-size: 9px", STYLE)
        self.assertIn(".market-graph-legend span", STYLE)
        self.assertIn(".market-daily-table-wrap .received-keywords em", STYLE)
        self.assertIn(".intelligence-viz-columns strong small", STYLE)

    def test_all_workspace_tabs_remain_in_shared_document(self):
        modules = (
            "dashboard", "monitoring", "news", "review", "competitor",
            "intelligence-map", "weekly", "performance", "subscriptions",
            "ai", "log", "fault", "organization", "footprint",
        )
        for module in modules:
            self.assertIn(f'data-workspace-tab="{module}"', INDEX)


if __name__ == "__main__":
    unittest.main()
