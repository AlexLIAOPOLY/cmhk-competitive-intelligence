import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
            worker.index('/usr/bin/rsync -a "$release_dir/" "$RUNTIME/"'),
        )
        self.assertIn("web-reload-releases", queue)
        self.assertIn("WORKER_COPY", queue)
        self.assertNotIn("/Desktop/", worker)
        self.assertIn('bootstrap "$DOMAIN" "$WEB_PLIST"', worker)
        self.assertIn('for _bootstrap_attempt in {1..5}', worker)
        self.assertIn('launchctl remove "$QUEUE_LABEL"', worker)
        self.assertIn("web-reload-queue.lock", queue)
        self.assertIn("prune_superseded_releases", queue)
        self.assertIn('prune_superseded_releases "$previous_token" "$request_token"', queue)
        self.assertIn("web-reload-queue.lock", worker)
        self.assertIn('delete_release_dir "$release_dir"', worker)
        self.assertNotIn('rm -rf "$release_dir"', worker)
        self.assertIn(
            '$RUNTIME/agent_knowledge/crawl_run_logs/index.json', worker
        )
        self.assertIn('task.get("task_kind") or task.get("kind")', worker)
        self.assertLess(
            worker.index('/usr/bin/rsync -a "$release_dir/" "$RUNTIME/"'),
            worker.index('bootstrap "$DOMAIN" "$WEB_PLIST"'),
        )

    def test_worker_fallback_counts_running_strategic_crawl(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime = Path(temporary_directory)
            registry = runtime / "agent_knowledge" / "crawl_run_logs" / "index.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                '['
                '{"task_kind": "strategic-news", "run_status": "running"},'
                '{"task_kind": "strategic-news", "run_status": "completed"},'
                '{"task_kind": "main-crawl", "run_status": "running"}'
                ']',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "bash",
                    "scripts/queued_web_app_reload_worker.sh",
                    "--count-running-strategic",
                ],
                cwd=ROOT,
                env={
                    "HOME": temporary_directory,
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "CMHK_WEB_RUNTIME": temporary_directory,
                    "CMHK_RELOAD_FORCE_INDEX_FALLBACK": "1",
                },
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.stdout.strip(), "1")

    def test_worker_fallback_fails_closed_for_missing_registry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    "bash",
                    "scripts/queued_web_app_reload_worker.sh",
                    "--count-running-strategic",
                ],
                cwd=ROOT,
                env={
                    "HOME": temporary_directory,
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "CMHK_WEB_RUNTIME": temporary_directory,
                    "CMHK_RELOAD_FORCE_INDEX_FALLBACK": "1",
                },
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_worker_fallback_accepts_object_registry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime = Path(temporary_directory)
            registry = runtime / "agent_knowledge" / "crawl_run_logs" / "index.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                '{"tasks": ['
                '{"kind": "strategic-news", "run_status": "running"}'
                ']}',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "bash",
                    "scripts/queued_web_app_reload_worker.sh",
                    "--count-running-strategic",
                ],
                cwd=ROOT,
                env={
                    "HOME": temporary_directory,
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "CMHK_WEB_RUNTIME": temporary_directory,
                    "CMHK_RELOAD_FORCE_INDEX_FALLBACK": "1",
                },
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.stdout.strip(), "1")


if __name__ == "__main__":
    unittest.main()
