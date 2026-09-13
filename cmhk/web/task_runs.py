from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from pathlib import Path

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def _task_atomic_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(app.json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        app.os.replace(temporary, path)

    publish(app, _task_atomic_json)

    def record_ui_runtime_incident(
        incident_type: str,
        *,
        status: str,
        error: str = "",
        context: dict | None = None,
    ) -> dict:
        """Persist UI-visible failures so the independent monitor can alert and resolve them."""
        definitions = {
            "competitor-ai-insight": {
                "component": "competitor-workbench",
                "task_name": "竞对工作台 AI 竞争洞察",
                "severity": "P2",
                "summary": "竞对工作台 AI 洞察未生成",
                "impact": "用户可查看权威数据图表，但当前组合的 AI 竞争格局、公司定位和业务含义未完成生成。",
                "suggestions": [
                    "核对 AI 网关、当前模型路由、限流队列和返回协议。",
                    "保留已展示的权威数据，只恢复 AI 洞察阶段；恢复后回读页面与告警状态。",
                ],
            },
            "fault-resolution": {
                "component": "project-monitor",
                "task_name": "项目告警人工处置",
                "severity": "P2",
                "summary": "项目告警人工处置未完整成功",
                "impact": "告警状态、飞书错误台账或原告警卡片可能没有完成一致更新。",
                "suggestions": [
                    "按告警ID核对操作审计、飞书台账和原告警卡片的实际状态。",
                    "保留已完成步骤并幂等重试未完成步骤，成功后回读处置状态。",
                ],
            },
        }
        incident_type = str(incident_type or "").strip()
        if incident_type not in definitions:
            raise ValueError("不支持的界面故障类型")
        if status not in {"open", "resolved"}:
            raise ValueError("界面故障状态无效")
        now_text = app.datetime.now().astimezone().isoformat(timespec="seconds")
        safe_context = {
            str(key)[:80]: str(value)[:240]
            for key, value in (context or {}).items()
            if isinstance(value, (str, int, float, bool))
        }
        with app.UI_RUNTIME_INCIDENTS_LOCK:
            try:
                payload = app.json.loads(app.UI_RUNTIME_INCIDENTS_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                payload = {"version": 1, "incidents": {}}
            incidents = payload.get("incidents") if isinstance(payload, dict) else None
            if not isinstance(incidents, dict):
                incidents = {}
                payload = {"version": 1, "incidents": incidents}
            record = incidents.get(incident_type) if isinstance(incidents.get(incident_type), dict) else {}
            definition = definitions[incident_type]
            if status == "open":
                record.update(definition)
                record.update({
                    "incident_type": incident_type,
                    "status": "open",
                    "first_seen_at_hkt": record.get("first_seen_at_hkt") or now_text,
                    "last_seen_at_hkt": now_text,
                    "error": str(error or "未记录到具体错误")[:1800],
                    "context": safe_context,
                    "failure_count": int(record.get("failure_count") or 0) + 1,
                })
                record.pop("resolved_at_hkt", None)
            else:
                record.update({
                    "incident_type": incident_type,
                    "status": "resolved",
                    "last_seen_at_hkt": now_text,
                    "resolved_at_hkt": now_text,
                    "context": safe_context or record.get("context") or {},
                })
            incidents[incident_type] = record
            payload["updated_at_hkt"] = now_text
            app._task_atomic_json(app.UI_RUNTIME_INCIDENTS_PATH, payload)
        return dict(record)

    publish(app, record_ui_runtime_incident)

    def _task_read_local_index() -> list[dict]:
        if not app.TASK_RUNS_INDEX_PATH.exists():
            return []
        try:
            payload = app.json.loads(app.TASK_RUNS_INDEX_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("tasks")
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    publish(app, _task_read_local_index)

    def _task_log_stats(record: dict) -> tuple[int, int]:
        relative_path = str(record.get("log_path") or "")
        path = app.ROOT / relative_path if relative_path else None
        if not path or not path.exists():
            return 0, 0
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return len(content.splitlines()), path.stat().st_size
        except OSError:
            return 0, 0

    publish(app, _task_log_stats)

    def _task_public_record(record: dict) -> dict:
        public = dict(record)
        lines, size = app._task_log_stats(record)
        public["lines"] = lines
        public["bytes"] = size
        public["run_status"] = str(public.get("run_status") or "completed")
        if public["run_status"] == "running" and int(public.get("backend_pid") or 0) != app.os.getpid():
            public["run_status"] = "failed"
            public["status_detail"] = "后端重启后任务已中断"
        return public

    publish(app, _task_public_record)

    def start_general_task_run(
        kind: str,
        title: str,
        scope: str,
        script_name: str = "",
        *,
        recovery_of: str = "",
        retry_count: int = 0,
        target_path: str = "",
    ) -> dict:
        now = app.datetime.now().astimezone()
        raw_id = now.strftime("%Y%m%d_%H%M%S") + "_" + app.uuid.uuid4().hex[:8]
        task_id = "task:" + raw_id
        log_path = app.TASK_RUNS_LOG_DIR / (raw_id + ".log")
        kind_labels = {
            "weekly-report": "周报生成",
            "carrier-performance": "业绩摘要",
            "audio-generation": "音频生成",
        }
        record = {
            "task_id": task_id,
            "task_run_id": raw_id,
            "kind": kind,
            "kind_label": kind_labels.get(kind, "后台任务"),
            "title": title,
            "scope": scope,
            "script": script_name,
            "run_status": "running",
            "started_at_hkt": now.isoformat(timespec="seconds"),
            "completed_at_hkt": "",
            "duration_ms": 0,
            "backend_pid": app.os.getpid(),
            "worker_pid": 0,
            "phase": "任务启动",
            "progress_detail": "后台已接收任务，正在准备执行。",
            "heartbeat_at_hkt": now.isoformat(timespec="seconds"),
            "log_path": str(log_path.relative_to(app.ROOT)),
            "recovery_of": str(recovery_of or ""),
            "retry_count": max(0, int(retry_count or 0)),
            "auto_recovered": bool(recovery_of),
            "target_path": str(target_path or ""),
        }
        with app.TASK_RUNS_LOCK:
            app.TASK_RUNS_DIR.mkdir(parents=True, exist_ok=True)
            app.TASK_RUNS_LOG_DIR.mkdir(parents=True, exist_ok=True)
            tasks = app._task_read_local_index()
            tasks.insert(0, record)
            app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
            app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), record)
            log_path.write_text(
                "[" + now.isoformat(timespec="seconds") + "] 任务启动：" + title + "\n",
                encoding="utf-8",
            )
        return record

    publish(app, start_general_task_run)

    def append_general_task_log(task_id: str, text: object) -> None:
        raw_id = str(task_id or "").removeprefix("task:")
        if not raw_id or any(not (char.isalnum() or char in "_-") for char in raw_id):
            return
        log_path = app.TASK_RUNS_LOG_DIR / (raw_id + ".log")
        value = str(text or "")
        if not value:
            return
        with app.TASK_RUNS_LOCK:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(value)
                if not value.endswith("\n"):
                    handle.write("\n")

    publish(app, append_general_task_log)

    def finish_general_task_run(task_id: str, ok: bool, detail: str = "") -> dict | None:
        now = app.datetime.now().astimezone()
        raw_id = str(task_id or "").removeprefix("task:")
        updated = None
        with app.TASK_RUNS_LOCK:
            tasks = app._task_read_local_index()
            for task in tasks:
                if str(task.get("task_id") or "") != task_id:
                    continue
                started_text = str(task.get("started_at_hkt") or "")
                try:
                    started = app.datetime.fromisoformat(started_text)
                    duration_ms = max(0, int((now - started).total_seconds() * 1000))
                except (TypeError, ValueError):
                    duration_ms = 0
                task["run_status"] = "completed" if ok else "failed"
                task["completed_at_hkt"] = now.isoformat(timespec="seconds")
                task["duration_ms"] = duration_ms
                task["status_detail"] = detail
                task["worker_pid"] = 0
                task["phase"] = "已完成" if ok else "失败"
                task["progress_detail"] = detail or ("任务全部步骤已完成。" if ok else "任务执行失败，请查看日志。")
                task["heartbeat_at_hkt"] = now.isoformat(timespec="seconds")
                updated = dict(task)
                break
            if updated:
                app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
                app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), updated)
        return updated

    publish(app, finish_general_task_run)

    def heartbeat_general_task_run(
        task_id: str,
        phase: str,
        detail: str,
        *,
        worker_pid: int = 0,
        append_log: bool = True,
    ) -> dict | None:
        """Persist report-task liveness even when the browser connection disappears."""
        now = app.datetime.now().astimezone()
        raw_id = str(task_id or "").removeprefix("task:")
        updated = None
        with app.TASK_RUNS_LOCK:
            tasks = app._task_read_local_index()
            for task in tasks:
                if str(task.get("task_id") or "") != task_id or task.get("run_status") != "running":
                    continue
                task.update(
                    {
                        "backend_pid": app.os.getpid(),
                        "worker_pid": int(worker_pid or 0),
                        "phase": str(phase or task.get("phase") or "执行中"),
                        "progress_detail": str(detail or task.get("progress_detail") or "任务仍在执行。"),
                        "heartbeat_at_hkt": now.isoformat(timespec="seconds"),
                    }
                )
                updated = dict(task)
                break
            if updated:
                app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
                app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), updated)
                if append_log:
                    log_path = app.TASK_RUNS_LOG_DIR / (raw_id + ".log")
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            f"[监控心跳 {now.strftime('%H:%M:%S')}] 阶段：{updated['phase']}；"
                            f"状态：{updated['progress_detail']}\n"
                        )
        return updated

    publish(app, heartbeat_general_task_run)

    def reconcile_interrupted_general_tasks() -> list[dict]:
        """Persistently close report tasks left running by an earlier backend process."""
        now = app.datetime.now().astimezone()
        reconciled: list[dict] = []
        with app.TASK_RUNS_LOCK:
            tasks = app._task_read_local_index()
            for task in tasks:
                if task.get("run_status") != "running":
                    continue
                raw_id = str(task.get("task_run_id") or str(task.get("task_id") or "").removeprefix("task:"))
                log_path = app.ROOT / str(task.get("log_path") or "")
                completed = now
                if log_path.exists():
                    try:
                        completed = app.datetime.fromtimestamp(log_path.stat().st_mtime, now.tzinfo)
                    except OSError:
                        completed = now
                try:
                    started = app.datetime.fromisoformat(str(task.get("started_at_hkt") or ""))
                    duration_ms = max(0, int((completed - started).total_seconds() * 1000))
                except (TypeError, ValueError):
                    duration_ms = 0
                detail = "后台服务已重新启动，原任务执行进程已不存在；已按最后心跳明确收尾。"
                task.update(
                    {
                        "run_status": "failed",
                        "interrupted": True,
                        "status_detail": detail,
                        "completed_at_hkt": completed.isoformat(timespec="seconds"),
                        "duration_ms": duration_ms,
                        "worker_pid": 0,
                        "phase": "已中断",
                        "progress_detail": detail,
                        "heartbeat_at_hkt": completed.isoformat(timespec="seconds"),
                    }
                )
                if log_path:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write("[任务中断] " + detail + "\n")
                app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), task)
                reconciled.append(dict(task))
            if reconciled:
                app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
        return reconciled

    publish(app, reconcile_interrupted_general_tasks)

    def pending_interrupted_general_task_retries() -> list[dict]:
        """Include interruptions recorded by an older service before auto-retry existed."""
        return [
            dict(task)
            for task in app._task_read_local_index()
            if task.get("run_status") == "failed"
            and bool(task.get("interrupted"))
            and not task.get("recovery_disposition")
        ]

    publish(app, pending_interrupted_general_task_retries)

    def _mark_general_task_recovery_disposition(task_id: str, disposition: str) -> None:
        now = app.datetime.now().astimezone().isoformat(timespec="seconds")
        raw_id = str(task_id or "").removeprefix("task:")
        with app.TASK_RUNS_LOCK:
            tasks = app._task_read_local_index()
            updated = None
            for task in tasks:
                if str(task.get("task_id") or "") != task_id:
                    continue
                task["recovery_disposition"] = str(disposition or "")
                task["recovery_scheduled_at_hkt"] = now
                updated = dict(task)
                break
            if updated:
                app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
                app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), updated)

    publish(app, _mark_general_task_recovery_disposition)

    def _latest_report_for_recovered_task(kind: str) -> Path:
        report_kind = "weekly" if kind == "weekly-report" else "carrier-performance"
        target = app.latest_output_path(app.build_status(), report_kind)
        if not target or not target.exists():
            raise RuntimeError("报告进程结束后未找到可用Word文件")
        return target

    publish(app, _latest_report_for_recovered_task)

    def _run_recovered_general_task(original: dict) -> None:
        """Retry an interrupted report/audio task without requiring a browser connection."""
        kind = str(original.get("kind") or "")
        retry_count = int(original.get("retry_count") or 0) + 1
        root_id = str(original.get("recovery_of") or original.get("task_id") or "")
        task = app.start_general_task_run(
            kind,
            str(original.get("title") or "自动恢复任务"),
            str(original.get("scope") or ""),
            str(original.get("script") or ""),
            recovery_of=root_id,
            retry_count=retry_count,
            target_path=str(original.get("target_path") or ""),
        )
        task_id = str(task["task_id"])
        app.append_general_task_log(
            task_id,
            f"[自动恢复] 服务已恢复，正在重试中断任务（第{retry_count}/{app.GENERAL_TASK_MAX_AUTO_RETRIES}次）。",
        )
        try:
            if kind == "audio-generation":
                target = app.Path(str(original.get("target_path") or ""))
                if not target.exists() or target.parent.resolve() != app.ROOT.resolve():
                    raise RuntimeError("原音频任务的报告文件已不存在或不在允许目录")
                app.heartbeat_general_task_run(
                    task_id,
                    "生成语音摘要",
                    "服务恢复后正在重新生成音频。",
                    append_log=True,
                )
                result = app.synthesize_report_audio(target, force=True)
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or "音频生成失败"))
                detail = f"自动恢复成功：{(result.get('audio') or {}).get('name') or target.name}"
            elif kind in {"weekly-report", "carrier-performance"}:
                script_name = str(original.get("script") or "")
                allowed_scripts = {
                    "weekly-report": "generate_weekly_report.py",
                    "carrier-performance": "generate_carrier_performance_report.py",
                }
                if script_name != allowed_scripts[kind]:
                    raise RuntimeError("任务恢复脚本不在允许列表")
                proc = app.subprocess.Popen(
                    [app.sys.executable, "-u", str(app.ROOT / script_name)],
                    cwd=str(app.ROOT),
                    stdout=app.subprocess.PIPE,
                    stderr=app.subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                app.heartbeat_general_task_run(
                    task_id,
                    "报告生成",
                    "服务恢复后已重新启动报告进程。",
                    worker_pid=proc.pid,
                    append_log=True,
                )
                from cmhk.reporting.report_audio_pipeline import audio_result_from_output, RESULT_PREFIX
                recovered_audio = None
                if proc.stdout:
                    for line in proc.stdout:
                        value = line.rstrip()
                        if value.startswith(RESULT_PREFIX):
                            recovered_audio = audio_result_from_output(value)
                            continue
                        if value:
                            app.append_general_task_log(task_id, value)
                            phase, progress = app._task_phase_from_payload({"type": "log", "text": value}, "报告生成")
                            app.heartbeat_general_task_run(
                                task_id,
                                phase,
                                progress,
                                worker_pid=proc.pid,
                                append_log=False,
                            )
                proc.wait()
                if proc.returncode:
                    raise RuntimeError(f"报告生成进程返回{proc.returncode}")
                target = app.Path(recovered_audio["report_path"]) if recovered_audio else app._latest_report_for_recovered_task(kind)
                app.heartbeat_general_task_run(
                    task_id,
                    "生成语音摘要",
                    "Word已恢复生成，正在重新生成音频。",
                    append_log=True,
                )
                audio = recovered_audio if recovered_audio is not None else app.synthesize_report_audio(target, force=False)
                if not audio.get("ok"):
                    raise RuntimeError(str(audio.get("error") or "音频生成失败"))
                detail = f"自动恢复成功：{target.name}及音频均已生成"
            else:
                raise RuntimeError(f"尚未支持自动恢复的任务类型：{kind or '-'}")
            app.append_general_task_log(task_id, detail)
            app.finish_general_task_run(task_id, True, detail)
        except Exception as exc:
            detail = f"第{retry_count}次自动恢复失败：{exc}"
            app.append_general_task_log(task_id, detail)
            app.finish_general_task_run(task_id, False, detail)

    publish(app, _run_recovered_general_task)

    def schedule_interrupted_general_task_retries(interrupted: list[dict]) -> list[str]:
        """Queue bounded retries for every safely replayable general task."""
        scheduled: list[str] = []
        supported = {"weekly-report", "carrier-performance", "audio-generation"}
        seen: set[tuple[str, str]] = set()
        for task in interrupted:
            kind = str(task.get("kind") or "")
            retry_count = int(task.get("retry_count") or 0)
            # The index is newest-first. If several restarts interrupted the same
            # logical operation, retry only the newest record instead of launching
            # duplicate reports/audio jobs after recovery.
            recovery_key = (kind, str(task.get("target_path") or task.get("scope") or ""))
            if recovery_key in seen:
                app._mark_general_task_recovery_disposition(
                    str(task.get("task_id") or ""), "superseded_by_newer_interruption"
                )
                continue
            seen.add(recovery_key)
            if kind not in supported:
                app.append_general_task_log(str(task.get("task_id") or ""), "[自动恢复] 任务类型不支持安全重放，未自动重试。")
                app._mark_general_task_recovery_disposition(
                    str(task.get("task_id") or ""), "unsupported"
                )
                continue
            if retry_count >= app.GENERAL_TASK_MAX_AUTO_RETRIES:
                app.append_general_task_log(
                    str(task.get("task_id") or ""),
                    f"[自动恢复] 已达最大{app.GENERAL_TASK_MAX_AUTO_RETRIES}次，停止自动重试。",
                )
                app._mark_general_task_recovery_disposition(
                    str(task.get("task_id") or ""), "retry_limit_reached"
                )
                continue
            timer = app.threading.Timer(
                app.GENERAL_TASK_RETRY_DELAY_SECONDS,
                app._run_recovered_general_task,
                args=(dict(task),),
            )
            timer.name = f"task-auto-retry-{task.get('task_run_id') or 'unknown'}"
            timer.daemon = True
            timer.start()
            app._mark_general_task_recovery_disposition(
                str(task.get("task_id") or ""), "scheduled"
            )
            scheduled.append(str(task.get("task_id") or ""))
        return scheduled

    publish(app, schedule_interrupted_general_task_retries)

    def reconcile_misclassified_general_tasks() -> list[dict]:
        """Correct legacy report tasks that completed the DOCX but failed required audio generation."""
        corrected: list[dict] = []
        with app.TASK_RUNS_LOCK:
            tasks = app._task_read_local_index()
            for task in tasks:
                if task.get("run_status") != "completed" or task.get("kind") not in {"weekly-report", "carrier-performance"}:
                    continue
                relative_log = str(task.get("log_path") or "")
                if not relative_log:
                    continue
                log_path = app.ROOT / relative_log
                try:
                    content = log_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                failure_index = max(
                    content.rfind("❌ 语音摘要生成失败"),
                    content.rfind("Audio generation failed"),
                )
                success_index = content.rfind("语音摘要生成完成")
                if failure_index < 0 or success_index > failure_index:
                    continue
                failure_line = content[failure_index:].splitlines()[0].strip()
                detail = failure_line or "语音摘要生成失败。"
                task.update(
                    {
                        "run_status": "failed",
                        "status_detail": detail,
                        "phase": "失败",
                        "progress_detail": detail,
                        "worker_pid": 0,
                    }
                )
                raw_id = str(task.get("task_run_id") or str(task.get("task_id") or "").removeprefix("task:"))
                app._task_atomic_json(app.TASK_RUNS_DIR / (raw_id + ".json"), task)
                corrected.append(dict(task))
            if corrected:
                app._task_atomic_json(app.TASK_RUNS_INDEX_PATH, {"tasks": tasks[:500]})
        return corrected

    publish(app, reconcile_misclassified_general_tasks)

    def _normalize_crawl_task(run: dict) -> dict:
        crawl_id = str(run.get("crawl_run_id") or "")
        stream = run.get("stream_log") if isinstance(run.get("stream_log"), dict) else {}
        task_kind = str(run.get("task_kind") or "crawl")
        kind_labels = {
            "strategic-news": "新闻爬虫",
            "news-selection-agent": "新闻自动初筛",
            "four-database-source-discovery": "01:00四库资料搜索",
            "four-database-research": "03:00四库研究",
            "executive-intelligence-refresh": "四库刷新",
            "quarterly-data-release": "季度数据发布",
            "crawl": "爬虫",
        }
        operational_summary = run.get("operational_summary") if isinstance(run.get("operational_summary"), dict) else {}
        run_status = str(run.get("run_status") or "completed")
        if str(run.get("failure_stage") or "") == "user_cancelled" or bool(operational_summary.get("cancelled_by_user")):
            run_status = "cancelled"
        model_analysis = operational_summary.get("model_analysis") if isinstance(operational_summary.get("model_analysis"), dict) else {}
        pages_publish = operational_summary.get("pages_publish") if isinstance(operational_summary.get("pages_publish"), dict) else {}
        return {
            "task_id": "crawl:" + crawl_id,
            "task_run_id": crawl_id,
            "parent_crawl_run_id": str(run.get("parent_crawl_run_id") or ""),
            "kind": task_kind,
            "kind_label": kind_labels.get(task_kind, "后台任务"),
            "title": (
                "新闻自动初筛"
                if task_kind == "news-selection-agent"
                else "四库资料研究与更新"
                if task_kind == "four-database-research"
                else str(run.get("trigger") or "爬虫任务")
            ),
            "scope": str(run.get("scope") or "未记录范围"),
            "run_status": run_status,
            "started_at_hkt": str(run.get("started_at_hkt") or ""),
            "completed_at_hkt": str(run.get("completed_at_hkt") or ""),
            "duration_ms": int(run.get("duration_ms") or 0),
            "lines": int(stream.get("lines") or 0),
            "bytes": int(stream.get("bytes") or 0),
            "status_detail": str(run.get("status_detail") or ""),
            "interrupted": bool(run.get("interrupted")),
            "backend_pid": int(run.get("backend_pid") or 0),
            "worker_pid": int(run.get("worker_pid") or 0),
            "phase": str(run.get("phase") or ""),
            "progress_detail": str(run.get("progress_detail") or ""),
            "heartbeat_at_hkt": str(run.get("heartbeat_at_hkt") or ""),
            "analysis_model": str(model_analysis.get("model") or ""),
            "analysis_fallback_used": bool(model_analysis.get("fallback_used")),
            "analysis_fallback_reason": str(model_analysis.get("fallback_reason") or ""),
            "evidence_hash": str(model_analysis.get("evidence_hash") or ""),
            "pages_publish_ok": bool(pages_publish.get("ok")),
            "pages_publish_status": str(pages_publish.get("status") or ""),
            "pages_public_url": str(pages_publish.get("public_url") or ""),
            "pages_site_version": str(pages_publish.get("site_version") or ""),
            "pages_publish_error": str(pages_publish.get("error") or ""),
            "source": "crawl-archive",
        }

    publish(app, _normalize_crawl_task)

    def _coalesce_research_refresh_tasks(tasks: list[dict]) -> list[dict]:
        """Present the 03:00 research and its legacy refresh child as one task."""
        by_id = {str(task.get("task_run_id") or ""): task for task in tasks}
        hidden: set[str] = set()
        analysis_fields = (
            "analysis_model",
            "analysis_fallback_used",
            "analysis_fallback_reason",
            "evidence_hash",
            "pages_publish_ok",
            "pages_publish_status",
            "pages_public_url",
            "pages_site_version",
            "pages_publish_error",
        )
        for child in tasks:
            if str(child.get("kind") or "") != "executive-intelligence-refresh":
                continue
            parent_id = str(child.get("parent_crawl_run_id") or "")
            parent = by_id.get(parent_id)
            if not parent or str(parent.get("kind") or "") != "four-database-research":
                continue
            child_id = str(child.get("task_run_id") or "")
            hidden.add(child_id)
            merged_ids = parent.setdefault("merged_task_ids", [])
            if child_id and child_id not in merged_ids:
                merged_ids.append(child_id)
            parent["merged_task_count"] = len(merged_ids)
            separator = f"\n----- 已合并阶段：{child.get('title') or '四库更新与页面发布'} -----\n"
            parent["lines"] = int(parent.get("lines") or 0) + int(child.get("lines") or 0) + 1
            parent["bytes"] = int(parent.get("bytes") or 0) + int(child.get("bytes") or 0) + len(separator.encode("utf-8"))
            for field in analysis_fields:
                if child.get(field) not in (None, "", False):
                    parent[field] = child[field]
            if str(child.get("completed_at_hkt") or "") > str(parent.get("completed_at_hkt") or ""):
                parent["completed_at_hkt"] = child["completed_at_hkt"]
            if child.get("run_status") == "running" and parent.get("run_status") == "running":
                parent["phase"] = child.get("phase") or parent.get("phase")
                parent["progress_detail"] = child.get("progress_detail") or parent.get("progress_detail")
        return [task for task in tasks if str(task.get("task_run_id") or "") not in hidden]

    publish(app, _coalesce_research_refresh_tasks)

    def _research_process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            app.os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    publish(app, _research_process_alive)

    def _orphan_research_tasks() -> list[dict]:
        """Expose pre-registry 03:00 runs so an active task can never disappear."""
        records: list[dict] = []
        try:
            registered = app.json.loads(
                (app.ROOT / "agent_knowledge/crawl_run_logs/index.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            registered = []
        if isinstance(registered, dict):
            registered = registered.get("runs", registered.get("items", []))
        if not isinstance(registered, list):
            registered = []
        registered_task_ids = {
            str(item.get("crawl_run_id") or "")
            for item in registered
            if isinstance(item, dict)
        }
        registered_research_ids = {
            str(summary.get("agent_run_id") or "")
            for item in registered
            if isinstance(item, dict)
            for summary in [item.get("operational_summary") if isinstance(item.get("operational_summary"), dict) else {}]
        }
        run_root = app.ROOT / "curation_data" / "research_runs"
        for directory in run_root.glob("research_*"):
            if not directory.is_dir():
                continue
            try:
                launch = app.json.loads((directory / "process.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                launch = {}
            try:
                manifest = app.json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
            if not launch and not manifest:
                continue
            launch_task_id = str(launch.get("task_run_id") or "")
            research_id = str(manifest.get("run_id") or directory.name)
            if launch_task_id in registered_task_ids or research_id in registered_research_ids:
                continue
            publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
            final_review = manifest.get("final_review") if isinstance(manifest.get("final_review"), dict) else {}
            process_alive = app._research_process_alive(int(launch.get("pid") or 0))
            publication_status = str(publication.get("status") or "")
            if publication_status == "completed":
                run_status, phase = "completed", "已完成"
            elif bool(publication.get("cancelled_by_user")):
                run_status, phase = "cancelled", "用户已中止"
            elif publication_status in {"error", "failed"}:
                run_status, phase = "failed", "四库写入或页面发布失败"
            elif process_alive:
                run_status = "running"
                if publication_status == "running":
                    phase = "四库写入与页面发布"
                elif str(final_review.get("status") or "") == "running":
                    phase = "最终审核 Agent 联网核对"
                else:
                    phase = "六 Agent 研究中"
            else:
                run_status, phase = "failed", "研究进程已停止"
            accepted = int(manifest.get("accepted") or 0)
            review = int(manifest.get("review") or 0)
            detail = (
                f"研究编号 {manifest.get('run_id') or directory.name}；新增更新候选 {accepted} 项；"
                f"仍需审核或失败 {review} 项；当前阶段：{phase}。"
            )
            process_log = directory / "process.log"
            try:
                raw = process_log.read_bytes()
                lines, size = len(raw.splitlines()), len(raw)
            except OSError:
                lines, size = 0, 0
            started_at = str(manifest.get("started_at") or launch.get("launched_at") or "")
            completed_at = str(publication.get("completed_at") or (manifest.get("completed_at") if run_status != "running" else "") or "")
            records.append({
                "task_id": "research:" + directory.name,
                "task_run_id": directory.name,
                "kind": "four-database-research",
                "kind_label": "03:00四库研究",
                "title": "四库资料研究与更新",
                "scope": f"六 Agent 最新资料研究（{started_at[:10] or directory.name}）",
                "run_status": run_status,
                "started_at_hkt": started_at,
                "completed_at_hkt": completed_at,
                "duration_ms": 0,
                "lines": lines,
                "bytes": size,
                "status_detail": detail if run_status != "running" else "",
                "backend_pid": 0,
                "worker_pid": int(launch.get("pid") or 0) if process_alive else 0,
                "phase": phase,
                "progress_detail": detail,
                "heartbeat_at_hkt": str(final_review.get("started_at") or manifest.get("completed_at") or started_at),
                "source": "research-run-archive",
            })
        return records

    publish(app, _orphan_research_tasks)

    def _annotate_task_retries(tasks: list[dict]) -> None:
        """Number only failure-driven or explicitly recorded automatic retries."""
        attempts: dict[tuple[str, str, str, str], dict[str, object]] = {}
        ordered = sorted(
            tasks,
            key=lambda item: str(
                item.get("started_at_hkt") or item.get("completed_at_hkt") or ""
            ),
        )
        for task in ordered:
            started_at = str(task.get("started_at_hkt") or task.get("completed_at_hkt") or "")
            key = (
                str(task.get("kind") or ""),
                str(task.get("title") or ""),
                str(task.get("scope") or ""),
                started_at[:10],
            )
            previous = attempts.get(key) or {}
            previous_failed = bool(previous.get("failed"))
            retry_index = int(previous.get("retry_index") or 0) + 1 if previous_failed else 0
            explicit_retry_count = task.get("retry_count")
            if explicit_retry_count is not None:
                try:
                    # A recorded zero starts a new run, even after same-day failures.
                    retry_index = max(0, int(explicit_retry_count))
                except (TypeError, ValueError):
                    pass
            task["retry_index"] = retry_index
            attempts[key] = {
                "retry_index": retry_index,
                "failed": (
                    str(task.get("run_status") or "") in {"failed", "cutoff"}
                    or bool(task.get("interrupted"))
                ),
            }

    publish(app, _annotate_task_retries)

    def _project_monitor_handlers() -> dict[str, dict]:
        """Merge Feishu-card and dashboard checkbox actions by latest handled time."""
        handlers: dict[str, dict] = {}
        try:
            action_state = app.json.loads(app.PROJECT_MONITOR_ACTIONS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            action_state = {}
        handled_messages = action_state.get("handled_messages") if isinstance(action_state, dict) else {}
        candidates = list(handled_messages.values()) if isinstance(handled_messages, dict) else []
        try:
            for line in app.PROJECT_MONITOR_WEB_ACTIONS_PATH.read_text(encoding="utf-8").splitlines():
                item = app.json.loads(line)
                if isinstance(item, dict):
                    candidates.append(item)
        except (OSError, ValueError, TypeError):
            pass
        for handled in candidates:
            if not isinstance(handled, dict):
                continue
            incident_id = str(handled.get("incident_id") or "")
            if not incident_id:
                continue
            previous = handlers.get(incident_id, {})
            handled_at = str(handled.get("handled_at_hkt") or handled.get("completed_at_hkt") or "")
            previous_at = str(previous.get("handled_at_hkt") or previous.get("completed_at_hkt") or "")
            if handled_at >= previous_at:
                handlers[incident_id] = handled
        return {
            incident_id: handled
            for incident_id, handled in handlers.items()
            if str(handled.get("status") or "completed") == "completed"
            and str(handled.get("operator_name") or "").strip()
        }

    publish(app, _project_monitor_handlers)

    def sync_project_monitor_sheet_handlers(*, force: bool = False) -> dict:
        """Consume direct Feishu ledger edits before serving the alarm screen."""
        try:
            return app.CardActionHandler(runtime_root=app.ROOT).sync_handlers_from_sheet(force=force)
        except Exception as exc:
            # Handler reconciliation is a periodic cache refresh. A slow Feishu
            # read must preserve the last verified mapping and retry later instead
            # of emitting a traceback that the project monitor treats as a new P1.
            detail = str(exc).lower()
            transient = isinstance(exc, (app.subprocess.TimeoutExpired, TimeoutError)) or any(
                marker in detail
                for marker in (
                    "connect: operation timed out",
                    "connection reset",
                    "dial tcp",
                    "i/o timeout",
                    "rate limit",
                    "temporarily unavailable",
                    "timed out",
                    "timeout",
                )
            )
            if transient:
                app.logging.warning(
                    "project monitor sheet handler reconciliation timed out; "
                    "retaining the last verified mapping"
                )
                return {"status": "deferred", "changes": 0, "error": str(exc)[:240]}
            app.logging.exception("project monitor sheet handler reconciliation failed")
            return {"status": "failed", "changes": 0, "error": str(exc)[:240]}

    publish(app, sync_project_monitor_sheet_handlers)

