import fcntl
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cmhk.intelligence import news_review_sheet as review


class ReviewAdmissionTests(unittest.TestCase):
    def test_periodic_cycle_yields_to_real_scan_lock_before_any_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / "monitor.lock").open("a+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                with mock.patch.object(review, "DATA_DIR", root), mock.patch.object(
                    review, "_review_cycle_admission"
                ) as admission:
                    self.assertEqual(review.run_cycle(), {
                        "status": "busy", "reason": "strategic_scan_owns_review"
                    })
                    admission.assert_not_called()
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            with mock.patch.object(review, "DATA_DIR", root):
                self.assertFalse(review._scan_is_running())

    def test_foreground_wait_reports_progress_and_continues_after_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock_path = root / "review.lock"
            with lock_path.open("a+") as owner:
                fcntl.flock(owner.fileno(), fcntl.LOCK_EX)
                callback = mock.Mock()
                with (
                    mock.patch.object(review, "DATA_DIR", root),
                    mock.patch.object(review, "PROCESS_LOCK_PATH", lock_path),
                    mock.patch.object(review.time, "sleep", side_effect=lambda _: fcntl.flock(owner.fileno(), fcntl.LOCK_UN)) as sleep,
                ):
                    with review._review_cycle_admission(force=True, progress_callback=callback) as acquired:
                        self.assertTrue(acquired)
                    sleep.assert_called_once_with(5)
                    self.assertEqual(callback.call_args.args[0], "等待已有审核完成")
                    with review._review_process_lock(wait=False) as acquired:
                        self.assertTrue(acquired)

    def test_periodic_cycle_does_not_wait_for_another_thread(self):
        held = threading.Event()
        release = threading.Event()

        def owner():
            with review._LOCK:
                held.set()
                release.wait(5)

        thread = threading.Thread(target=owner)
        thread.start()
        try:
            self.assertTrue(held.wait(2))
            with mock.patch.object(review.time, "sleep") as sleep:
                with review._review_cycle_admission(force=False) as acquired:
                    self.assertFalse(acquired)
                sleep.assert_not_called()
        finally:
            release.set()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
