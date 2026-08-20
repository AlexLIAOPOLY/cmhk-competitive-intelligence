from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "subscription-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "subscription-admin.css").read_text(encoding="utf-8")


class SubscriptionAdminTests(unittest.TestCase):
    def test_workspace_has_real_subscription_admin_tab(self):
        self.assertIn('id="workspace-tab-subscriptions"', INDEX)
        self.assertIn('/static/subscription-admin.html?v=12', INDEX)
        self.assertIn('/static/subscription-admin.js?v=19', (ROOT / "web" / "static" / "subscription-admin.html").read_text(encoding="utf-8"))
        self.assertIn('fetch("/api/subscriptions"', SCRIPT)
        self.assertNotIn("订阅服务 UI DEMO", SCRIPT)

    def test_admin_supports_controlled_delivery_and_mobile_layout(self):
        self.assertIn('action: "publish"', SCRIPT)
        self.assertIn('action: "pushLatest"', SCRIPT)
        self.assertIn("confirmBulk", SCRIPT)
        self.assertIn("推送记录", SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)
        self.assertIn('type: "cmhk-workspace-motion"', SCRIPT)
        self.assertIn('kind: "subscription"', SCRIPT)

    def test_status_feedback_is_a_one_second_animated_top_right_toast(self):
        self.assertIn('class="notice ${esc(state.noticeKind)}"', SCRIPT)
        self.assertIn('scheduleNoticeDismissal()', SCRIPT)
        self.assertIn('}, 1000);', SCRIPT)
        self.assertIn('classList.add("is-leaving")', SCRIPT)
        self.assertIn('.notice { position: fixed;', STYLE)
        self.assertIn('top: 16px; right: 18px;', STYLE)
        self.assertIn('@keyframes notice-enter', STYLE)
        self.assertIn('@keyframes notice-exit', STYLE)
        self.assertIn('.notice.is-leaving', STYLE)

    def test_report_delivery_exposes_supported_modes(self):
        self.assertIn('{ key: "pdf", label: "仅 PDF" }', SCRIPT)
        self.assertIn("PDF 文件", SCRIPT)
        self.assertIn('{ key: "pdf_audio", label: "PDF + 单独语音" }', SCRIPT)
        self.assertIn("PDF + 单独语音", SCRIPT)
        self.assertIn('{ key: "audio", label: "仅语音" }', SCRIPT)
        self.assertIn("仅语音", SCRIPT)
        self.assertIn("报告方式", SCRIPT)

    def test_admin_exposes_real_subscription_frequency_controls(self):
        self.assertIn("data-subscriber-news-frequency", SCRIPT)
        self.assertIn("data-subscriber-news-limit", SCRIPT)
        self.assertIn("newsItemLimit", SCRIPT)
        self.assertIn(".subscriber-table table { min-width: 1120px; }", STYLE)
        self.assertIn("仅当接收人已订阅对应内容且自动排期已启用时推送", SCRIPT)
        self.assertNotIn("data-subscriber-frequency", SCRIPT)
        self.assertIn("每天一次", SCRIPT)
        self.assertIn("每天两次", SCRIPT)
        self.assertNotIn("每天 18:00", SCRIPT)
        self.assertNotIn("每周五 18:00", SCRIPT)

    def test_admin_edits_multi_select_news_interest_categories(self):
        self.assertIn("data-news-category", SCRIPT)
        self.assertIn("newsCategories", SCRIPT)
        self.assertIn("新闻兴趣板块", SCRIPT)
        self.assertIn("至少选择一个兴趣板块", SCRIPT)
        self.assertIn(".news-interest-group", STYLE)
        self.assertIn(".news-interest-check", STYLE)

    def test_automatic_delivery_requires_subscription_and_saved_schedule(self):
        self.assertIn('id="newsScheduleForm"', SCRIPT)
        self.assertIn('action: "updateNewsSchedule"', SCRIPT)
        self.assertIn("仅当接收人已订阅对应内容且自动排期已启用时推送", SCRIPT)
        self.assertIn("执行日先生成当天最新周报", SCRIPT)

    def test_report_schedule_controls_align_without_redundant_helper_copy(self):
        report_form = SCRIPT.split('id="reportScheduleForm"', 1)[1].split("</form>", 1)[0]

        self.assertNotIn("可填写多个日期，以逗号分隔", report_form)
        self.assertNotIn("schedule-meta", report_form)
        self.assertIn(".schedule-form > label { align-self: end; }", STYLE)
        self.assertIn(".schedule-form > label input, .schedule-form > label select, .schedule-form > .schedule-save { height: 36px; min-height: 36px; }", STYLE)

    def test_admin_exposes_report_audio_preference(self):
        self.assertIn("data-subscriber-report-mode", SCRIPT)
        self.assertIn("reportMode", SCRIPT)
        self.assertIn("报告方式", SCRIPT)

    def test_subscriber_names_include_real_avatar_with_initial_fallback(self):
        self.assertIn('${avatar(item, true)}', SCRIPT)
        self.assertIn('class="table-person"', SCRIPT)
        self.assertIn('class="avatar-stack"', SCRIPT)
        self.assertIn('/api/subscriptions/avatar?openId=', SCRIPT)
        self.assertIn('event.target.remove()', SCRIPT)
        self.assertIn('.table-person { display: flex;', STYLE)

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
        self.assertIn("data-invite-chat=", SCRIPT)
        self.assertIn('action: "inviteTarget"', SCRIPT)
        self.assertIn("群内每个人的选择会分别保存", SCRIPT)

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
