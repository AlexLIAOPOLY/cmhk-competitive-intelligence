import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from subscription_service import SubscriptionService, subscription_entry_card


class FakeLark:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, timeout=45):
        self.calls.append(list(argv))
        if "api" in argv and "/open-apis/contact/v3/departments/0/children" in argv:
            payload = {"ok": True, "data": {"has_more": False, "items": [{
                "open_department_id": "od-test123", "name": "战略部", "member_count": 1,
                "status": {"is_deleted": False},
            }]}}
        elif "api" in argv and "/open-apis/contact/v3/users/find_by_department" in argv:
            payload = {"ok": True, "data": {"has_more": False, "items": [{
                "open_id": "ou_delivery123", "union_id": "on_test123",
                "name": "测试用户", "en_name": "Test User", "job_title": "经理",
                "avatar": {"avatar_72": "https://example.test/avatar.png"},
            }]}}
        elif "+get-user" in argv:
            if "union_id" in argv:
                payload = {"ok": True, "data": {"user": {
                    "open_id": "ou_delivery123", "union_id": "on_test123", "name": "测试用户",
                    "avatar": {"avatar_72": "https://example.test/avatar.png"},
                }}}
            else:
                requested = argv[argv.index("--user-id") + 1]
                payload = {"ok": True, "data": {"user": {
                    "open_id": requested, "union_id": "on_test123", "name": "测试用户",
                    "avatar": {"avatar_72": "https://example.test/avatar.png"},
                }}}
        elif "+messages-send" in argv:
            payload = {"ok": True, "data": {"message_id": "om_test123", "chat_id": "oc_test123"}}
        elif "+messages-mget" in argv:
            payload = {"ok": True, "data": {"items": [{"message_id": "om_test123"}]}}
        else:
            payload = {"ok": True, "data": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload, ensure_ascii=False), "")


class SubscriptionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "project_monitor.json").write_text(json.dumps({
            "bot": {"profile": "cli_test"},
            "subscriptions": {
                "entry_profile": "cli_test",
                "directory_profile": "org_test",
                "delivery_profile": "org_test",
                "primary_delivery_open_id": "ou_delivery123",
            },
            "card_actions": {
                "primary_handler_open_id": "ou_test123",
                "primary_handler_expected_name": "测试用户",
            },
            "targets": [
                {"role": "project", "chat_id": "oc_test123", "expected_name": "项目群"},
                {"role": "incident", "chat_id": "oc_incident123", "expected_name": "故障群"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        self.lark = FakeLark()
        self.service = SubscriptionService(runtime_root=self.root, command_runner=self.lark)

    def tearDown(self):
        self.temp.cleanup()

    def test_card_is_card_2_form_with_three_services(self):
        card = subscription_entry_card(image_key="img_v3_subscription_poster")
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "订阅战略情报")
        self.assertNotIn("subtitle", card["header"])
        self.assertNotIn("icon", card["header"])
        self.assertNotIn("text_tag_list", card["header"])
        poster = card["body"]["elements"][0]
        self.assertEqual(poster["tag"], "img")
        self.assertEqual(poster["img_key"], "img_v3_subscription_poster")
        intro = card["body"]["elements"][1]
        self.assertEqual(intro["tag"], "markdown")
        self.assertIn("可订阅的战略情报", intro["content"])
        form = next(item for item in card["body"]["elements"] if item["tag"] == "form")
        self.assertEqual([item["content"] for item in form["elements"] if item["tag"] == "markdown"], ["**订阅内容**", "**接收频率**"])
        selector = next(item for item in form["elements"] if item["tag"] == "multi_select_static")
        self.assertEqual({item["value"] for item in selector["options"]}, {"weekly", "performance", "news"})
        frequency = next(item for item in form["elements"] if item["tag"] == "select_static")
        self.assertEqual(frequency["name"], "frequency")
        self.assertEqual({item["value"] for item in frequency["options"]}, {"immediate", "daily", "weekly"})
        button = next(item for item in form["elements"] if item["tag"] == "button")
        self.assertEqual(button["form_action_type"], "submit")
        self.assertEqual(button["text"]["content"], "确认订阅")
        pause = next(item for item in card["body"]["elements"] if item.get("behaviors"))
        self.assertEqual(pause["type"], "text")
        self.assertEqual(pause["behaviors"][0]["value"]["action"], "cmhk_subscription_pause_all_v1")

    def test_form_callback_persists_identity_and_replaces_services(self):
        self.service.publish_entry_card(target_id="oc_test123", target_type="chat")
        first = self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-1",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({"services": ["weekly", "news"], "frequency": "daily"}),
        })
        self.assertEqual(first["status"], "subscription_saved")
        self.assertEqual(first["services"], ["news", "weekly"])
        self.assertEqual(first["frequency"], "daily")
        self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-2",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({"services": ["performance"], "frequency": "weekly"}),
        })
        summary = self.service.list_summary()
        self.assertEqual(summary["active_subscriber_count"], 1)
        self.assertEqual(summary["subscribers"][0]["services"], ["performance"])
        self.assertEqual(summary["subscribers"][0]["frequency"], "weekly")
        counts = {item["key"]: item["subscriber_count"] for item in summary["services"]}
        self.assertEqual(counts["performance"], 1)

        paused = self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "action_value": json.dumps({"action": "cmhk_subscription_pause_all_v1"}),
            "event_id": "event-3",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
        })
        self.assertEqual(paused["status"], "subscription_paused")
        self.assertEqual(self.service.list_summary()["active_subscriber_count"], 0)

    def test_unpublished_subscription_card_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "受控卡片"):
            self.service.handle_card_event({
                "type": "card.action.trigger",
                "action_tag": "button",
                "event_id": "event-forged",
                "operator_id": "ou_callback123",
                "chat_id": "oc_test123",
                "message_id": "om_unpublished123",
                "form_value": json.dumps({"services": ["news"], "frequency": "immediate"}),
            })

    def test_publish_is_whitelisted_and_read_back(self):
        result = self.service.publish_entry_card(target_id="oc_test123", target_type="chat")
        self.assertTrue(result["verified"])
        self.assertTrue(any("+messages-mget" in call for call in self.lark.calls))
        with self.assertRaises(ValueError):
            self.service.publish_entry_card(target_id="oc_incident123", target_type="chat")

    def test_directory_search_returns_avatar_and_adds_controlled_candidate(self):
        refreshed = self.service.refresh_people_directory()
        self.assertEqual(refreshed["people_count"], 1)
        results = self.service.search_people_directory("测试")
        self.assertEqual(results[0]["avatar_url"], "https://example.test/avatar.png")
        self.assertEqual(results[0]["department_names"], ["战略部"])
        self.assertEqual(self.service.invitation_permission_snapshot()["people_count"], 1)
        self.assertEqual(self.service.invitation_permission_snapshot()["status"], "ready")
        added = self.service.add_directory_candidates(["ou_delivery123"])
        self.assertEqual(added["added_count"], 1)
        self.assertEqual(added["candidates"][0]["display_name"], "测试用户")

    def test_invite_is_selected_only_and_callback_updates_result(self):
        self.service.refresh_people_directory()
        self.service.add_directory_candidates(["ou_delivery123"])
        with self.assertRaisesRegex(ValueError, "二次确认"):
            self.service.invite_users(["ou_delivery123"])
        sent = self.service.invite_users(["ou_delivery123"], confirm_invite=True)
        self.assertEqual(sent["sent_count"], 1)
        self.assertEqual(self.service.list_summary()["invitations"][0]["status"], "pending")
        accepted = self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-invite-accept",
            "operator_id": "ou_delivery123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({"services": ["news"], "frequency": "daily"}),
        })
        self.assertEqual(accepted["status"], "subscription_saved")
        invitation = self.service.list_summary()["invitations"][0]
        self.assertEqual(invitation["status"], "accepted")
        self.assertTrue(invitation["responded_at"])

    def test_invite_rejects_person_outside_controlled_candidates(self):
        with self.assertRaisesRegex(ValueError, "受控名单"):
            self.service.invite_users(["ou_unknown123"], confirm_invite=True)

    def test_news_test_push_is_logged_and_verified(self):
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"])
        result = self.service.push(
            service="news",
            mode="text",
            title="真实新闻",
            body="经审核的新闻正文",
            test_open_id="ou_test123",
        )
        self.assertEqual(result["verified_count"], 1)
        delivery = self.service.list_summary()["deliveries"][0]
        self.assertEqual(delivery["status"], "verified")
        self.assertEqual(delivery["service"], "news")

    def test_report_test_push_sends_pdf_and_reads_it_back(self):
        from report_pdf_preview import pdf_preview_path

        report = self.root / "测试周报.docx"
        report.write_bytes(b"docx placeholder")
        pdf = pdf_preview_path(report, self.root / "web" / "static" / "report-previews")
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF-1.7\n")
        result = self.service.push(
            service="weekly",
            mode="pdf",
            path=report.name,
            test_open_id="ou_test123",
        )
        self.assertEqual(result["verified_count"], 1)
        self.assertTrue(any("--file" in call and str(pdf.relative_to(self.root)) in call for call in self.lark.calls))

    def test_reports_reject_non_pdf_delivery_modes(self):
        report = self.root / "测试周报.docx"
        report.write_bytes(b"docx placeholder")
        with self.assertRaisesRegex(ValueError, "只支持 PDF"):
            self.service.push(service="weekly", mode="text", path=report.name, test_open_id="ou_test123")

    def test_report_audio_is_a_separate_message_after_pdf(self):
        from report_pdf_preview import pdf_preview_path

        report = self.root / "语音周报.docx"
        report.write_bytes(b"docx placeholder")
        pdf = pdf_preview_path(report, self.root / "web" / "static" / "report-previews")
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF-1.7\n")
        audio = self.root / "audio" / "语音周报.opus"
        audio.parent.mkdir()
        audio.write_bytes(b"OggS")
        result = self.service.push(
            service="weekly",
            mode="pdf_audio",
            path=report.name,
            test_open_id="ou_test123",
        )
        self.assertEqual(len(result["results"][0]["message_ids"]), 2)
        sends = [call for call in self.lark.calls if "+messages-send" in call]
        self.assertIn("--file", sends[0])
        self.assertIn("--audio", sends[1])

    def test_bulk_push_requires_explicit_confirmation(self):
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"])
        with self.assertRaisesRegex(ValueError, "二次确认"):
            self.service.push(service="news", mode="text", title="新闻", body="正文")

    def test_daily_frequency_queues_then_dispatches_when_due(self):
        from datetime import datetime

        self.service.save_subscriptions(
            "ou_delivery123",
            "测试用户",
            ["news"],
            frequency="daily",
        )
        queued = self.service.push(
            service="news",
            mode="text",
            title="延时新闻",
            body="按订阅频率投递",
            confirm_bulk=True,
        )
        self.assertEqual(queued["queued_count"], 1)
        self.assertEqual(queued["verified_count"], 0)
        self.assertFalse(any("+messages-send" in call for call in self.lark.calls))
        dispatched = self.service.flush_due(now=datetime.fromisoformat("2099-01-01T19:00:00+08:00"))
        self.assertEqual(dispatched["verified_count"], 1)
        self.assertTrue(any("+messages-send" in call for call in self.lark.calls))
        self.assertEqual(self.service.list_summary()["deliveries"][0]["status"], "verified")

    def test_invalid_frequency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "接收频率无效"):
            self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], frequency="hourly")

    def test_failed_scheduled_delivery_retries_without_a_fixed_attempt_cap(self):
        from datetime import datetime
        import sqlite3

        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], frequency="daily")
        self.service.push(
            service="news",
            mode="text",
            title="重试新闻",
            body="网络恢复后继续发送",
            confirm_bulk=True,
        )

        def offline(argv, timeout=45):
            raise RuntimeError("temporary offline")

        self.service.command_runner = offline
        first = self.service.flush_due(now=datetime.fromisoformat("2099-01-01T19:00:00+08:00"))
        second = self.service.flush_due(now=datetime.fromisoformat("2099-01-01T20:00:00+08:00"))
        self.assertEqual(first["retrying_count"], 1)
        self.assertEqual(second["retrying_count"], 1)
        db = sqlite3.connect(self.service.db_path)
        try:
            status, attempts = db.execute(
                "SELECT status, attempts FROM pending_subscription_deliveries"
            ).fetchone()
            delivery_status = db.execute("SELECT status FROM deliveries").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(status, "queued")
        self.assertEqual(attempts, 2)
        self.assertEqual(delivery_status, "retrying")

    def test_long_report_paragraphs_are_split_below_message_limit(self):
        chunks = self.service._text_chunks("长报告", "甲" * 12000)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 5800 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
