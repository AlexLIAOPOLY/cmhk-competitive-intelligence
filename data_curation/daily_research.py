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
from . import research_recovery as recovery


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
        trigger="四库资料研究与更新",
        scope=f"六 Agent 最新资料研究（{scheduled_for}）",
        task_kind="four-database-research",
        phase="分配六个研究 Agent",
        progress_detail="03:00 任务已启动，正在并行查找各公司最新资料。",
    )
    registry.append_crawl_run_event(task["stream_log_path"], {
        "type": "log",
        "text": f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [任务启动] {run_id} 已分配六个研究 Agent。",
    })
    for index, assignment in enumerate(research_plan(), start=1):
        companies = "、".join(assignment["companies"])
        registry.append_crawl_run_event(task["stream_log_path"], {
            "type": "log",
            "text": (
                f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [任务分工 {index}/6] "
                f"{assignment['title']}；范围：{companies}（共 {len(assignment['companies'])} 家）；"
                f"目标：{assignment['purpose']}。"
            ),
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


def _append_task_detail(root: Path, task_run_id: str, phase: str, detail: str) -> None:
    """Append detailed evidence without rewriting the shared registry per line."""
    registry = _live_registry(root)
    if registry is None or not task_run_id:
        return
    registry.append_crawl_run_event(
        root / "agent_knowledge" / "crawl_run_logs" / "runs" / f"{task_run_id}.jsonl",
        {
            "type": "log",
            "text": f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [{phase}] {detail}",
        },
    )


def _append_research_result_details(root: Path, task_run_id: str, directory: Path, summary: dict) -> None:
    """Archive one auditable summary per Agent and per researched company."""
    agents = summary.get("agents") if isinstance(summary.get("agents"), list) else []
    _append_task_detail(
        root,
        task_run_id,
        "六Agent研究汇总",
        f"六组结果已归档；新增更新候选 {int(summary.get('accepted') or 0)} 项，"
        f"待最终审核或失败 {int(summary.get('review') or 0)} 项，Agent 结果文件 {len(agents)} 份。",
    )
    for index, agent in enumerate(agents, start=1):
        key = str(agent.get("key") or "")
        try:
            payload = json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        reports = payload.get("reports") if isinstance(payload.get("reports"), list) else []
        items = [item for report in reports for item in (report.get("items") or []) if isinstance(item, dict)]
        statuses: dict[str, int] = {}
        for item in items:
            status = str(item.get("status") or "未标注")
            statuses[status] = statuses.get(status, 0) + 1
        status_text = "、".join(f"{name} {count}" for name, count in sorted(statuses.items())) or "无指标结果"
        _append_task_detail(
            root,
            task_run_id,
            f"Agent结果 {index}/6",
            f"{agent.get('title') or key}已完成；公司 {len(reports)} 家，指标 {len(items)} 项，"
            f"状态分布：{status_text}；完成时间：{agent.get('completed_at') or payload.get('completed_at') or '未记录'}。",
        )
        for company_index, report in enumerate(reports, start=1):
            report_items = [item for item in (report.get("items") or []) if isinstance(item, dict)]
            report_statuses: dict[str, int] = {}
            for item in report_items:
                status = str(item.get("status") or "未标注")
                report_statuses[status] = report_statuses.get(status, 0) + 1
            pages = report.get("pages") if isinstance(report.get("pages"), dict) else {}
            opened = sum(1 for page in pages.values() if isinstance(page, dict) and page.get("opened"))
            cached = sum(1 for page in pages.values() if isinstance(page, dict) and page.get("cache_hit"))
            distribution = "、".join(f"{name} {count}" for name, count in sorted(report_statuses.items())) or "无"
            _append_task_detail(
                root,
                task_run_id,
                f"公司结果 {index}.{company_index}",
                f"{report.get('company') or '未记录公司'}；研究指标 {len(report_items)} 项（{distribution}）；"
                f"资料页 {len(pages)} 个，成功打开 {opened} 个，命中缓存 {cached} 个；"
                f"结果状态：{report.get('status') or '未标注'}。",
            )


def _finish_research_task(root: Path, task_run_id: str, started: float, *, ok: bool,
                          detail: str, summary: dict) -> None:
    registry = _live_registry(root)
    if registry is not None and task_run_id:
        publication = summary.get("publication") if isinstance(summary.get("publication"), dict) else {}
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
                "recovery": summary.get("recovery", {}),
                "retryable_metrics": recovery.retryable_metrics(root / "curation_data/research_runs" / str(summary.get("run_id", ""))),
                "publication": publication,
                "model_analysis": publication.get("model_analysis", {}),
                "pages_publish": publication.get("pages", {}),
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
        if manifest.get("publication"):
            if not manifest.get("recovery") or manifest["recovery"].get("status") == "running":
                if manifest.get("recovery", {}).get("status") == "running":
                    manifest["recovery"]["status"] = "interrupted"
                manifest["recovery"] = recovery.schedule(manifest, directory, reference)
                atomic_write_json(manifest_path, manifest)
            if not recovery.due(manifest, reference):
                return {**result, "ok": manifest["publication"].get("status") == "completed",
                        "due": False, "status": manifest["recovery"]["status"],
                        "recovery": manifest["recovery"]}
        executable = worker_python()
        task = ({"crawl_run_id": launch["task_run_id"]} if manifest and launch.get("task_run_id")
                else _start_research_task(root, run_id, result["scheduled_for"]))
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
        if recovery.cancelled(previous):
            return previous
        from .research_contracts import VERSION
        if (previous.get("publication", {}).get("status") == "completed"
                and previous.get("contract_version") == VERSION and not recovery.retryable_metrics(directory)):
            previous["recovery"] = recovery.schedule(previous, directory, datetime.now(HKT))
            atomic_write_json(manifest_path, previous)
            _finish_research_task(root, task_run_id, task_started, ok=True,
                                  detail="本轮四库资料研究、数据处理与页面发布均已完成。", summary=previous)
            return previous
        summary = previous
        registry = _live_registry(root)
        if previous and registry is not None and task_run_id:
            registry.resume_crawl_run(task_run_id, "恢复四库资料研究与更新", "保留已通过指标，继续失败的审核或发布阶段。")
        if previous.get("publication"):
            summary["recovery"] = {**summary.get("recovery", {}), "status": "running", "next_retry_at": "",
                                   "attempts": int(summary.get("recovery", {}).get("attempts", 0)) + 1}
            atomic_write_json(manifest_path, summary)
        try:
            _append_task_detail(
                root, task_run_id, "执行上下文",
                f"研究编号 {run_id}；工作进程 PID {os.getpid()}；"
                f"断点续跑：{'是' if bool(previous) else '否'}；既有状态：{previous.get('status') or '无'}。",
            )
            _task_heartbeat(root, task_run_id, "六 Agent 研究中", "六个研究 Agent 正在搜索公司最新资料并逐项保存结果。")
            summary = previous if previous.get("status") in {"completed", "partial"} else run_research(
                run_id=run_id, output_dir=directory, resume=bool(previous))
            _append_research_result_details(root, task_run_id, directory, summary)
            final_review = summary.get("final_review") if isinstance(summary.get("final_review"), dict) else {}
            retry_metrics = final_review.get("status") == "completed" and bool(recovery.retryable_metrics(directory))
            from .research_contracts import VERSION
            contract_changed = summary.get("contract_version") != VERSION
            if final_review.get("status") != "completed" or retry_metrics or contract_changed:
                _task_heartbeat(root, task_run_id, "最终审核 Agent 联网核对", "六组研究结果已汇总，正在联网补查失败项并做最终审核。")
                from .research_final_review import review_run
                summary = (review_run(directory, retry_errors=True) if retry_metrics or previous.get("publication")
                           else review_run(directory))
            final_review = summary.get("final_review") if isinstance(summary.get("final_review"), dict) else {}
            _append_task_detail(
                root, task_run_id, "最终审核结果",
                f"审核方式：{final_review.get('execution') or '未记录'}；并行审核工作者 "
                f"{int(final_review.get('workers') or 0)} 个；通过 {int(summary.get('accepted') or 0)} 项；"
                f"待处理或未通过 {int(summary.get('review') or 0)} 项；"
                f"完成时间：{final_review.get('completed_at') or '未记录'}。",
            )
            if (summary.get("research_policy") == "latest_disclosure_incremental_v1" and not summary.get("accepted")
                    and not previous.get("publication") and not contract_changed):
                summary["publication"] = {"status": "partial" if summary.get("review") else "completed", "completed_at": now(),
                    "database_updated": False, "insights": 0,
                    "result_status": "needs_review" if summary.get("review") else "no_new_disclosures",
                    "note": "本轮未形成可写入的新披露，保留现有数据库和页面；待处理或失败记录见研究结果，未重复生成洞察。"}
                summary["recovery"] = recovery.schedule(summary, directory, datetime.now(HKT))
                atomic_write_json(manifest_path, summary)
                _append_task_detail(root, task_run_id, "发布判定", summary["publication"]["note"])
                _finish_research_task(root, task_run_id, task_started, ok=not bool(summary.get("review")),
                                      detail="研究与最终审核已完成；本轮无可写入的新资料，现有四库和页面保持不变。", summary=summary)
                return summary
            summary["publication"] = {"status": "running", "started_at": now()}
            summary["recovery"] = {**(summary.get("recovery") or {}), "status": "running",
                                   "phase": "publication", "error": "", "next_retry_at": ""}
            atomic_write_json(manifest_path, summary)
            _task_heartbeat(root, task_run_id, "四库写入与页面发布", "最终审核已完成，正在写入四库并更新分析页面。")
            _append_task_detail(
                root, task_run_id, "单任务续办",
                "研究、最终审核、四库写入、AI洞察与页面发布继续使用同一任务编号，不再创建刷新子任务。",
            )
            from executive_intelligence_pipeline import run_pipeline_with_recovery
            result = run_pipeline_with_recovery(
                agent_run_id=run_id, curation_summary=summary,
                task_run_id=task_run_id, max_attempts=1, finalize_task=False,
            )
            summary["publication"] = {
                "status": "completed" if result.get("ok") and not result.get("skipped") else "error",
                "task_run_id": task_run_id, "completed_at": now(),
                "database_updated": bool(summary.get("accepted") and result.get("storage_readback", {}).get("ok")),
                "storage_readback": result.get("storage_readback", {}),
                "insights": result.get("model_analysis", {}).get("insights_passed", 0),
                "model_analysis": result.get("model_analysis", {}),
                "domains": result.get("domains", {}), "changes": result.get("ui_value_changes", {}),
                "pages": result.get("pages_publish", {}), "error": result.get("error", ""),
                "result_status": result.get("reason") if result.get("skipped") else result.get("status", ""),
            }
        except Exception as exc:
            summary["publication"] = {"status": "error", "completed_at": now(), "error": str(exc)[:1000]}
            _append_task_detail(root, task_run_id, "任务异常", f"执行链路异常：{str(exc)[:1000]}")
        summary["recovery"] = recovery.schedule(summary, directory, datetime.now(HKT))
        if summary["recovery"]["status"] == "retry_pending":
            _append_task_detail(root, task_run_id, "断点恢复计划",
                                f"{summary['recovery']['error']}；下次 {summary['recovery']['next_retry_at']}；"
                                f"已恢复 {summary['recovery']['attempts']}/{recovery.MAX_ATTEMPTS} 次，已成功指标不重抓。")
        atomic_write_json(manifest_path, summary)
        publication_ok = (summary.get("publication", {}).get("status") == "completed"
                          and summary["recovery"]["status"] == "completed")
        _append_task_detail(
            root, task_run_id, "任务完成" if publication_ok else "任务失败",
            (
                "六Agent研究、最终审核、四库写入、AI洞察、页面发布与回读已在同一任务中完成。"
                if publication_ok else "任务链路未全部通过，已保留分阶段日志与失败原因。"
            ),
        )
        _finish_research_task(
            root, task_run_id, task_started, ok=publication_ok,
            detail=("本轮四库资料研究、数据处理与页面发布均已完成。" if publication_ok
                    else (f"本轮保留成功阶段，等待 {summary['recovery']['next_retry_at']} 自动恢复：{summary['recovery']['error']}"
                          if summary["recovery"]["status"] == "retry_pending" else "本轮未全部完成，已停止自动重试；具体原因见分阶段日志。")),
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
