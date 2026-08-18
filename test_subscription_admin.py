from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "subscription-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "subscription-admin.css").read_text(encoding="utf-8")


class SubscriptionAdminTests(unittest.TestCase):
    def test_workspace_has_real_subscription_admin_tab(self):
        self.assertIn('id="workspace-tab-subscriptions"', INDEX)
        self.assertIn('/static/subscription-admin.html?v=4', INDEX)
        self.assertIn('fetch("/api/subscriptions"', SCRIPT)
        self.assertNotIn("订阅服务 UI DEMO", SCRIPT)

    def test_admin_supports_controlled_delivery_and_mobile_layout(self):
        self.assertIn('action: "publish"', SCRIPT)
        self.assertIn('action: "push"', SCRIPT)
        self.assertIn("confirmBulk", SCRIPT)
        self.assertIn("推送台账", SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)

    def test_report_delivery_is_pdf_only(self):
        self.assertIn('value="pdf"', SCRIPT)
        self.assertIn("PDF 文件", SCRIPT)
        self.assertIn('value="pdf_audio"', SCRIPT)
        self.assertIn("PDF + 单独语音", SCRIPT)

    def test_admin_exposes_real_subscription_frequency_controls(self):
        self.assertIn("data-subscriber-frequency", SCRIPT)
        self.assertIn("每天 18:00", SCRIPT)
        self.assertIn("每周五 18:00", SCRIPT)
        self.assertIn("等待频率时点", SCRIPT)

    def test_admin_searches_feishu_people_with_avatar_and_invite_results(self):
        self.assertIn('action: "searchPeople"', SCRIPT)
        self.assertIn('action: "refreshDirectory"', SCRIPT)
        self.assertIn('action: "addCandidates"', SCRIPT)
        self.assertIn('action: "invite"', SCRIPT)
        self.assertIn("avatar_url", SCRIPT)
        self.assertIn("邀请结果", SCRIPT)
        self.assertIn("confirmInvite", SCRIPT)

    def test_people_and_invites_use_a_simple_two_pane_layout(self):
        self.assertIn('class="people-invite-grid"', SCRIPT)
        self.assertIn('<h2>人员</h2>', SCRIPT)
        self.assertIn('<h2>邀请</h2>', SCRIPT)
        self.assertIn('data-add-candidate=', SCRIPT)
        self.assertIn('class="icon-button add"', SCRIPT)
        self.assertNotIn('class="kpis"', SCRIPT)
        self.assertNotIn('class="permission-panel"', SCRIPT)
        self.assertNotIn('data-add-candidates', SCRIPT)


if __name__ == "__main__":
    unittest.main()
