import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from cmhk.services.news_delivery_dedupe import deduplicate_events, exact_unique, identity_keys
from cmhk.services.news_delivery_guard import deliver_news
from cmhk.services.subscriptions import SubscriptionService, encode_strategic_news_digest


MEETING = {"news_id": "meeting-a", "title": "新皇岗口岸：香港海关与皇岗海关讨论紧急事故应对机制",
           "summary": "香港海关与皇岗海关举行会议，讨论新皇岗口岸应对紧急事故的机制安排。", "category": "公司动态", "published_at": "2026-09-10T08:00:00+08:00", "subscription_preferred": True}
REWRITE = {"news_id": "meeting-b", "title": "新皇岗口岸：香港海关与皇岗海关讨论开通后合作安排",
           "summary": "香港海关与皇岗海关举行工作会议，讨论新皇岗口岸开通后的双方合作安排。", "category": "公司动态", "published_at": "2026-09-10T08:00:00+08:00", "subscription_preferred": True}
DISTINCT = {"news_id": "road", "title": "新皇岗口岸路面湿滑，路政署铺设防滑物料",
            "summary": "香港路政署正为新皇岗口岸湿滑路面铺设防滑物料。", "category": "公司动态", "published_at": "2026-09-10T08:00:00+08:00", "subscription_preferred": True}


def model_result(items):
    return {"decisions": [{"id": f"c{i}", "duplicate_of": "", "reason": "独立事件"} for i in range(len(items))]}


class EventDedupeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_aliases_cover_traditional_chinese_query_order_and_transports(self):
        a = {"news_id": "a", "title": "香港電訊推出新方案", "source_url": "http://www.example.com/n/?b=2&a=1"}
        b = {"record_id": "b", "title": "香港电讯推出新方案", "url": "https://example.com/n?a=1&b=2&utm_source=x#top"}
        self.assertTrue(identity_keys(a) & identity_keys(b))
        self.assertEqual(exact_unique([a, b, {"news_id": "b", "title": "再次改写"}]), [a])

    def test_same_meeting_removed_but_different_event_retained_and_cache_reused(self):
        result = model_result([REWRITE, DISTINCT])
        result["decisions"][0].update(duplicate_of="h0", reason="同一次双方海关会议的不同议题",
                                      evidence="香港海关与皇岗海关举行工作会议", matched_evidence="香港海关与皇岗海关举行会议")
        model = mock.Mock(return_value=result)
        selected, audit = deduplicate_events([REWRITE, DISTINCT], [MEETING], self.root, model_call=model)
        self.assertEqual(selected, [DISTINCT])
        self.assertEqual(len(audit), 2)
        self.assertEqual(deduplicate_events([REWRITE, DISTINCT], [MEETING], self.root, model_call=model)[0], [DISTINCT])
        model.assert_called_once()

    def test_within_card_event_duplicates(self):
        result = model_result([MEETING, REWRITE])
        result["decisions"][1].update(duplicate_of="c0", reason="同一次会议",
                                      evidence=REWRITE["summary"], matched_evidence=MEETING["summary"])
        self.assertEqual(deduplicate_events([MEETING, REWRITE], [], self.root,
                                           model_call=lambda *a, **k: result)[0], [MEETING])

    def test_small_batches_keep_full_prior_events_and_resume_completed_reviews(self):
        calls = []
        fail_second = True
        def model(system, user, **kwargs):
            payload = json.loads(user)
            calls.append(payload)
            result = model_result(payload["candidates"])
            if payload["history"]:
                if fail_second:
                    raise TimeoutError("second batch interrupted")
                result["decisions"][0].update(duplicate_of="h0", reason="同一次会议",
                    evidence=REWRITE["summary"], matched_evidence=MEETING["summary"])
            return result
        items = [MEETING, DISTINCT, {"title": "新的电信资费", "summary": "运营商推出新的电信资费。"},
                 {"title": "新的AI芯片", "summary": "芯片企业发布新的AI芯片。"}, REWRITE]
        with self.assertRaises(TimeoutError):
            deduplicate_events(items, [], self.root, model_call=model)
        fail_second = False
        kept, audit = deduplicate_events(items, [], self.root, model_call=model)
        self.assertEqual(kept, items[:4])
        self.assertEqual(len(calls), 3)  # The completed first chunk was reused.
        self.assertEqual(len(calls[-1]["history"]), 4)
        self.assertEqual(audit[-1]["chunk_start"], 4)

    def test_invalid_or_unavailable_review_never_falls_back_to_sending(self):
        bad = [None, {}, {"decisions": []}, {"decisions": [
            {"id": "c0", "duplicate_of": "c1", "reason": "未来引用"},
            {"id": "c1", "duplicate_of": "c0", "reason": "循环", "evidence": "伪造原文", "matched_evidence": "伪造原文"}]}]
        for result in bad:
            with self.subTest(result=result), self.assertRaises(ValueError):
                deduplicate_events([MEETING, REWRITE], [], self.root, model_call=lambda *a, **k: result)
        with self.assertRaises(TimeoutError):
            deduplicate_events([MEETING, REWRITE], [], self.root, model_call=mock.Mock(side_effect=TimeoutError))

    def test_contradictory_duplicate_verdict_is_rechecked_before_caching(self):
        wrong = model_result([DISTINCT])
        wrong["decisions"][0].update(duplicate_of="h0", reason="主体相同但属于不同事件，不应合并，保留c0",
                                      evidence=DISTINCT["summary"], matched_evidence=MEETING["summary"])
        corrected = model_result([DISTINCT])
        model = mock.Mock(side_effect=[wrong, corrected])
        self.assertEqual(deduplicate_events([DISTINCT], [MEETING], self.root, model_call=model)[0], [DISTINCT])
        self.assertEqual(model.call_count, 2)
        self.assertIn("结论与理由矛盾", model.call_args.args[1])
        self.assertEqual(deduplicate_events([DISTINCT], [MEETING], self.root, model_call=model)[0], [DISTINCT])
        self.assertEqual(model.call_count, 2)

    def test_failed_batch_narrows_to_single_items_with_full_history_and_aliases(self):
        calls = []
        prior = {"title": "另一家企业的新产品", "summary": "另一家企业发布全新产品。"}
        def model(system, user, **kwargs):
            payload = json.JSONDecoder().raw_decode(user)[0]
            calls.append(payload)
            rows = payload["candidates"]
            if len(rows) > 1:
                return {"decisions": []}
            item = rows[0]
            decision = {"id": item["id"], "duplicate_of": "", "reason": "不同事件"}
            self.assertEqual(item["id"], "c0")
            if item["title"] == REWRITE["title"]:
                decision.update(duplicate_of="h1", reason="同一次海关会议",
                                evidence=REWRITE["summary"], matched_evidence=MEETING["summary"])
            return {"decisions": [decision]}
        kept, audit = deduplicate_events([MEETING, REWRITE, DISTINCT], [prior], self.root, model_call=model)
        self.assertEqual(kept, [MEETING, DISTINCT])
        self.assertEqual(audit[1]["duplicate_of"], "c0")
        self.assertEqual([p["id"] for p in calls[-1]["history"]], ["h0", "h1", "h2"])
        self.assertEqual([p["title"] for p in calls[-1]["history"]], [prior["title"], MEETING["title"], REWRITE["title"]])
        self.assertEqual(len(calls), 5)
        deduplicate_events([MEETING, REWRITE, DISTINCT], [prior], self.root, model_call=model)
        self.assertEqual(len(calls), 5)

    def test_uncertain_or_different_event_reason_cannot_delete_a_story(self):
        for reason in ("两条报道的具体事实不同，故判为不同事件。", "不确定是否相同，保留。"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as root:
                wrong = model_result([DISTINCT])
                wrong["decisions"][0].update(duplicate_of="h0", reason=reason,
                    evidence=DISTINCT["summary"], matched_evidence=MEETING["summary"])
                model = mock.Mock(side_effect=[wrong, model_result([DISTINCT])])
                self.assertEqual(deduplicate_events([DISTINCT], [MEETING], Path(root), model_call=model)[0], [DISTINCT])
                self.assertEqual(model.call_count, 2)

    def test_single_item_recovery_checkpoints_completed_work_and_still_fails_closed(self):
        seen = []
        fail = True
        def model(system, user, **kwargs):
            payload = json.JSONDecoder().raw_decode(user)[0]
            rows = payload["candidates"]
            if len(rows) > 1:
                return {"decisions": []}
            identifier = rows[0]["id"]
            seen.append(rows[0]["title"])
            self.assertEqual(identifier, "c0")
            if fail and rows[0]["title"] == DISTINCT["title"]:
                raise TimeoutError("individual review unavailable")
            return {"decisions": [{"id": identifier, "duplicate_of": "", "reason": "不同事件"}]}
        with self.assertRaises(TimeoutError):
            deduplicate_events([MEETING, DISTINCT], [], self.root, model_call=model)
        fail = False
        self.assertEqual(deduplicate_events([MEETING, DISTINCT], [], self.root, model_call=model)[0], [MEETING, DISTINCT])
        self.assertEqual(seen, [MEETING["title"], DISTINCT["title"], DISTINCT["title"]])


class DeliveryGuardTests(unittest.TestCase):
    def setUp(self):
        from tests.news_push_fixtures import prepared_assets
        assets = mock.patch('cmhk.services.news_delivery_guard.prepare_news_assets', side_effect=prepared_assets)
        assets.start()
        self.addCleanup(assets.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        clock = mock.patch("cmhk.services.news_delivery_guard.datetime").start()
        clock.now.return_value = datetime.fromisoformat("2026-09-10T18:00:00+08:00")
        self.addCleanup(mock.patch.stopall)
        self.service = SubscriptionService(runtime_root=self.root)
        self.service.save_subscriptions("ou_test123", "测试用户", ["news"], frequency="twice_daily", news_categories=["公司动态"])
        self.service.update_news_schedule(enabled=True)
        for name, replacement in (
            ("cmhk.services.news_delivery_guard.deduplicate_events", lambda items, history, root: (exact_unique(items, history), [])),
            ("cmhk.services.news_digest_editor.prepare_digest", lambda items, root: {"items": items, "overview": "测试"}),
        ):
            patcher = mock.patch(name, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.send = mock.patch.object(self.service, "_send_interactive_card", return_value="om_test123").start()
        self.verify = mock.patch.object(self.service, "_verify_message").start()
        self.addCleanup(mock.patch.stopall)

    def send_news(self, batch, items, ref="strategic-crawl:2026-09-10@03:00", person="ou_test123"):
        return deliver_news(self.service, open_id=person, content_ref=ref, title="CMHK战略早茶",
                            body=encode_strategic_news_digest(items), batch_id=batch, profile="test")

    def receipt_items(self, batch):
        with sqlite3.connect(self.service.db_path) as db:
            return json.loads(db.execute("SELECT items_json FROM news_delivery_receipts WHERE batch_id=?", (batch,)).fetchone()[0])

    def test_manual_and_automatic_share_history_and_recipients_are_isolated(self):
        self.send_news("manual", [MEETING], ref="人工推送")
        self.send_news("automatic", [MEETING, DISTINCT])
        self.assertEqual(self.receipt_items("automatic"), [DISTINCT])
        self.send_news("other-person", [MEETING], person="ou_another123")
        self.assertEqual(self.receipt_items("other-person"), [MEETING])

    def test_readback_failure_and_restart_never_send_twice(self):
        self.verify.side_effect = RuntimeError("readback unavailable")
        with self.assertRaises(RuntimeError):
            self.send_news("same-batch", [MEETING])
        self.verify.side_effect = None
        self.send_news("same-batch", [MEETING])
        self.send_news("same-batch", [MEETING])
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.verify.call_count, 3)

    def test_transport_retry_reuses_frozen_card_even_after_another_batch(self):
        self.send.side_effect = TimeoutError("uncertain transport")
        with self.assertRaises(TimeoutError):
            self.send_news("uncertain", [MEETING])
        original = self.send.call_args
        self.send.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "待确认"):
            self.send_news("next-batch", [MEETING, DISTINCT])
        self.send_news("uncertain", [DISTINCT])
        self.assertEqual(self.send.call_args, original)
        self.send_news("next-batch", [MEETING, DISTINCT])
        self.assertEqual(self.receipt_items("next-batch"), [DISTINCT])

    def test_repeated_manual_click_is_idempotent_and_new_content_uses_same_history(self):
        args = dict(service="news", mode="text", target_open_id="ou_test123", title="人工战略新闻")
        first = self.service.push(**args, body=encode_strategic_news_digest([MEETING]))
        second = self.service.push(**args, body=encode_strategic_news_digest([MEETING]))
        self.assertEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(self.send.call_count, 1)
        third = self.service.push(**args, body=encode_strategic_news_digest([MEETING, DISTINCT]))
        self.assertNotEqual(third["batch_id"], first["batch_id"])
        self.assertEqual(self.receipt_items(third["batch_id"]), [DISTINCT])

    def test_invalid_digest_fails_without_sending_an_empty_success_card(self):
        with self.assertRaises(ValueError):
            deliver_news(self.service, open_id="ou_test123", content_ref="invalid", title="新闻",
                         body="CMHK_NEWS_DIGEST_V1\n{}", batch_id="invalid", profile="test")
        self.send.assert_not_called()

    def test_simultaneous_recipient_send_cannot_pass_guard(self):
        def nested(*args, **kwargs):
            with self.assertRaisesRegex(RuntimeError, "正在发送"):
                self.send_news("concurrent", [MEETING])
            return "om_test123"
        self.send.side_effect = nested
        self.send_news("first", [MEETING])
        self.assertEqual(self.send.call_count, 1)

    def test_prior_crawl_delivered_today_is_seen_by_todays_round(self):
        self.send_news("late-yesterday", [MEETING], ref="strategic-crawl:2026-09-09@14:00")
        self.send_news("today", [MEETING, DISTINCT])
        self.assertEqual(self.receipt_items("today"), [DISTINCT])

    def test_new_hong_kong_day_still_excludes_yesterdays_delivery(self):
        with mock.patch("cmhk.services.news_delivery_guard.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat("2026-09-10T23:50:00+08:00")
            self.send_news("yesterday", [MEETING])
            clock.now.return_value = datetime.fromisoformat("2026-09-11T08:00:00+08:00")
            self.send_news("tomorrow", [MEETING], ref="strategic-crawl:2026-09-11@03:00")
        self.assertEqual(self.receipt_items("tomorrow"), [])

    def test_existing_afternoon_first_time_is_migrated_to_morning(self):
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("UPDATE subscribers SET frequency='once_daily',news_delivery_times=?",
                       (json.dumps(["16:00", "18:30"]),))
        fresh = SubscriptionService(runtime_root=self.root)
        self.assertEqual(fresh.list_summary()["subscribers"][0]["news_delivery_times"], ["08:00", "18:30"])

    def test_legacy_verified_outbox_is_used_but_future_queue_is_not(self):
        self.service.dispatch_news_after_crawl(crawl_slot="2026-09-10@03:00", slot_label="晨间扫描", items=[MEETING])
        with sqlite3.connect(self.service.db_path) as db:
            db.execute("UPDATE deliveries SET status='verified'")
            db.execute("UPDATE pending_subscription_deliveries SET status='verified',dispatched_at='2026-09-10T08:00:00+08:00'")
        self.service.dispatch_news_after_crawl(crawl_slot="2026-09-10@14:00", slot_label="午后扫描", items=[DISTINCT])
        self.send_news("new-boundary", [MEETING, DISTINCT])
        self.assertEqual(self.receipt_items("new-boundary"), [DISTINCT])

    def test_failed_review_queues_without_sending_and_survives_service_restart(self):
        with mock.patch("cmhk.services.news_delivery_guard.deduplicate_events", side_effect=TimeoutError("review failed")):
            result = self.service.push(service="news", mode="text", target_open_id="ou_test123",
                                       body=encode_strategic_news_digest([MEETING]))
        self.assertEqual(result["queued_count"], 1)
        self.send.assert_not_called()
        SubscriptionService(runtime_root=self.root)
        with sqlite3.connect(self.service.db_path) as db:
            self.assertEqual(db.execute("SELECT status FROM pending_subscription_deliveries").fetchone()[0], "queued")

    def test_once_daily_defaults_to_morning_even_with_afternoon_time(self):
        saved = self.service.save_subscriptions("ou_test123", "测试用户", ["news"], frequency="once_daily", news_delivery_times=["16:00", "18:30"])
        self.assertEqual(saved["news_delivery_times"], ["08:00", "18:30"])
        result = self.service.dispatch_news_after_crawl(crawl_slot="2099-01-01@03:00", slot_label="晨间扫描", items=[MEETING], completed_at="2099-01-01T07:00:00+08:00")
        self.assertEqual(result["results"][0]["due_at"], "2099-01-01T08:00:00+08:00")
        result = self.service.dispatch_news_after_crawl(crawl_slot="2099-01-01@14:00", slot_label="午后扫描", items=[DISTINCT])
        self.assertEqual(result["queued_count"], 0)

    def test_frequency_change_does_not_reclaim_morning_and_cancels_queued_afternoon(self):
        self.service.dispatch_news_after_crawl(crawl_slot="2099-01-01@03:00", slot_label="晨间扫描", items=[MEETING])
        self.service.dispatch_news_after_crawl(crawl_slot="2099-01-01@14:00", slot_label="午后扫描", items=[DISTINCT])
        self.service.save_subscriptions("ou_test123", "测试用户", ["news"], frequency="once_daily")
        repeat = self.service.dispatch_news_after_crawl(crawl_slot="2099-01-01@04:00", slot_label="晨间扫描", items=[MEETING])
        self.assertEqual(repeat["queued_count"], 0)
        with mock.patch.object(self.service, "_deliver_one", return_value=["om_test123"]) as delivery:
            self.service.flush_due(now=datetime.fromisoformat("2099-01-01T20:00:00+08:00"))
        self.assertEqual(delivery.call_count, 1)
        with sqlite3.connect(self.service.db_path) as db:
            self.assertEqual(db.execute("SELECT status FROM pending_subscription_deliveries ORDER BY id DESC LIMIT 1").fetchone()[0], "cancelled")


if __name__ == "__main__":
    unittest.main()
