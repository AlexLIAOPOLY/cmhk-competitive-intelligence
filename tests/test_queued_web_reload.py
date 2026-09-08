import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QueuedWebReloadTests(unittest.TestCase):
    def test_overlays_retain_prior_release_and_only_replace_selected_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source, state, bins = root / "source", root / "state", root / "bin"
            for directory in (source / "scripts", source / "Codex/agent/skills", bins):
                directory.mkdir(parents=True)
            (source / "scripts/queued_web_app_reload_worker.sh").write_text("#!/bin/bash\nexit 0\n")
            (bins / "launchctl").write_text("#!/bin/bash\nexit 0\n")
            (bins / "launchctl").chmod(0o755)
            queue = (ROOT / "scripts/queue_web_app_reload.sh").read_text()
            queue = queue.replace(f'SOURCE="{ROOT}"', f'SOURCE="{source}"')
            queue = queue.replace('STATE_DIR="$HOME/Library/Application Support/CMHK"', f'STATE_DIR="{state}"')
            queue = queue.replace('LOG_FILE="$HOME/Library/Logs/cmhk_public_crawl/queued-web-reload.log"', f'LOG_FILE="{root}/queue.log"')
            queue = queue.replace('/Users/liaowang/Downloads/模板.docx', str(root / 'absent-template.docx'))
            script = root / "queue.sh"
            script.write_text(queue)
            env = {**os.environ, "PATH": f"{bins}:{os.environ['PATH']}"}

            def submit(*args):
                result = subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                token = (state / "web-reload-requested").read_text().strip()
                return state / "web-reload-releases" / token

            (source / "date-fix.py").write_text("validated date fix")
            (source / "page.css").write_text("original page")
            full = submit()
            (source / "date-fix.py").write_text("unselected work in progress")
            (source / "page.css").write_text("updated page")
            overlay = submit("--overlay-file", "page.css")
            self.assertEqual((overlay / "date-fix.py").read_text(), "validated date fix")
            self.assertEqual((overlay / "page.css").read_text(), "updated page")
            self.assertEqual((full / "page.css").read_text(), "original page")
            (source / "another.py").write_text("another fix")
            chained = submit("--overlay-file", "another.py")
            self.assertEqual((chained / "date-fix.py").read_text(), "validated date fix")
            self.assertEqual((chained / "page.css").read_text(), "updated page")
            self.assertEqual((chained / "another.py").read_text(), "another fix")

            # Missing pending payloads must not silently become a partial release.
            missing = "20260908T000000-1-1"
            (state / "web-reload-requested").write_text(missing + "\n")
            result = subprocess.run(["bash", str(script), "--overlay-file", "page.css"], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((state / "web-reload-requested").read_text().strip(), missing)

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
        self.assertIn("agent_knowledge/requested_overview_010304_2016_2025/", queue)
        self.assertIn("WORKER_COPY", queue)
        self.assertNotIn("/Desktop/", worker)
        self.assertIn('bootstrap "$DOMAIN" "$WEB_PLIST"', worker)
        self.assertIn('kickstart -k "$DOMAIN/$SCHEDULER_LABEL"', worker)
        self.assertIn("running_frequency_pipeline_tasks", worker)
        self.assertIn("running_protected_tasks", worker)
        self.assertIn('"news-selection-agent"', worker)
        self.assertIn('for _bootstrap_attempt in {1..5}', worker)
        self.assertIn('launchctl remove "$QUEUE_LABEL"', worker)
        self.assertIn("web-reload-queue.lock", queue)
        self.assertIn("prune_superseded_releases", queue)
        self.assertIn('prune_superseded_releases "$previous_token" "$request_token"', queue)
        self.assertIn('--overlay-commit', queue)
        self.assertIn('git -C "$SOURCE" show "$overlay_commit:$overlay_file"', queue)
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
        self.assertLess(
            worker.index('/usr/bin/rsync -a "$release_dir/" "$RUNTIME/"'),
            worker.index('kickstart -k "$DOMAIN/$SCHEDULER_LABEL"'),
        )

    def test_worker_fallback_counts_running_protected_tasks(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime = Path(temporary_directory)
            registry = runtime / "agent_knowledge" / "crawl_run_logs" / "index.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                '['
                '{"task_kind": "strategic-news", "run_status": "running"},'
                '{"task_kind": "news-selection-agent", "run_status": "running"},'
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
            self.assertEqual(result.stdout.strip(), "2")

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
