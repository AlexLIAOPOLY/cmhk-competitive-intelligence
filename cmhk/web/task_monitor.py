from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import subprocess
import threading

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def _task_incident_metadata() -> dict[str, dict]:
        try:
            monitor_state = app.json.loads(app.PROJECT_MONITOR_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            monitor_state = {}
        incidents = monitor_state.get("incidents") if isinstance(monitor_state, dict) else {}
        incidents = incidents if isinstance(incidents, dict) else {}

        handlers = app._project_monitor_handlers()

        severity_labels = {"P1": "紧急", "P2": "高", "P3": "中"}
        metadata: dict[str, dict] = {}
        for incident in incidents.values():
            if not isinstance(incident, dict):
                continue
            condition_key = str(incident.get("condition_key") or "")
            if not condition_key:
                continue
            incident_id = str(incident.get("incident_id") or "")
            handled = handlers.get(incident_id, {})
            severity = str(incident.get("severity") or "")
            metadata[condition_key] = {
                "incident_id": incident_id,
                "incident_status": str(incident.get("status") or ""),
                "severity": severity,
                "severity_label": severity_labels.get(severity, ""),
                **app._handler_public_fields(handled),
            }
        return metadata

    publish(app, _task_incident_metadata)

    def _annotate_task_incidents(tasks: list[dict]) -> None:
        metadata = app._task_incident_metadata()
        for task in tasks:
            task_id = str(task.get("task_id") or task.get("task_run_id") or "")
            run_id = str(task.get("task_run_id") or task_id.removeprefix("crawl:"))
            prefixes = ("crawl-task-failed", "crawl-task-stuck") if task_id.startswith("crawl:") else ("general-task-failed", "general-task-stuck")
            keys = [f"{prefix}:{run_id if prefix.startswith('crawl-') else task_id}" for prefix in prefixes]
            incident = next((metadata[key] for key in keys if key in metadata), None)
            if incident:
                task.update(incident)

    publish(app, _annotate_task_incidents)

    def load_project_incident_index(limit: int = 100) -> list[dict]:
        """Return the real project-monitor incident ledger for the alarm screen."""
        try:
            monitor_state = app.json.loads(app.PROJECT_MONITOR_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            monitor_state = {}
        incidents = monitor_state.get("incidents") if isinstance(monitor_state, dict) else {}
        incidents = incidents if isinstance(incidents, dict) else {}

        handlers = app._project_monitor_handlers()

        severity_labels = {"P1": "紧急", "P2": "高", "P3": "中"}
        records: list[dict] = []
        for incident in incidents.values():
            if not isinstance(incident, dict):
                continue
            incident_id = str(incident.get("incident_id") or "")
            if not incident_id:
                continue
            diagnosis = incident.get("diagnosis") if isinstance(incident.get("diagnosis"), dict) else {}
            resolution = incident.get("resolution") if isinstance(incident.get("resolution"), dict) else {}
            resolution_ai = resolution.get("ai_summary") if isinstance(resolution.get("ai_summary"), dict) else {}
            severity = str(diagnosis.get("severity") or incident.get("severity") or "P2").upper()
            if severity not in severity_labels:
                severity = "P2"
            handled = handlers.get(incident_id, {})
            suggestions = diagnosis.get("recommended_solutions") or incident.get("suggestions") or []
            if not isinstance(suggestions, list):
                suggestions = [str(suggestions)] if suggestions else []
            evidence = incident.get("evidence") if isinstance(incident.get("evidence"), list) else []
            affected_routes = diagnosis.get("affected_routes") if isinstance(diagnosis.get("affected_routes"), list) else []
            status = str(incident.get("status") or "open")
            resolution_type = str(resolution.get("type") or "")
            condition_key = str(incident.get("condition_key") or "")
            component = str(incident.get("component") or "")
            alarm_type = "系统运行异常"
            alarm_type_rules = (
                (("heartbeat",), "心跳异常"),
                (("stuck", "timeout"), "任务停滞或超时"),
                (("failed", "failure"), "任务执行失败"),
                (("fault-resolution", "card-update", "ledger"), "告警结案或回写异常"),
                (("feishu", "delivery", "publish"), "飞书交付异常"),
                (("log-error", "stable-log"), "运行日志错误"),
                (("web-health", "web-app"), "后台服务异常"),
            )
            alarm_type_source = f"{condition_key} {component}".lower()
            for needles, label in alarm_type_rules:
                if any(needle in alarm_type_source for needle in needles):
                    alarm_type = label
                    break
            resolution_type_labels = {
                "automatic_recovery": "系统自行恢复",
                "normal_task_progress": "任务实际正常推进",
                "service_restarted": "服务重启后恢复",
                "condition_cleared": "故障条件消除",
                "false_positive": "确认误报",
                "superseded": "由新告警口径接管",
                "unverified": "等待恢复证据",
            }
            resolution_reason_labels = {
                "scheduler_heartbeat_verified": "独立心跳持续更新，任务实际正常推进；没有执行重启、补跑或其他修复动作。",
                "log_condition_cleared": "后续巡检未再发现同一类新增日志错误；没有记录自动修复动作。",
                "condition_no_longer_current": "最新任务归档或状态源已不再显示该故障；没有记录自动修复动作。",
                "service_restarted_after_error": "服务在故障后确实重新启动，后续巡检未再命中原异常。",
                "superseded_by_stable_log_condition": "旧版重复日志告警已由新的稳定故障状态接管。",
            }
            resolution_reason_code = str(incident.get("resolution_reason") or "")
            resolution_reason = str(resolution_ai.get("recovery_cause") or "")
            if not resolution_reason:
                resolution_reason = resolution_reason_labels.get(resolution_reason_code, "")
            phase_labels = {
                "automatic_recovery": "自动修复后恢复",
                "normal_task_progress": "已确认任务正常",
                "service_restarted": "服务重启后恢复",
                "condition_cleared": "恢复证据已确认",
                "false_positive": "已确认为误报",
                "superseded": "已由新口径接管",
            }
            if handled:
                phase = "机器人处理" if str(handled.get("source") or "") == "feishu_robot" else "人工修复"
            elif status == "open":
                phase = "待处理"
            elif status == "recovery_pending" or resolution.get("status") == "awaiting_evidence":
                phase = "恢复待验证"
            elif resolution.get("ai_status") != "completed" and resolution.get("status") == "evidence_verified":
                phase = "证据已确认，等待LLM结案"
            elif resolution_type:
                phase = phase_labels.get(resolution_type, "已验证结案")
            else:
                phase = "历史结案（旧口径）"
            records.append({
                "source": "project-monitor",
                "task_id": f"incident:{incident_id}",
                "incident_id": incident_id,
                "incident_status": status,
                "kind": str(incident.get("component") or "project-monitor"),
                "kind_label": str(incident.get("task_name") or "项目故障"),
                "title": str(incident.get("task_name") or incident.get("summary") or "项目故障"),
                "scope": str(incident.get("component") or incident.get("condition_key") or "项目监控"),
                "run_status": "failed" if status == "open" else "completed",
                "severity": severity,
                "severity_label": severity_labels[severity],
                **app._handler_public_fields(handled),
                "summary": str(incident.get("summary") or ""),
                "alarm_type": alarm_type,
                "alarm_reason": str(diagnosis.get("fault_cause") or incident.get("error") or incident.get("summary") or ""),
                "alarm_trigger_summary": str(incident.get("summary") or ""),
                "error": str(diagnosis.get("fault_cause") or incident.get("error") or ""),
                "impact": str(diagnosis.get("fault_impact") or incident.get("impact") or ""),
                "suggestions": [str(item) for item in suggestions if str(item).strip()],
                "evidence": [str(item) for item in evidence if str(item).strip()],
                "diagnosis_summary": str(diagnosis.get("diagnosis_summary") or ""),
                "diagnosis_status": str(incident.get("diagnosis_status") or ""),
                "diagnosis_model": str(diagnosis.get("model") or ""),
                "diagnosis_source": str(diagnosis.get("source") or ""),
                "severity_reason": str(diagnosis.get("severity_reason") or ""),
                "confirmed_facts": diagnosis.get("confirmed_facts") if isinstance(diagnosis.get("confirmed_facts"), list) else [],
                "inferences": diagnosis.get("inferences") if isinstance(diagnosis.get("inferences"), list) else [],
                "affected_routes": [dict(item) for item in affected_routes if isinstance(item, dict)],
                "route_assessment_version": int(diagnosis.get("route_assessment_version") or 0),
                "resolution_status": str(resolution.get("status") or ""),
                "resolution_type": resolution_type,
                "resolution_type_label": resolution_type_labels.get(resolution_type, "历史结案（旧口径）" if status == "resolved" else "尚未结案"),
                "resolution_reason_code": resolution_reason_code,
                "resolution_reason": resolution_reason,
                "resolution_summary": str(resolution_ai.get("resolution_summary") or ""),
                "recovery_cause": str(resolution_ai.get("recovery_cause") or ""),
                "verification_summary": str(resolution_ai.get("verification_summary") or ""),
                "remaining_risk": str(resolution_ai.get("remaining_risk") or ""),
                "resolution_model": str(resolution_ai.get("model") or ""),
                "resolution_evidence": resolution.get("evidence") if isinstance(resolution.get("evidence"), list) else [],
                "resolution_action": resolution.get("action") if isinstance(resolution.get("action"), dict) else {},
                "phase": phase,
                "occurred_at_hkt": str(incident.get("occurred_at_hkt") or incident.get("first_seen_at_hkt") or ""),
                "started_at_hkt": str(incident.get("first_seen_at_hkt") or incident.get("occurred_at_hkt") or ""),
                "heartbeat_at_hkt": str(incident.get("last_seen_at_hkt") or ""),
                "completed_at_hkt": str(incident.get("resolved_at_hkt") or ""),
                "resolved_at_hkt": str(incident.get("resolved_at_hkt") or ""),
                "auto_repaired_at_hkt": str(incident.get("resolved_at_hkt") or "") if resolution_type == "automatic_recovery" else "",
                "source": "project-monitor",
            })
        records.sort(
            key=lambda item: str(item.get("occurred_at_hkt") or item.get("started_at_hkt") or ""),
            reverse=True,
        )
        return records[: max(1, min(100_000, int(limit or 100)))]

    publish(app, load_project_incident_index)

    def count_project_incidents() -> int:
        """Count every valid incident in the ledger independently of the page limit."""
        try:
            monitor_state = app.json.loads(app.PROJECT_MONITOR_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return 0
        incidents = monitor_state.get("incidents") if isinstance(monitor_state, dict) else {}
        if not isinstance(incidents, dict):
            return 0
        return sum(
            1
            for incident in incidents.values()
            if isinstance(incident, dict) and str(incident.get("incident_id") or "")
        )

    publish(app, count_project_incidents)

    def load_unified_task_index(limit: int = 50) -> list[dict]:
        tasks = [app._task_public_record(item) for item in app._task_read_local_index()]
        tasks.extend(
            app._normalize_crawl_task(item)
            for item in app.load_crawl_run_index()
            if isinstance(item, dict) and item.get("crawl_run_id")
        )
        tasks.extend(app._orphan_research_tasks())
        tasks = app._coalesce_research_refresh_tasks(tasks)
        app._annotate_task_retries(tasks)
        app._annotate_task_incidents(tasks)
        tasks.sort(
            key=lambda item: str(item.get("started_at_hkt") or item.get("completed_at_hkt") or ""),
            reverse=True,
        )
        return tasks[:limit]

    publish(app, load_unified_task_index)

    def load_unified_task_log(task_id: str) -> dict:
        task_id = str(task_id or "").strip()
        if task_id.startswith("research:"):
            run_id = task_id.removeprefix("research:")
            if not app.re.fullmatch(r"research_\d{8}(?:_rerun_\d{6})?", run_id):
                return {"ok": False, "error": "无效的研究任务编号。"}
            task = next((item for item in app._orphan_research_tasks()
                         if str(item.get("task_id") or "") == task_id), None)
            if not task:
                return {"ok": False, "error": "未找到该研究任务记录。"}
            log_path = app.ROOT / "curation_data" / "research_runs" / run_id / "process.log"
            try:
                content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            except OSError as exc:
                return {"ok": False, "error": "研究任务日志读取失败：" + str(exc)}
            return {
                "ok": True,
                "task": task,
                "run": {
                    "run_status": task.get("run_status"),
                    "started_at_hkt": task.get("started_at_hkt"),
                    "completed_at_hkt": task.get("completed_at_hkt"),
                    "duration_ms": task.get("duration_ms"),
                },
                "content": content,
                "lines": int(task.get("lines") or 0),
                "bytes": int(task.get("bytes") or 0),
            }
        if task_id.startswith("crawl:"):
            crawl_id = task_id.removeprefix("crawl:")
            result = app.load_crawl_run_log(crawl_id)
            if result.get("ok"):
                run = result.get("run") if isinstance(result.get("run"), dict) else {}
                indexed = next(
                    (
                        item
                        for item in app.load_unified_task_index(limit=500)
                        if str(item.get("task_id") or "") == task_id
                    ),
                    {},
                )
                result["task"] = dict(indexed) if indexed else app._normalize_crawl_task(run)
                merged_ids = result["task"].get("merged_task_ids") if isinstance(result["task"].get("merged_task_ids"), list) else []
                contents = [str(result.get("content") or "").rstrip()]
                raw_parts = [str(result.get("raw") or "").rstrip()]
                for merged_id in merged_ids:
                    child = app.load_crawl_run_log(str(merged_id))
                    if not child.get("ok"):
                        continue
                    child_run = child.get("run") if isinstance(child.get("run"), dict) else {}
                    heading = f"----- 已合并阶段：{child_run.get('trigger') or '四库更新与页面发布'} -----"
                    contents.extend([heading, str(child.get("content") or "").rstrip()])
                    raw_parts.extend([heading, str(child.get("raw") or "").rstrip()])
                content = "\n".join(part for part in contents if part).rstrip()
                raw = "\n".join(part for part in raw_parts if part).rstrip()
                result["content"] = content + ("\n" if content else "")
                result["raw"] = raw + ("\n" if raw else "")
                result["lines"] = len(result["content"].splitlines())
                result["bytes"] = len(result["raw"].encode("utf-8"))
                result["task"]["lines"] = result["lines"]
                result["task"]["bytes"] = result["bytes"]
                result["task"]["retry_index"] = int(result["task"].get("retry_index") or 0)
            return result
        if not task_id.startswith("task:"):
            return {"ok": False, "error": "无效的任务编号。"}
        record = next(
            (item for item in app._task_read_local_index() if str(item.get("task_id") or "") == task_id),
            None,
        )
        if not record:
            return {"ok": False, "error": "未找到该任务记录。"}
        task = app._task_public_record(record)
        relative_path = str(record.get("log_path") or "")
        log_path = app.ROOT / relative_path if relative_path else None
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.exists() else ""
        except OSError as exc:
            return {"ok": False, "error": "任务日志读取失败：" + str(exc)}
        run = {
            "run_status": task.get("run_status"),
            "started_at_hkt": task.get("started_at_hkt"),
            "completed_at_hkt": task.get("completed_at_hkt"),
            "duration_ms": task.get("duration_ms"),
        }
        return {
            "ok": True,
            "task": task,
            "run": run,
            "content": content,
            "lines": int(task.get("lines") or 0),
            "bytes": int(task.get("bytes") or 0),
        }

    publish(app, load_unified_task_log)

    def _task_phase_from_payload(payload: dict, current: str) -> tuple[str, str]:
        event_type = str(payload.get("type") or "")
        if event_type == "agent_trace":
            trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
            return str(trace.get("node") or "Agent 审核"), str(trace.get("message") or "Agent 正在处理审核节点。")
        if event_type == "done":
            return "任务收尾", str(payload.get("message") or "执行步骤已结束，正在持久化最终状态。")
        text = str(payload.get("text") or payload.get("message") or "").strip()
        if not text:
            return current or "执行中", "任务仍在执行，等待下一条业务进度。"
        if "语音" in text or "TTS" in text:
            phase = "生成语音摘要"
        elif "飞书" in text or "同步" in text:
            phase = "飞书同步"
        elif any(token in text for token in ("搜索验证", "事实抽取", "质量审计", "冲突仲裁", "主体校验", "Agent")):
            phase = "Agent 审核"
        elif "补爬" in text:
            phase = "缺口补爬"
        elif any(token in text for token in ("crawl row", "抓取", "状态码", "URL")):
            phase = "网页抓取"
        elif any(token in text for token in ("报告", "模板", "周报", "业绩摘要")):
            phase = "报告生成"
        else:
            phase = current or "执行中"
        return phase, text[:360]

    publish(app, _task_phase_from_payload)

    def observe_task_progress(handler: BaseHTTPRequestHandler, payload: dict) -> None:
        if not isinstance(payload, dict) or not getattr(handler, "_task_monitor_kind", ""):
            return
        phase, detail = app._task_phase_from_payload(payload, str(getattr(handler, "_task_monitor_phase", "") or ""))
        handler._task_monitor_phase = phase
        handler._task_monitor_detail = detail
        if getattr(handler, "_task_monitor_kind", "") == "crawl":
            app.CRAWL_PIPELINE_STATE.update({"phase": phase, "detail": detail})

    publish(app, observe_task_progress)

    def _task_monitor_loop(handler: BaseHTTPRequestHandler, owner: threading.Thread) -> None:
        stop_event = handler._task_monitor_stop
        while not stop_event.wait(app.TASK_HEARTBEAT_INTERVAL_SECONDS):
            task_id = str(getattr(handler, "_task_monitor_id", "") or "")
            kind = str(getattr(handler, "_task_monitor_kind", "") or "")
            phase = str(getattr(handler, "_task_monitor_phase", "") or "执行中")
            detail = str(getattr(handler, "_task_monitor_detail", "") or "任务仍在执行，等待下一条业务进度。")
            worker_pid = int(getattr(handler, "_task_worker_pid", 0) or 0)
            if not owner.is_alive():
                reason = f"任务执行线程意外结束；最后阶段：{phase}；最后进度：{detail}"
                if kind == "crawl":
                    app.mark_crawl_run_interrupted(task_id, reason)
                elif kind == "general":
                    app.append_general_task_log(task_id, "[任务中断] " + reason)
                    app.finish_general_task_run(task_id, False, reason)
                return
            if kind == "crawl":
                app.heartbeat_crawl_run(task_id, phase, detail, worker_pid=worker_pid, append_log=True)
            elif kind == "general":
                app.heartbeat_general_task_run(task_id, phase, detail, worker_pid=worker_pid, append_log=True)

    publish(app, _task_monitor_loop)

    def start_task_lifecycle_monitor(
        handler: BaseHTTPRequestHandler,
        kind: str,
        task_id: str,
        phase: str,
    ) -> None:
        handler._task_monitor_kind = kind
        handler._task_monitor_id = task_id
        handler._task_monitor_phase = phase
        handler._task_monitor_detail = "后台任务已启动，持续监控中。"
        handler._task_worker_pid = 0
        handler._task_monitor_stop = app.threading.Event()
        if kind == "crawl":
            app.heartbeat_crawl_run(task_id, phase, handler._task_monitor_detail, append_log=False)
        else:
            app.heartbeat_general_task_run(task_id, phase, handler._task_monitor_detail, append_log=False)
        monitor = app.threading.Thread(
            target=app._task_monitor_loop,
            args=(handler, app.threading.current_thread()),
            name=f"task-monitor-{task_id}",
            daemon=True,
        )
        handler._task_monitor_thread = monitor
        monitor.start()

    publish(app, start_task_lifecycle_monitor)

    def stop_task_lifecycle_monitor(handler: BaseHTTPRequestHandler) -> None:
        stop_event = getattr(handler, "_task_monitor_stop", None)
        if stop_event:
            stop_event.set()

    publish(app, stop_task_lifecycle_monitor)

    def start_audio_generation_task(target: Path, force: bool = True) -> tuple[dict, bool]:
        target_key = str(target.resolve())
        with app.TASK_RUNS_LOCK:
            existing = next(
                (
                    task
                    for task in app._task_read_local_index()
                    if task.get("kind") == "audio-generation"
                    and task.get("run_status") == "running"
                    and str(task.get("target_path") or "") == target_key
                ),
                None,
            )
        if existing:
            return app._task_public_record(existing), False

        task = app.start_general_task_run(
            "audio-generation",
            "生成音频摘要",
            target.name,
            "tts_service.py",
        )
        task_id = str(task["task_id"])
        raw_id = str(task["task_run_id"])
        with app.TASK_RUNS_LOCK:
            tasks = app._task_read_local_index()
            for record in tasks:
                if str(record.get("task_id") or "") == task_id:
                    record["target_path"] = target_key
                    task = dict(record)
                    break
            app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
            app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), task)

        def worker() -> None:
            code = (
                "import sys, json\n"
                "from pathlib import Path\n"
                "from tts_service import synthesize_report_audio\n"
                "try:\n"
                "    res = synthesize_report_audio(Path(sys.argv[1]), force=sys.argv[2] == 'True')\n"
                "    print(json.dumps({'ok': True, 'result': res}))\n"
                "except Exception as e:\n"
                "    print(json.dumps({'ok': False, 'error': str(e)}))\n"
            )
            proc_audio: subprocess.Popen[str] | None = None
            try:
                app.append_general_task_log(task_id, f"开始为报告生成音频摘要：{target.name}")
                proc_audio = app.subprocess.Popen(
                    [app.sys.executable, "-c", code, str(target), str(bool(force))],
                    cwd=str(app.ROOT),
                    stdout=app.subprocess.PIPE,
                    stderr=app.subprocess.PIPE,
                    text=True,
                )
                app.heartbeat_general_task_run(
                    task_id,
                    "生成语音摘要",
                    "AI TTS 正在生成并统一处理音频。",
                    worker_pid=proc_audio.pid,
                    append_log=True,
                )
                while proc_audio.poll() is None:
                    try:
                        proc_audio.wait(timeout=app.TASK_HEARTBEAT_INTERVAL_SECONDS)
                    except app.subprocess.TimeoutExpired:
                        app.heartbeat_general_task_run(
                            task_id,
                            "生成语音摘要",
                            "AI TTS 仍在处理，任务持续跟踪中。",
                            worker_pid=proc_audio.pid,
                            append_log=False,
                        )
                stdout, stderr = proc_audio.communicate()
                try:
                    payload = app.json.loads(stdout or "{}")
                except app.json.JSONDecodeError as exc:
                    raise RuntimeError(f"音频服务返回无法解析：{stderr.strip() or stdout.strip() or exc}") from exc
                if proc_audio.returncode != 0 or not payload.get("ok"):
                    raise RuntimeError(str(payload.get("error") or stderr.strip() or "音频生成失败"))
                result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or "音频生成失败"))
                audio = result.get("audio") if isinstance(result.get("audio"), dict) else {}
                backend = str(result.get("backend") or "unknown")
                audio_name = str(audio.get("name") or "音频摘要")
                detail = f"音频摘要已生成：{audio_name}（{backend}）"
                app.append_general_task_log(task_id, detail)
                app.finish_general_task_run(task_id, True, detail)
            except Exception as exc:
                detail = str(exc) or "音频生成失败"
                app.append_general_task_log(task_id, "音频生成失败：" + detail)
                app.finish_general_task_run(task_id, False, detail)

        app.threading.Thread(
            target=worker,
            name="audio-task-" + raw_id,
            daemon=True,
        ).start()
        return app._task_public_record(task), True

    publish(app, start_audio_generation_task)
