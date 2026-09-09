"""03:00 entry point: six researchers, one database writer, one publication."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .research_plan import ARCHITECTURE_VERSION, research_plan
from .six_agent_research import HKT, now, run_research
from .storage import atomic_write_json


ROOT = Path(__file__).resolve().parents[1]


def _live_registry(root: Path):
    """Return the operational registry only for its own deployed workspace."""
    from cmhk.crawl import run_registry
    return run_registry if run_registry.ROOT.resolve() == root.resolve() else None


def _start_research_task(root: Path, run_id: str, scheduled_for: str) -> dict:
    registry = _live_registry(root)
    if registry is None:
        return {}
    task = registry.start_crawl_run(
        trigger="03:00 四库资料研究与更新",
        scope=f"六 Agent 最新资料研究（{scheduled_for}）",
        task_kind="four-database-research",
        phase="分配六个研究 Agent",
        progress_detail="03:00 任务已启动，正在并行查找各公司最新资料。",
    )
    registry.append_crawl_run_event(task["stream_log_path"], {
        "type": "log",
        "text": f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [任务启动] {run_id} 已分配六个研究 Agent。",
    })
    return task


def _research_task_id(root: Path, directory: Path, run_id: str) -> str:
    launch_path = directory / "process.json"
    try:
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        launch = {}
    task_run_id = str(launch.get("task_run_id") or "")
    if task_run_id or _live_registry(root) is None:
        return task_run_id
    task = _start_research_task(root, run_id, run_id.removeprefix("research_"))
    task_run_id = str(task.get("crawl_run_id") or "")
    if task_run_id:
        atomic_write_json(launch_path, {**launch, "pid": os.getpid(), "task_run_id": task_run_id,
                                        "launched_at": launch.get("launched_at") or now()})
    return task_run_id


def _task_heartbeat(root: Path, task_run_id: str, phase: str, detail: str) -> None:
    registry = _live_registry(root)
    if registry is not None and task_run_id:
        registry.heartbeat_crawl_run(task_run_id, phase, detail, worker_pid=os.getpid())


def _finish_research_task(root: Path, task_run_id: str, started: float, *, ok: bool,
                          detail: str, summary: dict) -> None:
    registry = _live_registry(root)
    if registry is not None and task_run_id:
        registry.finalize_operational_crawl_run(
            task_run_id,
            ok=ok,
            duration_ms=int((time.monotonic() - started) * 1000),
            progress_detail=detail,
            failure_stage="" if ok else "daily_research",
            summary={
                "agent_run_id": summary.get("run_id", ""),
                "accepted": summary.get("accepted", 0),
                "review": summary.get("review", 0),
                "publication": summary.get("publication", {}),
            },
        )


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


def active_dispatch(root: Path, reference: datetime) -> dict:
    """Describe today's dispatched worker without launching another process."""
    day = reference.astimezone(HKT).date().isoformat()
    run_id = "research_" + day.replace("-", "")
    launch_path = root / "curation_data" / "research_runs" / run_id / "process.json"
    try:
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pid = int(launch.get("pid") or 0)
    if not running_worker(pid, root):
        return {}
    return {
        "ok": True,
        "due": True,
        "status": "running",
        "run_id": run_id,
        "scheduled_for": day + "T03:00:00+08:00",
        "agent_count": 6,
        "pid": pid,
        "task_run_id": str(launch.get("task_run_id") or ""),
    }


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
            return {**result, "ok": True, "status": "running", "pid": launch["pid"],
                    "task_run_id": launch.get("task_run_id", "")}
        if manifest.get("publication", {}).get("status") in {"completed", "error"}:
            return {**result, "ok": manifest["publication"]["status"] == "completed", "due": False, "status": manifest["publication"]["status"]}
        executable = worker_python()
        task = _start_research_task(root, run_id, result["scheduled_for"])
        try:
            with (directory / "process.log").open("a") as log:
                process = subprocess.Popen(
                    [executable, "-u", "-m", "data_curation.daily_research", "--root", str(root), "--run-id", run_id],
                    cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
        except Exception as exc:
            task_run_id = str(task.get("crawl_run_id") or "")
            if task_run_id:
                _finish_research_task(root, task_run_id, time.monotonic(), ok=False,
                                      detail=f"研究进程启动失败：{str(exc)[:300]}", summary={"run_id": run_id})
            raise
        task_run_id = str(task.get("crawl_run_id") or "")
        atomic_write_json(launch_path, {"pid": process.pid, "launched_at": now(), "task_run_id": task_run_id})
        if task_run_id:
            _task_heartbeat(root, task_run_id, "六 Agent 研究中", "六个研究 Agent 已启动，正在搜索并核对公司最新资料。")
        return {**result, "ok": True, "due": True, "status": "running", "pid": process.pid,
                "task_run_id": task_run_id}


def execute(root: Path, run_id: str) -> dict:
    import re
    if root.resolve() != ROOT.resolve() or not re.fullmatch(r"research_\d{8}(?:_rerun_\d{6})?", run_id):
        raise ValueError("运行目录或研究编号不符合定时任务约定")
    directory = root / "curation_data" / "research_runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    task_started = time.monotonic()
    with (directory / "execution.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": True, "skipped": "already_running"}
        task_run_id = _research_task_id(root, directory, run_id)
        manifest_path = directory / "manifest.json"
        previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if previous.get("publication", {}).get("status") == "completed":
            _finish_research_task(root, task_run_id, task_started, ok=True,
                                  detail="本轮四库资料研究、数据处理与页面发布均已完成。", summary=previous)
            return previous
        summary = previous
        try:
            _task_heartbeat(root, task_run_id, "六 Agent 研究中", "六个研究 Agent 正在搜索公司最新资料并逐项保存结果。")
            summary = previous if previous.get("status") in {"completed", "partial"} else run_research(
                run_id=run_id, output_dir=directory, resume=bool(previous))
            _task_heartbeat(root, task_run_id, "最终审核 Agent 联网核对", "六组研究结果已汇总，正在联网补查失败项并做最终审核。")
            from .research_final_review import review_run
            summary = review_run(directory)
            if summary.get("research_policy") == "latest_disclosure_incremental_v1" and not summary.get("accepted"):
                summary["publication"] = {"status": "completed", "completed_at": now(),
                    "database_updated": False, "insights": 0,
                    "result_status": "needs_review" if summary.get("review") else "no_new_disclosures",
                    "note": "本轮未形成可写入的新披露，保留现有数据库和页面；待处理或失败记录见研究结果，未重复生成洞察。"}
                atomic_write_json(manifest_path, summary)
                _finish_research_task(root, task_run_id, task_started, ok=True,
                                      detail="研究与最终审核已完成；本轮无可写入的新资料，现有四库和页面保持不变。", summary=summary)
                return summary
            summary["publication"] = {"status": "running", "started_at": now()}
            atomic_write_json(manifest_path, summary)
            _task_heartbeat(root, task_run_id, "四库写入与页面发布", "最终审核已完成，正在写入四库并更新分析页面。")
            from executive_intelligence_pipeline import _start_refresh_task, run_pipeline_with_recovery
            task = _start_refresh_task(agent_run_id=run_id, parent_crawl_run_id=task_run_id)
            result = run_pipeline_with_recovery(
                agent_run_id=run_id, curation_summary=summary,
                task_run_id=task["crawl_run_id"], max_attempts=1,
            )
            summary["publication"] = {
                "status": "completed" if result.get("ok") and not result.get("skipped") else "error",
                "task_run_id": task["crawl_run_id"], "completed_at": now(),
                "database_updated": bool(result.get("domains")) and not result.get("failed_domains"),
                "insights": result.get("model_analysis", {}).get("insights_passed", 0),
                "model_analysis": result.get("model_analysis", {}),
                "domains": result.get("domains", {}), "changes": result.get("ui_value_changes", {}),
                "pages": result.get("pages_publish", {}), "error": result.get("error", ""),
                "result_status": result.get("status", ""),
            }
        except Exception as exc:
            summary["publication"] = {"status": "error", "completed_at": now(), "error": str(exc)[:1000]}
        atomic_write_json(manifest_path, summary)
        publication_ok = summary.get("publication", {}).get("status") == "completed"
        _finish_research_task(
            root, task_run_id, task_started, ok=publication_ok,
            detail=("本轮四库资料研究、数据处理与页面发布均已完成。" if publication_ok
                    else "研究任务已结束，但四库写入或页面发布失败；请查看任务日志。"),
            summary=summary,
        )
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
