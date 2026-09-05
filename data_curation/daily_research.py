"""03:00 entry point: six researchers, one database writer, one publication."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .research_plan import ARCHITECTURE_VERSION, research_plan
from .six_agent_research import HKT, now, run_research
from .storage import atomic_write_json


ROOT = Path(__file__).resolve().parents[1]


def worker_python() -> str:
    """Use the isolated harness environment on macOS; deployments use their venv."""
    configured = os.environ.get("CMHK_RESEARCH_PYTHON", "").strip()
    candidate = Path(configured) if configured else Path.home() / "Library/Application Support/CMHK/research-venv/bin/python"
    executable = str(candidate) if candidate.is_file() else sys.executable
    check = subprocess.run([executable, "-c", "import deepagents"], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError("研究运行环境缺少 deepagents；请安装 requirements.txt 或运行 scripts/setup_research_harness.sh")
    return executable


def running_worker(pid: int, root: Path) -> bool:
    if pid <= 0:
        return False
    proc = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    command = proc.stdout.strip()
    return proc.returncode == 0 and "data_curation.daily_research" in command and str(root) in command


def dispatch(root: Path, reference: datetime, *, dry_run: bool = False) -> dict:
    reference = reference.astimezone(HKT)
    day = reference.date().isoformat()
    run_id = "research_" + day.replace("-", "")
    directory = root / "curation_data" / "research_runs" / run_id
    result = {"architecture": ARCHITECTURE_VERSION, "run_id": run_id, "scheduled_for": day + "T03:00:00+08:00", "agent_count": 6}
    if reference.hour < 3:
        return {**result, "ok": True, "due": False}
    if dry_run:
        return {**result, "ok": True, "due": True, "dry_run": True, "plan": research_plan()}
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "dispatch.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**result, "ok": True, "skipped": "dispatch_in_progress"}
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        launch_path = directory / "process.json"
        launch = json.loads(launch_path.read_text()) if launch_path.exists() else {}
        if running_worker(int(launch.get("pid") or 0), root):
            return {**result, "ok": True, "status": "running", "pid": launch["pid"]}
        if manifest.get("publication", {}).get("status") in {"completed", "error"}:
            return {**result, "ok": manifest["publication"]["status"] == "completed", "due": False, "status": manifest["publication"]["status"]}
        with (directory / "process.log").open("a") as log:
            process = subprocess.Popen(
                [worker_python(), "-u", "-m", "data_curation.daily_research", "--root", str(root), "--run-id", run_id],
                cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        atomic_write_json(launch_path, {"pid": process.pid, "launched_at": now()})
        return {**result, "ok": True, "due": True, "status": "running", "pid": process.pid}


def execute(root: Path, run_id: str) -> dict:
    import re
    if root.resolve() != ROOT.resolve() or not re.fullmatch(r"research_\d{8}", run_id):
        raise ValueError("运行目录或研究编号不符合定时任务约定")
    directory = root / "curation_data" / "research_runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "execution.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": True, "skipped": "already_running"}
        manifest_path = directory / "manifest.json"
        previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if previous.get("publication", {}).get("status") == "completed":
            return previous
        summary = previous if previous.get("status") in {"completed", "partial"} else run_research(
            run_id=run_id, output_dir=directory, resume=bool(previous))
        summary["publication"] = {"status": "running", "started_at": now()}
        atomic_write_json(manifest_path, summary)
        try:
            from executive_intelligence_pipeline import _start_refresh_task, run_pipeline_with_recovery
            task = _start_refresh_task(agent_run_id=run_id)
            result = run_pipeline_with_recovery(
                agent_run_id=run_id, curation_summary=summary,
                task_run_id=task["crawl_run_id"], max_attempts=1,
            )
            summary["publication"] = {
                "status": "completed" if result.get("ok") and not result.get("skipped") else "error",
                "task_run_id": task["crawl_run_id"], "completed_at": now(),
                "database_updated": bool(result.get("domains")) and not result.get("failed_domains"),
                "insights": result.get("model_analysis", {}).get("insights_passed", 0),
                "domains": result.get("domains", {}), "changes": result.get("ui_value_changes", {}),
                "pages": result.get("pages_publish", {}), "error": result.get("error", ""),
                "result_status": result.get("status", ""),
            }
        except Exception as exc:
            summary["publication"] = {"status": "error", "completed_at": now(), "error": str(exc)[:1000]}
        atomic_write_json(manifest_path, summary)
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = execute(args.root, args.run_id)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("publication", {}).get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
