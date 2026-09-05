from unittest import TestCase, mock

import scheduler
import web_app


class SchedulerOverviewTests(TestCase):
    def setUp(self):
        web_app.SCHEDULER_OVERVIEW_CACHE.clear()

    def test_overview_groups_live_rows_and_links_latest_pipeline_runs(self):
        rows = []
        for row in range(2, 35):
            frequency = "每天 03:00"
            if row in {13, 21, 25}:
                frequency = "每周一 03:00"
            elif row in {23, 30, 34}:
                frequency = "每月1日 03:00"
            rows.append({
                "row": row,
                "frequency": frequency,
                "status": "waiting",
                "next_run_hkt": "2026-08-20T03:00:00+08:00",
            })
        history = [
            {"crawl_run_id": "intel", "task_kind": "executive-intelligence-refresh", "run_status": "completed"},
            {"crawl_run_id": "news", "task_kind": "strategic-news", "run_status": "completed"},
            {"crawl_run_id": "main", "trigger": "定时爬虫", "run_status": "completed"},
        ]
        with (
            mock.patch.object(scheduler, "load_state", return_value={}),
            mock.patch.object(scheduler, "due_rows", return_value=([], rows)),
            mock.patch.object(web_app, "load_crawl_run_history", return_value=history),
            mock.patch(
                "strategic_briefing.public_snapshot",
                return_value={"monitor": {"enabled": True, "status": "active"}},
            ),
        ):
            payload = web_app.build_scheduler_overview(force=True)

        self.assertEqual(payload["configured_rows"], 33)
        self.assertEqual(payload["frequency_counts"], {"daily": 27, "weekly": 3, "monthly": 3, "other": 0})
        self.assertEqual([item["count"] for item in payload["source_groups"]], [17, 3, 4, 9])
        self.assertEqual(payload["latest"]["main_crawl"]["crawl_run_id"], "main")
        self.assertEqual(payload["latest"]["strategic_news"]["crawl_run_id"], "news")
        self.assertEqual(payload["latest"]["four_database_refresh"]["crawl_run_id"], "intel")
        self.assertEqual(payload["pipeline"]["four_databases"], ["local", "international", "cloud", "macro"])
        self.assertFalse(payload["strategic_monitor"]["task_visible"])

    def test_overview_exposes_live_strategic_task_progress(self):
        running = {
            "crawl_run_id": "news-running",
            "task_kind": "strategic-news",
            "run_status": "running",
            "phase": "AI批量审核",
            "progress_detail": "正在处理第 12/20 批。",
            "heartbeat_at_hkt": "2026-09-05T11:10:17+08:00",
        }
        with (
            mock.patch.object(scheduler, "load_state", return_value={}),
            mock.patch.object(scheduler, "due_rows", return_value=([], [])),
            mock.patch.object(web_app, "load_crawl_run_history", return_value=[running]),
            mock.patch(
                "strategic_briefing.public_snapshot",
                return_value={"monitor": {"enabled": True, "status": "active"}},
            ),
        ):
            payload = web_app.build_scheduler_overview(force=True)

        monitor = payload["strategic_monitor"]
        self.assertEqual(monitor["status"], "running")
        self.assertTrue(monitor["task_visible"])
        self.assertEqual(monitor["active_task_id"], "news-running")
        self.assertEqual(monitor["active_phase"], "AI批量审核")
        self.assertEqual(monitor["active_heartbeat_at"], "2026-09-05T11:10:17+08:00")

    def test_overview_exposes_scheduler_handoff_before_task_registry_entry(self):
        snapshot = {
            "monitor": {
                "enabled": True,
                "status": "active",
                "latest_scan_slot": {
                    "slot": "2026-09-05@14:00",
                    "status": "starting",
                    "scheduled_for": "2026-09-05T14:00:00+08:00",
                    "at": "2026-09-05T14:00:03+08:00",
                },
            }
        }
        with (
            mock.patch.object(scheduler, "load_state", return_value={}),
            mock.patch.object(scheduler, "due_rows", return_value=([], [])),
            mock.patch.object(web_app, "load_crawl_run_history", return_value=[]),
            mock.patch("strategic_briefing.public_snapshot", return_value=snapshot),
        ):
            payload = web_app.build_scheduler_overview(force=True)

        monitor = payload["strategic_monitor"]
        self.assertEqual(monitor["status"], "starting")
        self.assertTrue(monitor["task_visible"])
        self.assertEqual(monitor["active_task_id"], "slot:2026-09-05@14:00")
        self.assertEqual(monitor["active_phase"], "调度已交接")
