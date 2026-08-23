from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "organization-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "organization-admin.css").read_text(encoding="utf-8")


class OrganizationAdminCollapsibleTests(unittest.TestCase):
    def test_collapsible_assets_are_cache_busted(self):
        self.assertIn('/static/organization-admin.js?v=16', INDEX)
        self.assertIn('/static/organization-admin.css?v=17', INDEX)

    def test_account_menu_keeps_department_label_and_role_visible(self):
        self.assertIn('id="authUserDepartment"', INDEX)
        self.assertIn('class="auth-user-role" id="authUserRole"', INDEX)
        self.assertIn("grid-template-columns:44px minmax(0,1fr)", STYLE)
        self.assertIn("overflow-wrap:anywhere", STYLE)
        self.assertIn("width:min(420px,calc(100vw - 16px))", STYLE)

    def test_collapsed_account_trigger_only_shows_avatar_and_chevron(self):
        self.assertIn('.auth-user-copy{display:none;', STYLE)
        self.assertIn('class="auth-user-avatar"', INDEX)
        self.assertIn('class="auth-user-chevron"', INDEX)
        self.assertNotIn('.auth-user-copy,.auth-user-chevron{display:none}', STYLE)

    def test_member_sections_have_compact_native_disclosures(self):
        self.assertIn("function detailSection(", SCRIPT)
        self.assertIn('class="organization-section-chevron"', SCRIPT)
        self.assertIn('title: "角色与账号"', SCRIPT)
        self.assertIn("body: account, open: true", SCRIPT)
        self.assertIn('body: organization, open: true', SCRIPT)
        self.assertIn('body: profile, open: true', SCRIPT)
        self.assertIn("data-permission-count", SCRIPT)
        self.assertIn('["Enter", " "].includes(event.key)', SCRIPT)
        self.assertIn("disclosure.open = !disclosure.open", SCRIPT)

    def test_team_footprint_is_a_separate_accessible_tab(self):
        self.assertIn('role="tablist" aria-label="团队管理"', SCRIPT)
        self.assertIn('data-organization-view="control"', SCRIPT)
        self.assertIn('data-organization-view="footprint"', SCRIPT)
        self.assertIn('id="organization-footprint-panel" role="tabpanel"', SCRIPT)
        self.assertIn('function footprintSurface()', SCRIPT)
        self.assertNotIn('title: "个人行动记录"', SCRIPT)
        self.assertIn('.organization-view-tabs button.is-active:after', STYLE)

    def test_member_avatars_open_a_feishu_style_profile_card(self):
        self.assertIn('data-profile-key=', SCRIPT)
        self.assertIn('aria-haspopup="dialog"', SCRIPT)
        self.assertIn('class="organization-profile-card" role="dialog"', SCRIPT)
        self.assertIn('data-profile-close', SCRIPT)
        self.assertIn('event.key === "Escape"', SCRIPT)
        self.assertIn('.organization-avatar-button:focus-visible', STYLE)
        self.assertIn('.organization-profile-card dl', STYLE)
        self.assertIn('@keyframes organization-profile-mobile-enter', STYLE)

    def test_disclosure_controls_have_focus_motion_and_mobile_rules(self):
        self.assertIn(".organization-section-summary:focus-visible", STYLE)
        self.assertIn(".organization-detail-section[open] .organization-section-chevron", STYLE)
        self.assertIn("@keyframes organization-section-enter", STYLE)
        self.assertIn("prefers-reduced-motion:reduce", STYLE)
        self.assertIn(".organization-section-copy{display:grid", STYLE)


if __name__ == "__main__":
    unittest.main()
