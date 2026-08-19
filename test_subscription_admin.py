from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "subscription-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "subscription-admin.css").read_text(encoding="utf-8")


class SubscriptionAdminTests(unittest.TestCase):
    def test_workspace_has_real_subscription_admin_tab(self):
        self.assertIn('id="workspace-tab-subscriptions"', INDEX)
        self.assertIn('/static/subscription-admin.html?v=7', INDEX)
        self.assertIn('/static/subscription-admin.js?v=7', (ROOT / "web" / "static" / "subscription-admin.html").read_text(encoding="utf-8"))
        self.assertIn('fetch("/api/subscriptions"', SCRIPT)
        self.assertNotIn("订阅服务 UI DEMO", SCRIPT)

    def test_admin_supports_controlled_delivery_and_mobile_layout(self):
        self.assertIn('action: "publish"', SCRIPT)
        self.assertIn('action: "push"', SCRIPT)
        self.assertIn("confirmBulk", SCRIPT)
        self.assertIn("推送记录", SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)

    def test_report_delivery_is_pdf_only(self):
        self.assertIn('value="pdf"', SCRIPT)
        self.assertIn("PDF 文件", SCRIPT)
        self.assertIn('value="pdf_audio"', SCRIPT)
        self.assertIn("PDF + 单独语音", SCRIPT)
        self.assertIn('value="audio"', SCRIPT)
        self.assertIn("仅语音", SCRIPT)
        self.assertIn("发送前自动命名", SCRIPT)
        self.assertIn("data-outgoing-names", SCRIPT)

    def test_admin_exposes_real_subscription_frequency_controls(self):
        self.assertIn("data-subscriber-news-frequency", SCRIPT)
        self.assertIn("报告随发布推送，新闻随爬虫完成派发", SCRIPT)
        self.assertNotIn("data-subscriber-frequency", SCRIPT)
        self.assertIn("每天一次", SCRIPT)
        self.assertIn("每天两次", SCRIPT)
        self.assertNotIn("每天 18:00", SCRIPT)
        self.assertNotIn("每周五 18:00", SCRIPT)

    def test_admin_exposes_report_audio_preference(self):
        self.assertIn("data-subscriber-report-mode", SCRIPT)
        self.assertIn("reportMode", SCRIPT)
        self.assertIn("报告方式", SCRIPT)

    def test_admin_searches_feishu_people_with_avatar_and_invite_results(self):
        self.assertIn('action: "searchDirectory"', SCRIPT)
        self.assertIn('action: "refreshDirectory"', SCRIPT)
        self.assertIn('action: "addCandidates"', SCRIPT)
        self.assertIn('action: "invite"', SCRIPT)
        self.assertIn("avatar_url", SCRIPT)
        self.assertIn("邀请结果", SCRIPT)
        self.assertIn("confirmInvite", SCRIPT)

    def test_admin_searches_chats_and_highlights_matching_keywords(self):
        self.assertIn("chatSearchResults", SCRIPT)
        self.assertIn("搜索姓名或群聊", SCRIPT)
        self.assertIn('class="search-highlight"', SCRIPT)
        self.assertIn(".search-highlight", STYLE)

    def test_admin_keeps_three_primary_blocks_and_moves_secondary_views_to_icons(self):
        self.assertIn('class="three-block-layout"', SCRIPT)
        self.assertIn('class="surface invite-surface"', SCRIPT)
        self.assertIn('class="surface subscriber-surface"', SCRIPT)
        self.assertIn('class="surface push-surface"', SCRIPT)
        self.assertIn('data-open-people', SCRIPT)
        self.assertIn('data-open-management', SCRIPT)
        self.assertIn('data-drawer-tab="invitations"', SCRIPT)
        self.assertIn('data-drawer-tab="deliveries"', SCRIPT)
        self.assertIn('data-add-candidate=', SCRIPT)
        self.assertIn('class="icon-button add"', SCRIPT)
        self.assertNotIn('class="people-invite-grid"', SCRIPT)
        self.assertIn('.upper-grid', STYLE)


if __name__ == "__main__":
    unittest.main()
