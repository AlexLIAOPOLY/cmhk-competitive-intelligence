import unittest

import web_app


class TaskRetryIdentityTests(unittest.TestCase):
    def test_new_report_does_not_inherit_failed_morning_attempts(self):
        for kind in ("weekly-report", "carrier-performance", "audio-generation"):
            with self.subTest(kind=kind):
                tasks = [
                    {
                        "task_id": f"task:{index}",
                        "kind": kind,
                        "title": "生成报告",
                        "scope": "同一报告",
                        "started_at_hkt": f"2026-09-11T{9 + index:02d}:00:00+08:00",
                        "run_status": "failed",
                        "retry_count": count,
                        "recovery_of": "task:0" if index < 4 and count else "task:4" if count else "",
                    }
                    for index, count in enumerate((0, 1, 2, 3, 0, 1))
                ]
                tasks.reverse()
                web_app._annotate_task_retries(tasks)
                self.assertEqual([task["retry_index"] for task in reversed(tasks)], [0, 1, 2, 3, 0, 1])
                self.assertEqual([task["retry_count"] for task in reversed(tasks)], [0, 1, 2, 3, 0, 1])

    def test_recorded_retry_count_survives_midnight_and_partial_history(self):
        tasks = [
            {"kind": "weekly-report", "started_at_hkt": "2026-09-12T00:01:00+08:00", "retry_count": 2},
        ]
        web_app._annotate_task_retries(tasks)
        self.assertEqual(tasks[0]["retry_index"], 2)


if __name__ == "__main__":
    unittest.main()
