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
        ):
            payload = web_app.build_scheduler_overview(force=True)

        self.assertEqual(payload["configured_rows"], 33)
        self.assertEqual(payload["frequency_counts"], {"daily": 27, "weekly": 3, "monthly": 3, "other": 0})
        self.assertEqual([item["count"] for item in payload["source_groups"]], [17, 3, 4, 9])
        self.assertEqual(payload["latest"]["main_crawl"]["crawl_run_id"], "main")
        self.assertEqual(payload["latest"]["strategic_news"]["crawl_run_id"], "news")
        self.assertEqual(payload["latest"]["four_database_refresh"]["crawl_run_id"], "intel")
        self.assertEqual(payload["pipeline"]["four_databases"], ["local", "international", "cloud", "macro"])
