import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class QueuedWebReloadTests(unittest.TestCase):
    def test_shell_scripts_are_valid(self):
        subprocess.run(
            [
                "bash",
                "-n",
                "start_backend_service.sh",
                "scripts/queue_web_app_reload.sh",
                "scripts/queued_web_app_reload_worker.sh",
            ],
            cwd=ROOT,
            check=True,
        )

    def test_loaded_service_queues_and_returns_instead_of_waiting(self):
        script = (ROOT / "start_backend_service.sh").read_text(encoding="utf-8")
        loaded_branch = script.split("else", 1)[0]
        self.assertIn("scripts/queue_web_app_reload.sh", loaded_branch)
        self.assertNotIn("safe_reload_web_app.sh", loaded_branch)

    def test_worker_coalesces_then_activates_at_idle_or_midnight(self):
        queue = (ROOT / "scripts/queue_web_app_reload.sh").read_text(
            encoding="utf-8"
        )
        worker = (ROOT / "scripts/queued_web_app_reload_worker.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("web-reload-requested", queue)
        self.assertIn("launchctl submit", queue)
        self.assertIn("next_midnight_epoch", worker)
        self.assertIn("wait_until_idle_or_midnight", worker)
        self.assertLess(
            worker.index("wait_until_idle_or_midnight"),
            worker.index('"$SOURCE/sync_app_runtime.sh"'),
        )
        self.assertIn('kickstart -k "$DOMAIN/$WEB_LABEL"', worker)


if __name__ == "__main__":
    unittest.main()
