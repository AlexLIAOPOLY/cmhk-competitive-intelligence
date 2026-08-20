from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "organization-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "organization-admin.css").read_text(encoding="utf-8")


class OrganizationAdminCollapsibleTests(unittest.TestCase):
    def test_collapsible_assets_are_cache_busted(self):
        self.assertIn('/static/organization-admin.js?v=9', INDEX)
        self.assertIn('/static/organization-admin.css?v=9', INDEX)

    def test_member_sections_have_compact_native_disclosures(self):
        self.assertIn("function detailSection(", SCRIPT)
        self.assertIn('class="organization-section-chevron"', SCRIPT)
        self.assertIn('title: "角色与账号"', SCRIPT)
        self.assertIn("body: account, open: true", SCRIPT)
        self.assertIn("data-permission-count", SCRIPT)
        self.assertIn('class="organization-surface organization-audit-surface"', SCRIPT)
        self.assertIn('["Enter", " "].includes(event.key)', SCRIPT)
        self.assertIn("disclosure.open = !disclosure.open", SCRIPT)

    def test_disclosure_controls_have_focus_motion_and_mobile_rules(self):
        self.assertIn(".organization-section-summary:focus-visible", STYLE)
        self.assertIn(".organization-detail-section[open] .organization-section-chevron", STYLE)
        self.assertIn("@keyframes organization-section-enter", STYLE)
        self.assertIn("prefers-reduced-motion:reduce", STYLE)
        self.assertIn(".organization-section-copy{display:grid", STYLE)


if __name__ == "__main__":
    unittest.main()
