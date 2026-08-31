from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
APP = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")
ORGANIZATION = (ROOT / "web/static/organization-admin.js").read_text(encoding="utf-8")
ORGANIZATION_STYLES = (ROOT / "web/static/organization-admin.css").read_text(encoding="utf-8")


class LongListScrollTests(unittest.TestCase):
    def test_members_render_all_rows_inside_a_viewport_scroller(self):
        self.assertIn("const items = users.map((user)", ORGANIZATION)
        self.assertNotIn("memberPageSize", ORGANIZATION)
        self.assertNotIn("data-member-page", ORGANIZATION)
        self.assertIn(".organization-member-list{display:flex;align-self:stretch", ORGANIZATION_STYLES)
        self.assertIn("height:calc(100dvh - 212px)", ORGANIZATION_STYLES)
        self.assertIn(".organization-member-list>ul{min-height:0;flex:1;overflow-y:auto", ORGANIZATION_STYLES)

    def test_team_footprint_renders_all_filtered_rows_in_a_scroller(self):
        self.assertIn("const rows = events.map((event)", ORGANIZATION)
        self.assertNotIn("auditPageSize", ORGANIZATION)
        self.assertNotIn("data-audit-page", ORGANIZATION)
        self.assertIn(".organization-footprint-surface{display:flex;height:calc(100dvh - 150px)", ORGANIZATION_STYLES)
        self.assertIn("flex:1;overflow:auto;overscroll-behavior:contain", ORGANIZATION_STYLES)

    def test_weekly_and_performance_files_render_all_rows_in_the_scroller(self):
        self.assertIn("files.forEach((file)", APP)
        self.assertNotIn("reportPageSize", APP)
        self.assertNotIn("data-report-page", APP)
        self.assertIn("overflow-y: auto;", STYLES[STYLES.index(".output-table {"):])

    def test_changed_assets_are_cache_busted(self):
        for asset in (
            "/static/styles.css?v=288",
            "/static/workspace-tabs.css?v=133",
            "/static/organization-admin.css?v=26",
            "/static/app.js?v=314",
            "/static/organization-admin.js?v=32",
            "/static/workspace-tabs.js?v=155",
        ):
            self.assertIn(asset, INDEX)


if __name__ == "__main__":
    unittest.main()
