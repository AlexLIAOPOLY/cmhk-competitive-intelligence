from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "organization-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "organization-admin.css").read_text(encoding="utf-8")


class OrganizationAdminCollapsibleTests(unittest.TestCase):
    def test_collapsible_assets_are_cache_busted(self):
        self.assertIn('/static/organization-admin.js?v=27', INDEX)
        self.assertIn('/static/organization-admin.css?v=25', INDEX)

    def test_member_detail_starts_empty_until_a_member_is_selected(self):
        self.assertIn('selectedUserId: ""', SCRIPT)
        self.assertNotIn('state.selectedUserId = String(state.users[0].id)', SCRIPT)
        self.assertNotIn('const next = users[0]', SCRIPT)
        self.assertIn('class="organization-member-detail is-empty"', SCRIPT)
        self.assertIn('选择成员查看详情', SCRIPT)
        self.assertIn('点击左侧成员，查看资料、角色与功能权限', SCRIPT)
        self.assertIn('data-select-user=', SCRIPT)
        self.assertIn('String(state.selectedUserId) === String(userId) ? "" : userId', SCRIPT)
        self.assertIn('.organization-member-detail.is-empty{display:grid', STYLE)
        self.assertIn('.organization-detail-empty svg', STYLE)

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

    def test_team_footprint_is_a_separate_workspace_tab(self):
        self.assertIn('id="workspace-tab-organization"', INDEX)
        self.assertIn('id="workspace-tab-footprint"', INDEX)
        self.assertIn('data-workspace-tab="footprint"', INDEX)
        self.assertIn('id="workspace-panel-footprint"', INDEX)
        self.assertIn('id="organizationFootprint"', INDEX)
        self.assertNotIn('data-organization-view=', SCRIPT)
        self.assertIn('["organization", "footprint"].includes(event.detail?.tab)', SCRIPT)
        self.assertIn('function footprintSurface()', SCRIPT)
        self.assertNotIn('title: "个人行动记录"', SCRIPT)
        self.assertNotIn('.organization-view-tabs', STYLE)

    def test_member_avatars_open_a_feishu_style_profile_card(self):
        self.assertIn('data-profile-key=', SCRIPT)
        self.assertIn('aria-haspopup="dialog"', SCRIPT)
        self.assertIn('class="organization-profile-card" role="dialog"', SCRIPT)
        self.assertIn('data-profile-close', SCRIPT)
        self.assertIn('event.key === "Escape"', SCRIPT)
        self.assertIn('.organization-avatar-button:focus-visible', STYLE)
        self.assertIn('.organization-profile-card dl', STYLE)
        self.assertIn('@keyframes organization-profile-mobile-enter', STYLE)

    def test_footprint_actions_open_a_detail_card(self):
        self.assertIn('data-event-key=', SCRIPT)
        self.assertIn('class="organization-event-card" role="dialog"', SCRIPT)
        self.assertIn('data-event-close', SCRIPT)
        self.assertIn('.organization-event-button:focus-visible', STYLE)

    def test_subscription_page_changes_and_messages_have_readable_footprint_actions(self):
        self.assertIn('"subscription.settings_update": "修改订阅设置"', SCRIPT)
        self.assertIn('"subscription.news_schedule_update": "修改新闻排期"', SCRIPT)
        self.assertIn('"subscription.invite_send": "发送订阅邀请"', SCRIPT)
        self.assertIn('"subscription.content_send": "发送订阅内容"', SCRIPT)

    def test_footprint_separates_clickable_action_and_target_with_filters(self):
        self.assertIn('<th>动作</th><th>处理对象</th>', SCRIPT)
        self.assertIn('class="organization-event-button is-action"', SCRIPT)
        self.assertIn('function actionIcon(action)', SCRIPT)
        self.assertIn('class="organization-action-icon"', SCRIPT)
        self.assertIn('.organization-event-button.is-action{display:inline-flex', STYLE)
        self.assertIn('class="organization-event-button is-target"', SCRIPT)
        self.assertIn('class="organization-target-person"', SCRIPT)
        self.assertIn('function eventTarget(event)', SCRIPT)
        self.assertIn('request("/api/project-incidents?limit=500")', SCRIPT)
        self.assertIn('追踪编号', SCRIPT)
        self.assertIn('function filteredAudit()', SCRIPT)
        self.assertIn('data-audit-search', SCRIPT)
        self.assertIn('data-audit-action-filter', SCRIPT)
        self.assertIn('data-audit-result-filter', SCRIPT)
        self.assertIn('没有符合筛选条件的团队足迹', SCRIPT)
        self.assertIn('.organization-footprint-toolbar', STYLE)

    def test_disclosure_controls_have_focus_motion_and_mobile_rules(self):
        self.assertIn(".organization-section-summary:focus-visible", STYLE)
        self.assertIn(".organization-detail-section[open] .organization-section-chevron", STYLE)
        self.assertIn("@keyframes organization-section-enter", STYLE)
        self.assertIn("prefers-reduced-motion:reduce", STYLE)
        self.assertIn(".organization-section-copy{display:grid", STYLE)


if __name__ == "__main__":
    unittest.main()
