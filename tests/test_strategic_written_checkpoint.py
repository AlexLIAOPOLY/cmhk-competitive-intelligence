"""Verified Feishu writes survive downstream failures and process restarts."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import strategic_briefing as briefing
from cmhk.intelligence import news_review_sheet


class WrittenScanCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.slot = "2026-09-03@07:30"
        self.now = datetime(2026, 9, 3, 10, tzinfo=briefing.HKT)
        self.receipt = {"status": "ok", "readback_verified": True,
                        "new_count": 148, "sheet_id": "sheet", "new_items": [{"news_id": "n1"}]}
        self.checkpoint = {"slot": self.slot, "crawl_run_id": "original",
                           "review_result": self.receipt}

    def test_legacy_verified_receipt_is_reused_without_search_or_sheet_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.json"
            sheet.write_text(json.dumps({"successful_cycle_results": {self.slot: self.receipt}}))
            with (mock.patch.object(briefing, "RUNS_DIR", root / "runs"),
                  mock.patch.object(briefing, "DATA_DIR", root),
                  mock.patch.object(news_review_sheet, "STATE_PATH", sheet),
                  mock.patch.object(briefing, "_selection_recovery_parent_run_id", return_value="original"),
                  mock.patch.object(briefing, "_prepare_scan") as prepare,
                  mock.patch.object(news_review_sheet, "run_cycle") as write,
                  mock.patch.object(briefing, "_complete_written_crawl") as complete,
                  mock.patch.object(briefing, "_continue_written_scan", return_value={"continued": True}) as onward):
                result = briefing._run_scan_impl(self.now, self.slot, "晨间扫描", {})
                self.assertEqual(result, {"continued": True})
                prepare.assert_not_called()
                write.assert_not_called()
                self.assertEqual(onward.call_args.kwargs["checkpoint"]["review_result"], self.receipt)
                complete.assert_called_once()
                self.assertTrue(briefing._written_scan_path(self.slot).exists())
                # A later unrelated latest receipt cannot replace this batch.
                sheet.write_text('{}')
                self.assertEqual(briefing._load_written_scan(self.slot)["review_result"], self.receipt)

    def test_unverified_or_other_slot_receipt_does_not_complete_crawl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.json"
            with (mock.patch.object(briefing, "RUNS_DIR", root / "runs"),
                  mock.patch.object(news_review_sheet, "STATE_PATH", sheet)):
                for key, verified in [(self.slot, False), ("2026-09-03@14:00", True)]:
                    sheet.write_text(json.dumps({"successful_cycle_results": {key: {**self.receipt, "readback_verified": verified}}}))
                    self.assertEqual(briefing._load_written_scan(self.slot), {})

    def test_downstream_failure_preserves_success_and_original_task(self):
        original = {"crawl_run_id": "original", "run_status": "completed",
                    "local_files": {"stream_log": "original.jsonl"}}
        with (mock.patch.object(briefing, "_completed_scan_archive", return_value={}),
              mock.patch.object(briefing, "_load_written_scan", return_value=self.checkpoint),
              mock.patch.object(briefing, "load_crawl_run_index", return_value=[original]),
              mock.patch.object(briefing, "start_crawl_run") as start,
              mock.patch.object(briefing, "append_crawl_run_event"),
              mock.patch.object(briefing, "_run_scan_impl", side_effect=RuntimeError("notification unavailable")),
              mock.patch.object(briefing, "finalize_operational_crawl_run") as finalize,
              mock.patch.object(briefing, "amend_operational_crawl_run") as amend):
            with self.assertRaisesRegex(RuntimeError, "notification unavailable"):
                briefing._run_scan(self.now, self.slot, "晨间扫描", {})
            start.assert_not_called()
            finalize.assert_not_called()
            self.assertEqual(amend.call_args.kwargs["summary_updates"]["downstream_status"], "pending")

    def test_crawl_is_completed_before_downstream_begins(self):
        order = []
        with (mock.patch.object(briefing, "_load_written_scan", return_value={}),
              mock.patch.object(briefing, "_prepare_scan", side_effect=lambda *a, **k: order.append("verified_write") or self.checkpoint),
              mock.patch.object(briefing, "_complete_written_crawl", side_effect=lambda *a: order.append("crawl_success")),
              mock.patch.object(briefing, "_continue_written_scan", side_effect=lambda *a, **k: order.append("selection") or {})):
            briefing._run_scan_impl(self.now, self.slot, "晨间扫描", {})
        self.assertEqual(order, ["verified_write", "crawl_success", "selection"])

    def test_notification_survives_slow_or_interrupted_selection_without_resend(self):
        for interruption in (KeyboardInterrupt("process stopped"), RuntimeError("model unavailable")):
            with self.subTest(interruption=type(interruption).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                checkpoint = {
                    **self.checkpoint,
                    "spec": {"spec_hash": "spec", "module_count": 1, "keyword_count": 1, "source_urls": []},
                    "ranked": [], "bridge_stats": {}, "bridge_batch": {},
                    "passed_bridge_signal_ids": [], "gated_items": [], "full_items": [],
                    "gate_reasons": {}, "plans": [], "searched_count": 0,
                    "discovery_result": {"result_count": 1},
                }

                def interrupt_selection(**_kwargs):
                    archived = briefing._completed_scan_archive(self.slot)
                    self.assertEqual(archived["notification_status"], "sent")
                    self.assertEqual(archived["message_ids"], ["om_group"])
                    self.assertEqual(archived["selection_agent"]["status"], "pending")
                    raise interruption

                with (mock.patch.object(briefing, "RUNS_DIR", root / "runs"),
                      mock.patch.object(briefing, "_save_state"),
                      mock.patch.object(briefing, "_load_candidates", return_value=[]),
                      mock.patch.object(briefing, "_save_candidates"),
                      mock.patch.object(briefing, "commit_signal_attempts", return_value={}),
                      mock.patch.object(briefing, "_dispatch_subscription_news_after_scan", return_value={"status": "completed"}),
                      mock.patch.object(briefing, "_send_scan_message", return_value=("om_group", "bot", ["om_group"])) as send,
                      mock.patch.object(briefing, "_append_event"),
                      mock.patch.object(briefing, "_strategic_task_progress"),
                      mock.patch.object(briefing, "amend_operational_crawl_run"),
                      mock.patch.object(news_review_sheet, "pending_selection_batches", return_value=[]),
                      mock.patch("cmhk.intelligence.news_selection_agent.run_news_selection_agent", side_effect=interrupt_selection) as selection):
                    state = {}
                    try:
                        briefing._continue_written_scan(self.now, self.slot, "晨间扫描", state,
                                                        checkpoint=checkpoint, crawl_run_id="original")
                    except KeyboardInterrupt:
                        pass
                    archived = briefing._completed_scan_archive(self.slot)
                    self.assertEqual(archived["task_run_id"], "original")
                    self.assertIn(archived["selection_agent"]["status"], {"pending", "retry_pending"})
                    reused = briefing._run_scan(self.now, self.slot, "晨间扫描", state)
                    self.assertTrue(reused["reused_completed_slot"])
                    send.assert_called_once()
                    selection.assert_called_once()
                    selection.side_effect = None
                    selection.return_value = {"status": "completed", "readback_verified": True,
                                              "task_run_id": "child", "verified_field_count": 2}
                    recovered = briefing._recover_pending_selection_agents(self.now, state)
                    self.assertEqual(len(recovered), 1)
                    self.assertTrue(recovered[0]["no_notification_replay"])
                    send.assert_called_once()
                    self.assertEqual(briefing._completed_scan_archive(self.slot)["selection_agent"]["status"], "completed")
