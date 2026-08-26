from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
APP = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")
ORGANIZATION = (ROOT / "web/static/organization-admin.js").read_text(encoding="utf-8")
ORGANIZATION_STYLES = (ROOT / "web/static/organization-admin.css").read_text(encoding="utf-8")


class LongListPaginationTests(unittest.TestCase):
    def test_members_have_a_six_row_height_cap_and_pagination(self):
        self.assertIn("memberPage: 1, memberPageSize: 6", ORGANIZATION)
        self.assertIn("users.slice(pageStart, pageStart + state.memberPageSize)", ORGANIZATION)
        self.assertIn('attribute: "data-member-page"', ORGANIZATION)
        self.assertIn("state.memberPage = 1", ORGANIZATION)
        self.assertIn("max-height:648px", ORGANIZATION_STYLES)
        self.assertIn(".organization-pagination", ORGANIZATION_STYLES)

    def test_team_footprint_has_ten_row_pages_and_filter_reset(self):
        self.assertIn("auditPage: 1, auditPageSize: 10", ORGANIZATION)
        self.assertIn("events.slice(pageStart, pageStart + state.auditPageSize)", ORGANIZATION)
        self.assertIn('attribute: "data-audit-page"', ORGANIZATION)
        self.assertIn("state.auditPage = 1", ORGANIZATION)
        self.assertIn("max-height:658px", ORGANIZATION_STYLES)

    def test_weekly_and_performance_files_have_ten_row_pages(self):
        self.assertIn("reportPages: { weekly: 1, performance: 1 }", APP)
        self.assertIn("reportPageSize: 10", APP)
        self.assertIn("files.slice(pageStart, pageStart + state.reportPageSize)", APP)
        self.assertIn('class="report-pagination"', APP)
        self.assertIn('data-report-page="${page + 1}"', APP)
        self.assertIn(".report-pagination", STYLES)

    def test_changed_assets_are_cache_busted(self):
        for asset in (
            "/static/styles.css?v=284",
            "/static/workspace-tabs.css?v=125",
            "/static/organization-admin.css?v=24",
            "/static/app.js?v=306",
            "/static/organization-admin.js?v=26",
            "/static/workspace-tabs.js?v=131",
        ):
            self.assertIn(asset, INDEX)


if __name__ == "__main__":
    unittest.main()
