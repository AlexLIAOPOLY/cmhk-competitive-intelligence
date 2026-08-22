import json
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from subscription_service import (
    SubscriptionService,
    encode_strategic_news_digest,
    strategic_news_card,
    subscription_confirmation_card,
    subscription_entry_card,
)


class FakeLark:
    def __init__(self, *, job_title="经理", leader_open_id=""):
        self.calls = []
        self.job_title = job_title
        self.leader_open_id = leader_open_id

    def __call__(self, argv, timeout=45):
        self.calls.append(list(argv))
        if "api" in argv and "/open-apis/contact/v3/departments/0/children" in argv:
            payload = {"ok": True, "data": {"has_more": False, "items": [{
                "open_department_id": "od-test123", "name": "战略部", "member_count": 1,
                "leader_user_id": self.leader_open_id,
                "status": {"is_deleted": False},
            }]}}
        elif "api" in argv and "/open-apis/contact/v3/users/find_by_department" in argv:
            payload = {"ok": True, "data": {"has_more": False, "items": [{
                "open_id": "ou_delivery123", "union_id": "on_test123",
                "name": "测试用户", "en_name": "测试用户 Test User", "job_title": self.job_title,
                "avatar": {"avatar_72": "https://example.test/avatar.png"},
            }]}}
        elif "api" in argv and "/open-apis/im/v1/chats" in argv:
            payload = {"ok": True, "data": {"has_more": False, "items": [{
                "chat_id": "oc_strategy123", "name": "战略情报群", "description": "每日竞对资讯",
                "chat_mode": "group", "chat_status": "normal", "external": False,
            }, {
                "chat_id": "oc_archived123", "name": "战略旧群", "description": "",
                "chat_mode": "group", "chat_status": "stopped", "external": False,
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
            "strategic_scan_times": ["09:00", "14:00"],
            "bot": {"profile": "cli_test"},
            "subscriptions": {
                "entry_profile": "cli_test",
                "directory_profile": "org_test",
                "delivery_profile": "org_test",
                "primary_delivery_open_id": "ou_delivery123",
                "confirmation_image_keys": {
                    "cli_test": "img_v3_confirmation_test",
                    "org_test": "img_v3_confirmation_test",
                },
                "news_image_keys": {
                    "morning": "img_v3_morning_tea",
                    "afternoon": "img_v3_afternoon_tea",
                },
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
        card = subscription_entry_card(
            image_key="img_v3_subscription_poster",
            recipient_name="Alex LIAO Wang",
        )
        self.assertEqual(card["schema"], "2.0")
        self.assertTrue(card["config"]["update_multi"])
        self.assertEqual(card["header"]["title"]["content"], "订阅战略情报")
        self.assertNotIn("subtitle", card["header"])
        self.assertNotIn("icon", card["header"])
        self.assertNotIn("text_tag_list", card["header"])
        poster = card["body"]["elements"][0]
        self.assertEqual(poster["tag"], "img")
        self.assertEqual(poster["img_key"], "img_v3_subscription_poster")
        intro = card["body"]["elements"][1]
        self.assertEqual(intro["tag"], "markdown")
        self.assertEqual(
            intro["content"],
            "尊敬的 Alex LIAO Wang，您好！我是战略竞对中心管家小竞。"
            "为帮助战略部宣传和推广战略情报产品，您可以按需选择战略双周报、运营商业绩摘要或战略新闻，"
            "报告按后台设定的月度排期自动生成并推送；战略新闻爬虫每日香港时间 09:00 和 14:00 执行，"
            "完成审核后推送，您可以选择每天一次或每天两次。"
            "感谢您的配合！",
        )
        form = next(item for item in card["body"]["elements"] if item["tag"] == "form")
        self.assertEqual(
            [item["content"] for item in form["elements"] if item["tag"] == "markdown" and item["content"].startswith("**")],
            ["**订阅内容**", "**报告接收方式**", "**战略新闻频率**", "**感兴趣的战略新闻板块（可多选）**", "**每次战略新闻条数**"],
        )
        selector = next(item for item in form["elements"] if item["tag"] == "multi_select_static")
        self.assertEqual({item["value"] for item in selector["options"]}, {"weekly", "performance", "news"})
        report_mode = next(item for item in form["elements"] if item.get("name") == "report_mode")
        frequency = next(item for item in form["elements"] if item.get("name") == "news_frequency")
        item_limit = next(item for item in form["elements"] if item.get("name") == "news_item_limit")
        categories = next(item for item in form["elements"] if item.get("name") == "news_categories")
        self.assertEqual({item["value"] for item in report_mode["options"]}, {"pdf", "pdf_audio", "audio"})
        self.assertEqual({item["value"] for item in frequency["options"]}, {"once_daily", "twice_daily"})
        self.assertEqual({item["value"] for item in item_limit["options"]}, {"5", "10", "15", "20"})
        self.assertEqual(len(categories["options"]), 7)
        self.assertTrue(categories["required"])
        self.assertNotIn("frequency", {item.get("name") for item in form["elements"]})
        button = next(item for item in form["elements"] if item["tag"] == "button")
        self.assertEqual(button["form_action_type"], "submit")
        self.assertEqual(button["text"]["content"], "确认订阅")
        pause = next(item for item in card["body"]["elements"] if item.get("behaviors"))
        self.assertEqual(pause["type"], "text")
        self.assertEqual(pause["behaviors"][0]["value"]["action"], "cmhk_subscription_pause_all_v1")

    def test_management_snapshot_exposes_strategic_news_schedule(self):
        self.assertEqual(
            self.service.strategic_news_schedule_snapshot(),
            {
                "service": "news",
                "enabled": False,
                "times": ["09:00", "14:00"],
                "times_text": "09:00 / 14:00",
                "timezone": "Asia/Hong_Kong",
                "timezone_label": "香港时间",
                "dispatch_rule": "爬虫完成审核后推送",
                "updated_at": self.service.strategic_news_schedule_snapshot()["updated_at"],
            },
        )

    def test_subscription_confirmation_is_compact_card_2_receipt(self):
        card = subscription_confirmation_card(
            image_key="img_v3_confirmation_test",
            display_name="Alex LIAO Wang",
            service_labels="战略双周报、战略新闻",
            report_mode_label="PDF + 单独语音",
            frequency_label="每天两次",
            category_labels="竞对动态、政策监管",
            news_item_limit=15,
        )
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["template"], "green")
        self.assertEqual(card["header"]["title"]["content"], "订阅已生效")
        self.assertEqual(card["header"]["text_tag_list"][0]["text"]["content"], "已开启")
        self.assertEqual(card["body"]["elements"][0]["tag"], "img")
        self.assertEqual(card["body"]["elements"][0]["img_key"], "img_v3_confirmation_test")
        text = json.dumps(card, ensure_ascii=False)
        self.assertIn("Alex LIAO Wang，设置完成", text)
        self.assertIn("战略双周报、战略新闻", text)
        self.assertIn("每天两次 · 最新 15 条", text)
        self.assertIn("竞对动态、政策监管", text)

    def test_success_callback_sends_interactive_confirmation_card(self):
        self.service.publish_entry_card(target_id="oc_test123", target_type="chat")
        self.lark.calls.clear()
        self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-card-confirmation",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({
                "services": ["weekly", "news"],
                "report_mode": "pdf_audio",
                "news_frequency": "twice_daily",
                "news_item_limit": "15",
                "news_categories": ["竞对动态", "政策监管"],
            }),
        })
        send_call = next(call for call in self.lark.calls if "+messages-send" in call)
        self.assertEqual(send_call[send_call.index("--msg-type") + 1], "interactive")
        self.assertNotIn("--markdown", send_call)
        card = json.loads(send_call[send_call.index("--content") + 1])
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "订阅已生效")
        self.assertEqual(card["body"]["elements"][0]["img_key"], "img_v3_confirmation_test")
        self.assertIn("每天两次 · 最新 15 条", json.dumps(card, ensure_ascii=False))

    def test_news_schedule_is_paused_by_default_and_can_be_enabled(self):
        self.assertFalse(self.service.strategic_news_schedule_snapshot()["enabled"])
        saved = self.service.update_news_schedule(enabled=True)
        self.assertTrue(saved["enabled"])

    def test_form_callback_persists_identity_and_replaces_services(self):
        self.service.publish_entry_card(target_id="oc_test123", target_type="chat")
        first = self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-1",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({"services": ["weekly", "news"], "report_mode": "pdf_audio", "news_frequency": "daily", "news_item_limit": "15", "news_categories": ["竞对动态", "政策监管"]}),
        })
        self.assertEqual(first["status"], "subscription_saved")
        self.assertEqual(first["services"], ["news", "weekly"])
        self.assertEqual(first["frequency"], "once_daily")
        self.assertEqual(first["news_frequency"], "once_daily")
        self.assertEqual(first["report_cadence"], "biweekly_on_publish")
        self.assertEqual(first["report_mode"], "pdf_audio")
        self.assertEqual(first["news_item_limit"], 15)
        self.assertEqual(first["news_categories"], ["竞对动态", "政策监管"])
        self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-2",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({"services": ["performance"], "report_mode": "pdf", "frequency": "weekly"}),
        })
        summary = self.service.list_summary()
        self.assertEqual(summary["active_subscriber_count"], 1)
        self.assertEqual(summary["subscribers"][0]["services"], ["performance"])
        self.assertEqual(summary["subscribers"][0]["frequency"], "once_daily")
        self.assertEqual(summary["subscribers"][0]["report_mode"], "pdf")
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

    def test_real_card_single_select_arrays_are_accepted(self):
        self.service._send_entry_card_to_user("ou_callback123")
        result = self.service.handle_card_event({
            "type": "card.action.trigger",
            "action_tag": "button",
            "event_id": "event-card-array-values",
            "operator_id": "ou_callback123",
            "chat_id": "oc_test123",
            "message_id": "om_test123",
            "form_value": json.dumps({
                "services": ["weekly", "news"],
                "report_mode": ["pdf_audio"],
                "news_frequency": ["twice_daily"],
                "news_item_limit": ["20"],
                "news_categories": ["市场/产品类", "基础设施/网络/技术类"],
            }),
        })
        self.assertEqual(result["status"], "subscription_saved")
        self.assertEqual(result["frequency"], "twice_daily")
        self.assertEqual(result["report_mode"], "pdf_audio")
        self.assertEqual(result["news_item_limit"], 20)
        self.assertEqual(result["news_categories"], ["市场/产品类", "基础设施/网络/技术类"])
        invitation = self.service.list_summary()["invitations"][0]
        self.assertEqual(invitation["message_id"], "om_test123")
        self.assertEqual(invitation["status"], "accepted")
        self.assertTrue(invitation["responded_at"])

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

    def test_directory_refresh_does_not_infer_position_from_org_relationship(self):
        self.service.command_runner = FakeLark(job_title="", leader_open_id="ou_delivery123")
        self.service.refresh_people_directory()
        self.assertEqual(self.service.search_people_directory("测试")[0]["job_title"], "")

        self.service.command_runner = FakeLark(job_title="经理", leader_open_id="ou_someone_else")
        self.service.refresh_people_directory()
        self.assertEqual(self.service.search_people_directory("测试")[0]["job_title"], "经理")

    def test_chat_search_returns_only_visible_normal_group_matches(self):
        results = self.service.search_chat_directory("战略")
        self.assertEqual([item["name"] for item in results], ["战略情报群"])
        self.assertEqual(results[0]["chat_id"], "oc_strategy123")
        self.assertEqual(self.service.search_chat_directory("不存在"), [])

    def test_admin_invite_target_auto_detects_group_and_sends_group_compatible_card(self):
        with self.assertRaisesRegex(ValueError, "二次确认"):
            self.service.invite_target("oc_strategy123")
        sent = self.service.invite_target("oc_strategy123", confirm_invite=True)
        self.assertEqual(sent["target_type"], "chat")
        self.assertEqual(sent["target_id"], "oc_strategy123")
        self.assertEqual(sent["target_name"], "战略情报群")
        send_call = next(call for call in self.lark.calls if "+messages-send" in call)
        self.assertEqual(send_call[send_call.index("--chat-id") + 1], "oc_strategy123")
        card = json.loads(send_call[send_call.index("--content") + 1])
        self.assertTrue(card["config"]["update_multi"])
        group_invitation = self.service.list_summary()["group_invitations"][0]
        self.assertEqual(group_invitation["target_name"], "战略情报群")
        self.assertEqual(group_invitation["status"], "verified")
        self.assertEqual(group_invitation["response_count"], 0)

    def test_two_people_can_save_different_preferences_from_one_group_card(self):
        self.service.publish_entry_card(target_id="oc_test123", target_type="chat")

        def identity(open_id, *, source_profile=""):
            return {
                "display_name": open_id,
                "callback_open_id": open_id,
                "union_id": f"on_{open_id[3:]}",
                "open_id": open_id,
                "source_profile": source_profile,
                "avatar_url": "",
                "job_title": "",
            }
        with mock.patch.object(self.service, "resolve_user", side_effect=identity):
            for index, (operator_id, categories, item_limit) in enumerate((
                ("ou_persona123", ["竞对动态"], "5"),
                ("ou_personb123", ["政策监管"], "20"),
            ), start=1):
                self.service.handle_card_event({
                    "type": "card.action.trigger",
                    "action_tag": "button",
                    "event_id": f"event-group-{index}",
                    "operator_id": operator_id,
                    "chat_id": "oc_test123",
                    "message_id": "om_test123",
                    "form_value": json.dumps({
                        "services": ["news"],
                        "news_frequency": "once_daily",
                        "report_mode": "pdf",
                        "news_item_limit": item_limit,
                        "news_categories": categories,
                    }),
                })
        subscribers = {item["open_id"]: item for item in self.service.list_summary()["subscribers"]}
        self.assertEqual(set(subscribers), {"ou_persona123", "ou_personb123"})
        self.assertEqual(subscribers["ou_persona123"]["news_categories"], ["竞对动态"])
        self.assertEqual(subscribers["ou_persona123"]["news_item_limit"], 5)
        self.assertEqual(subscribers["ou_personb123"]["news_categories"], ["政策监管"])
        self.assertEqual(subscribers["ou_personb123"]["news_item_limit"], 20)
        self.assertEqual(subscribers["ou_persona123"]["preference_source"], "group_card")
        self.assertEqual(subscribers["ou_personb123"]["preference_message_id"], "om_test123")
        group_invitation = self.service.list_summary()["group_invitations"][0]
        self.assertEqual(group_invitation["status"], "responded")
        self.assertEqual(group_invitation["response_count"], 2)
        self.assertEqual(
            {item["display_name"] for item in group_invitation["responses"]},
            {"ou_persona123", "ou_personb123"},
        )
        with closing(self.service._connect()) as db:
            db.execute("DELETE FROM subscription_group_responses")
            db.commit()
        reloaded = SubscriptionService(runtime_root=self.root, command_runner=self.lark)
        self.assertEqual(reloaded.list_summary()["group_invitations"][0]["response_count"], 2)

    def test_personal_card_still_rejects_a_different_operator(self):
        self.service._send_entry_card_to_user("ou_invited123")
        with self.assertRaisesRegex(ValueError, "受邀人不一致"):
            self.service.handle_card_event({
                "type": "card.action.trigger",
                "action_tag": "button",
                "event_id": "event-wrong-person",
                "operator_id": "ou_someoneelse123",
                "chat_id": "oc_test123",
                "message_id": "om_test123",
                "form_value": json.dumps({
                    "services": ["news"],
                    "news_frequency": "once_daily",
                    "report_mode": "pdf",
                    "news_item_limit": "10",
                    "news_categories": ["竞对动态"],
                }),
            })

    def test_invite_is_selected_only_and_callback_updates_result(self):
        self.service.refresh_people_directory()
        self.service.add_directory_candidates(["ou_delivery123"])
        with self.assertRaisesRegex(ValueError, "二次确认"):
            self.service.invite_users(["ou_delivery123"])
        sent = self.service.invite_users(["ou_delivery123"], confirm_invite=True)
        self.assertEqual(sent["sent_count"], 1)
        send_call = next(call for call in self.lark.calls if "+messages-send" in call)
        card = json.loads(send_call[send_call.index("--content") + 1])
        intro = next(item for item in card["body"]["elements"] if item.get("tag") == "markdown")
        self.assertTrue(intro["content"].startswith("尊敬的 Test User，您好！"))
        self.assertTrue(intro["content"].endswith("感谢您的配合！"))
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
        self.assertEqual(delivery["recipient_name"], "测试用户")
        self.assertEqual(delivery["recipient_open_id"], "ou_delivery123")
        send_call = next(call for call in self.lark.calls if "+messages-send" in call)
        self.assertEqual(send_call[send_call.index("--msg-type") + 1], "interactive")
        self.assertEqual(send_call[send_call.index("--profile") + 1], "org_test")
        self.assertEqual(send_call[send_call.index("--user-id") + 1], "ou_delivery123")
        card = json.loads(send_call[send_call.index("--content") + 1])
        self.assertNotIn("schema", card)
        self.assertEqual(card["header"]["title"]["content"], "真实新闻")
        self.assertIn("经审核的新闻正文", card["elements"][0]["content"])

    def test_strategic_news_card_uses_clean_personal_subscription_format(self):
        items = [{
            "title": f"新闻 {index}", "summary": f"摘要 {index}", "category": "竞对动态",
            "region": "香港本地", "source": "测试来源", "published_at": "2026-08-19T09:00:00+08:00",
            "source_url": f"https://example.test/{index}",
        } for index in range(1, 7)]
        card = strategic_news_card(
            title="  CMHK战略订阅｜6条新闻  ",
            body=encode_strategic_news_digest(items),
            published_at="2026-08-19T10:00:00+08:00",
            image_key="img_v3_morning_tea",
        )
        self.assertEqual(card["header"]["subtitle"]["content"], "截至 2026-08-19 10:00 · 香港时间")
        self.assertEqual(card["elements"][0]["img_key"], "img_v3_morning_tea")
        text = "\n".join(str(item.get("content") or "") for item in card["elements"])
        self.assertIn("**今日关键信号**", text)
        self.assertIn("**竞对动态 · 6 条**", text)
        self.assertIn("**01｜竞对动态 · 香港本地**", text)
        self.assertIn("**06｜竞对动态 · 香港本地**", text)
        self.assertNotIn("###", text)
        self.assertNotIn("已完整列出", json.dumps(card, ensure_ascii=False))

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
        send_call = next(call for call in self.lark.calls if "--file" in call)
        self.assertEqual(
            send_call[send_call.index("--file") + 1],
            "var/subscriptions/outbound/CMHK_战略双周报_测试周报.pdf",
        )
        named_pdf = self.root / "var" / "subscriptions" / "outbound" / "CMHK_战略双周报_测试周报.pdf"
        self.assertEqual(named_pdf.read_bytes(), pdf.read_bytes())

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
        self.assertEqual(
            sends[0][sends[0].index("--file") + 1],
            "var/subscriptions/outbound/CMHK_战略双周报_语音周报.pdf",
        )
        self.assertEqual(
            sends[1][sends[1].index("--audio") + 1],
            "var/subscriptions/outbound/CMHK_战略双周报_语音周报_音频.opus",
        )

    def test_bulk_report_audio_respects_each_subscriber_preference(self):
        from report_pdf_preview import pdf_preview_path

        report = self.root / "偏好周报.docx"
        report.write_bytes(b"docx placeholder")
        pdf = pdf_preview_path(report, self.root / "web" / "static" / "report-previews")
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF-1.7\n")
        audio = self.root / "audio" / "偏好周报.opus"
        audio.parent.mkdir()
        audio.write_bytes(b"OggS")
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["weekly"], report_mode="pdf", frequency="daily"
        )
        pdf_only = self.service.push(
            service="weekly", mode="pdf_audio", path=report.name, confirm_bulk=True
        )
        self.assertEqual(pdf_only["results"][0]["mode"], "pdf")
        self.assertEqual(pdf_only["results"][0]["frequency"], "immediate")
        self.assertEqual(pdf_only["verified_count"], 1)
        self.assertEqual(pdf_only["queued_count"], 0)
        self.assertEqual(len(pdf_only["results"][0]["message_ids"]), 1)
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["weekly"], report_mode="pdf_audio"
        )
        with_audio = self.service.push(
            service="weekly", mode="pdf_audio", path=report.name, confirm_bulk=True
        )
        self.assertEqual(with_audio["results"][0]["mode"], "pdf_audio")
        self.assertEqual(len(with_audio["results"][0]["message_ids"]), 2)
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["weekly"], report_mode="audio"
        )
        audio_only = self.service.push(
            service="weekly", mode="pdf_audio", path=report.name, confirm_bulk=True
        )
        self.assertEqual(audio_only["results"][0]["mode"], "audio")
        self.assertEqual(len(audio_only["results"][0]["message_ids"]), 1)

    def test_bulk_push_requires_explicit_confirmation(self):
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"])
        with self.assertRaisesRegex(ValueError, "二次确认"):
            self.service.push(service="news", mode="text", title="新闻", body="正文")

    def test_manual_push_can_target_one_active_subscriber_without_bulk_confirmation(self):
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"])
        result = self.service.push(
            service="news",
            mode="text",
            title="手动推送",
            body="只发送给指定订阅者",
            target_open_id="ou_delivery123",
        )
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["results"][0]["open_id"], "ou_delivery123")
        self.assertEqual(result["verified_count"], 1)
        with self.assertRaisesRegex(ValueError, "未启用此项服务"):
            self.service.push(
                service="weekly",
                mode="pdf",
                path="missing.docx",
                target_open_id="ou_delivery123",
            )

    def test_news_dispatches_after_crawler_completion_with_daily_limits(self):
        self.service.save_subscriptions(
            "ou_delivery123",
            "测试用户",
            ["news"],
            frequency="once_daily",
        )
        self.service.update_news_schedule(enabled=True)
        item = {"title": "爬虫新闻", "summary": "已完成审核", "source_url": "https://example.test/news"}
        morning = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@07:00",
            slot_label="晨间扫描",
            items=[item],
        )
        afternoon = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@15:00",
            slot_label="午后扫描",
            items=[item],
        )
        self.assertEqual(morning["verified_count"], 1)
        self.assertEqual(afternoon["skipped_count"], 1)
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["news"], frequency="twice_daily"
        )
        next_morning = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-02@07:00", slot_label="晨间扫描", items=[item]
        )
        next_afternoon = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-02@15:00", slot_label="午后扫描", items=[item]
        )
        self.assertEqual(next_morning["verified_count"], 1)
        self.assertEqual(next_afternoon["verified_count"], 1)
        sends = [call for call in self.lark.calls if "+messages-send" in call]
        self.assertEqual(len(sends), 3)

    def test_twice_daily_dispatch_blocks_same_window_after_schedule_change(self):
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["news"], frequency="twice_daily"
        )
        self.service.update_news_schedule(enabled=True)
        item = {"title": "下午茶", "summary": "已完成审核"}

        first = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@13:30",
            slot_label="午后扫描",
            items=[item],
        )
        shifted = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@14:00",
            slot_label="午后扫描",
            items=[item],
        )

        self.assertEqual(first["verified_count"], 1)
        self.assertEqual(shifted["skipped_count"], 1)
        sends = [call for call in self.lark.calls if "+messages-send" in call]
        self.assertEqual(len(sends), 1)
        card = json.loads(sends[0][sends[0].index("--content") + 1])
        self.assertEqual(card["header"]["title"]["content"], "CMHK战略下午茶订阅")
        self.assertEqual(card["elements"][0]["img_key"], "img_v3_afternoon_tea")

    def test_twice_daily_dispatch_honors_legacy_exact_slot_claim(self):
        import sqlite3

        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["news"], frequency="twice_daily"
        )
        self.service.update_news_schedule(enabled=True)
        with sqlite3.connect(self.service.db_path) as db:
            db.execute(
                """INSERT INTO news_crawl_dispatches(
                       open_id, dispatch_key, crawl_slot, crawl_date, frequency,
                       status, created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, 'verified', ?, ?)""",
                (
                    "ou_delivery123", "twice_daily:2099-01-01@13:30",
                    "2099-01-01@13:30", "2099-01-01", "twice_daily",
                    "2099-01-01T13:31:00+08:00", "2099-01-01T13:31:00+08:00",
                ),
            )

        result = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@14:00",
            slot_label="午后扫描",
            items=[{"title": "不应重发"}],
        )

        self.assertEqual(result["skipped_count"], 1)
        self.assertFalse(any("+messages-send" in call for call in self.lark.calls))

    def test_news_dispatch_sorts_globally_and_applies_subscriber_item_limit(self):
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["news"],
            frequency="twice_daily", news_item_limit=5,
        )
        self.service.update_news_schedule(enabled=True)
        items = [
            {
                "title": f"新闻{hour}",
                "published_at": f"2099-01-03T{hour:02d}:00:00+08:00",
                "source_url": f"https://example.test/{hour}",
            }
            for hour in (3, 8, 1, 7, 2, 6, 4, 5)
        ]
        with mock.patch.object(self.service, "_deliver_one", return_value=["om_test123"]) as deliver:
            result = self.service.dispatch_news_after_crawl(
                crawl_slot="2099-01-03@09:00",
                slot_label="晨间扫描",
                items=items,
            )

        body = deliver.call_args.kwargs["body"]
        delivered = json.loads(body.removeprefix("CMHK_NEWS_DIGEST_V1\n"))
        self.assertEqual([item["title"] for item in delivered], ["新闻8", "新闻7", "新闻6", "新闻5", "新闻4"])
        self.assertEqual(deliver.call_args.kwargs["title"], "CMHK战略早茶订阅")
        self.assertEqual(result["results"][0]["news_item_limit"], 5)

    def test_news_dispatch_filters_each_recipient_then_groups_matching_categories(self):
        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["news"],
            frequency="twice_daily", news_item_limit=5,
            news_categories=["竞对动态", "政策监管"],
        )
        self.service.update_news_schedule(enabled=True)
        items = [
            {"title": "最新行业", "category": "行业动态", "published_at": "2099-01-04T12:00:00+08:00"},
            {"title": "最新竞对", "category": "竞对动态", "published_at": "2099-01-04T11:00:00+08:00"},
            {"title": "最新政策", "category": "政策监管", "published_at": "2099-01-04T10:00:00+08:00"},
            {"title": "旧竞对", "category": "竞对动态", "published_at": "2099-01-04T09:00:00+08:00"},
        ]
        with mock.patch.object(self.service, "_deliver_one", return_value=["om_test123"]) as deliver:
            result = self.service.dispatch_news_after_crawl(
                crawl_slot="2099-01-04@14:00",
                slot_label="午后扫描",
                items=items,
            )

        delivered = json.loads(deliver.call_args.kwargs["body"].removeprefix("CMHK_NEWS_DIGEST_V1\n"))
        self.assertEqual([item["title"] for item in delivered], ["最新竞对", "最新政策", "旧竞对"])
        self.assertEqual(deliver.call_args.kwargs["title"], "CMHK战略下午茶订阅")
        self.assertEqual(result["results"][0]["news_categories"], ["竞对动态", "政策监管"])

    def test_existing_subscribers_migrate_to_all_news_categories(self):
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"])
        summary = self.service.list_summary()
        self.assertEqual(len(summary["subscribers"][0]["news_categories"]), 7)
        self.assertEqual(len(summary["news_categories"]), 7)

    def test_news_subscription_rejects_empty_interest_categories(self):
        with self.assertRaisesRegex(ValueError, "兴趣板块"):
            self.service.save_subscriptions(
                "ou_delivery123", "测试用户", ["news"], news_categories=[]
            )

    def test_invalid_frequency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "接收频率无效"):
            self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], frequency="hourly")

    def test_invalid_report_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "报告接收形式无效"):
            self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], report_mode="voice_note")

    def test_invalid_news_item_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "新闻条数无效"):
            self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], news_item_limit=12)

    def test_report_schedule_persists_multiple_month_days_and_hong_kong_time(self):
        from datetime import datetime

        initial = self.service.report_schedule_snapshot(
            now=datetime.fromisoformat("2026-08-19T08:00:00+08:00")
        )
        self.assertFalse(initial["enabled"])
        self.assertEqual(initial["days"], [15, 30])
        saved = self.service.update_report_schedule(days="30，15, 15", time_hm="09:30", enabled=True)
        self.assertEqual(saved["days"], [15, 30])
        self.assertEqual(saved["time"], "09:30")
        self.assertTrue(saved["enabled"])
        snapshot = self.service.report_schedule_snapshot(
            now=datetime.fromisoformat("2026-08-19T08:00:00+08:00")
        )
        self.assertEqual(snapshot["next_run_at"], "2026-08-30T09:30+08:00")

    def test_report_schedule_is_due_once_after_configured_time(self):
        from datetime import datetime

        self.service.update_report_schedule(days=[15, 30], time_hm="09:30", enabled=True)
        before = self.service.report_schedule_due(
            now=datetime.fromisoformat("2026-08-30T09:29:00+08:00")
        )
        due = self.service.report_schedule_due(
            now=datetime.fromisoformat("2026-08-30T09:30:00+08:00")
        )
        self.assertFalse(before["due"])
        self.assertTrue(due["due"])
        self.assertEqual(due["slot"], "2026-08-30@09:30")

    def test_report_schedule_rejects_invalid_days_and_time(self):
        with self.assertRaisesRegex(ValueError, "1 至 31"):
            self.service.update_report_schedule(days="0, 15", time_hm="09:00", enabled=True)
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            self.service.update_report_schedule(days="15, 30", time_hm="25:00", enabled=True)

    def test_due_report_schedule_generates_and_delivers_only_once_per_slot(self):
        from datetime import datetime

        self.service.save_subscriptions(
            "ou_delivery123", "测试用户", ["weekly"], report_mode="pdf"
        )
        self.service.update_report_schedule(days=[30], time_hm="09:30", enabled=True)

        def run_with_generated_report(argv, timeout=45):
            if any("generate_weekly_report.py" in item for item in argv):
                (self.root / "8月30日周报.docx").write_bytes(b"generated")
                return subprocess.CompletedProcess(argv, 0, "generated", "")
            return self.lark(argv, timeout=timeout)

        self.service.command_runner = run_with_generated_report
        now = datetime.fromisoformat("2026-08-30T09:30:00+08:00")
        with mock.patch.object(self.service, "_deliver_one", return_value=["om_scheduled123"]):
            first = self.service.run_due_weekly_report(now=now)
            second = self.service.run_due_weekly_report(now=now)
        self.assertTrue(first["ok"])
        self.assertEqual(first["status"], "verified")
        self.assertEqual(first["report_path"], "8月30日周报.docx")
        self.assertFalse(second["due"])
        self.assertEqual(self.service.report_schedule_snapshot(now=now)["last_slot"], "2026-08-30@09:30")

    def test_due_report_does_not_generate_without_an_active_weekly_subscriber(self):
        from datetime import datetime

        self.service.update_report_schedule(days=[30], time_hm="09:30", enabled=True)
        now = datetime.fromisoformat("2026-08-30T09:30:00+08:00")
        result = self.service.run_due_weekly_report(now=now)
        self.assertEqual(result["skipped"], "no_active_subscribers")
        self.assertFalse(any("generate_weekly_report.py" in item for call in self.lark.calls for item in call))

    def test_due_report_never_falls_back_to_an_old_report(self):
        from datetime import datetime

        (self.root / "旧周报.docx").write_bytes(b"old")
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["weekly"], report_mode="pdf")
        self.service.update_report_schedule(days=[30], time_hm="09:30", enabled=True)

        def successful_but_no_output(argv, timeout=45):
            if any("generate_weekly_report.py" in item for item in argv):
                return subprocess.CompletedProcess(argv, 0, "generated", "")
            return self.lark(argv, timeout=timeout)

        self.service.command_runner = successful_but_no_output
        result = self.service.run_due_weekly_report(
            now=datetime.fromisoformat("2026-08-30T09:30:00+08:00")
        )
        self.assertFalse(result["ok"])
        self.assertIn("本轮新生成", result["error"])
        self.assertFalse(any("+messages-send" in call for call in self.lark.calls))

    def test_news_dispatch_requires_both_schedule_and_active_subscription(self):
        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], frequency="once_daily")
        paused = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@07:00", slot_label="晨间扫描", items=[{"title": "不会发送"}]
        )
        self.assertEqual(paused["skipped"], "schedule_disabled")
        self.assertEqual(paused["recipient_count"], 0)
        self.service.update_news_schedule(enabled=True)
        self.service.update_subscriber(
            "ou_delivery123", services=["news"], status="paused", frequency="once_daily", report_mode="pdf"
        )
        unsubscribed = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@15:00", slot_label="午后扫描", items=[{"title": "仍不发送"}]
        )
        self.assertTrue(unsubscribed["schedule_enabled"])
        self.assertEqual(unsubscribed["recipient_count"], 0)

    def test_failed_crawler_delivery_retries_without_a_fixed_attempt_cap(self):
        from datetime import datetime
        import sqlite3

        self.service.save_subscriptions("ou_delivery123", "测试用户", ["news"], frequency="once_daily")
        self.service.update_news_schedule(enabled=True)

        def offline(argv, timeout=45):
            raise RuntimeError("temporary offline")

        self.service.command_runner = offline
        queued = self.service.dispatch_news_after_crawl(
            crawl_slot="2099-01-01@07:00",
            slot_label="晨间扫描",
            items=[{"title": "重试新闻"}],
        )
        self.assertEqual(queued["retrying_count"], 1)
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
