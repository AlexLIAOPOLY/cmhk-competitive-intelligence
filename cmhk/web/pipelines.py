from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import queue

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def start_scheduler_with_backend() -> None:
        """Run the Feishu scheduler and strategic briefing monitor with the APP backend."""
        import threading as scheduler_threading
        import traceback as scheduler_traceback

        disable_all = app.os.environ.get(
            "CMHK_DISABLE_EMBEDDED_SCHEDULER", ""
        ).strip().lower() in {"1", "true", "yes"}
        disable_frequency = app.os.environ.get(
            "CMHK_DISABLE_FREQUENCY_SCHEDULER", ""
        ).strip().lower() in {"1", "true", "yes"}

        def scheduler_worker() -> None:
            import scheduler

            while True:
                try:
                    scheduler.main()
                except Exception:
                    scheduler_traceback.print_exc()
                app.time.sleep(10)

        if not disable_all and not disable_frequency:
            thread = scheduler_threading.Thread(target=scheduler_worker, name="feishu-frequency-scheduler", daemon=True)
            thread.start()
            print("Feishu frequency scheduler started with APP backend", flush=True)

        if (
            not disable_all
            and app.os.environ.get(
                "CMHK_DISABLE_STRATEGIC_BRIEFING_MONITOR", ""
            ).strip().lower()
            not in {"1", "true", "yes"}
        ):
            def strategic_briefing_worker() -> None:
                import strategic_briefing

                while True:
                    try:
                        strategic_briefing.main()
                    except Exception:
                        scheduler_traceback.print_exc()
                    app.time.sleep(10)

            briefing_thread = scheduler_threading.Thread(
                target=strategic_briefing_worker,
                name="strategic-briefing-monitor",
                daemon=True,
            )
            briefing_thread.start()

            # News discovery runs inside strategic_briefing._run_scan so discovery,
            # review-sheet synchronization and group reporting form one ordered task.
            # A second 03:00/14:00 worker would race the Feishu write and report stale counts.
            print("Strategic briefing monitor started with APP backend", flush=True)

    publish(app, start_scheduler_with_backend)

    def run_crawl() -> dict:
        started = app.time.time()
        crawl_env = app.os.environ.copy()
        crawl_env.pop("CMHK_ROWS", None)
        crawl_env["CMHK_CRAWL_TRIGGER"] = "手动全量"
        crawl_env["CMHK_CRAWL_SCOPE"] = "全量（第2-34行）"
        proc = app.subprocess.run(
            [app.sys.executable, str(app.ROOT / "crawl.py")],
            cwd=str(app.ROOT),
            env=crawl_env,
            text=True,
            capture_output=True,
            timeout=1200,
        )
        main_sync = None
        performance_sync = None
        metrics_refresh = None
        agent_trace_sync = None
        if proc.returncode == 0 and (app.ROOT / "write_payload.json").exists():
            main_sync = app.subprocess.run(
                [app.sys.executable, str(app.ROOT / "daily_crawl_and_write.py"), "--sync-only"],
                cwd=str(app.ROOT),
                env=crawl_env,
                text=True,
                capture_output=True,
                timeout=600,
            )
            app.subprocess.run(
                [app.sys.executable, str(app.ROOT / "tools" / "maintenance" / "update_sources_from_crawl.py")],
                cwd=str(app.ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            performance_sync = app.run_carrier_performance_sync()
            metrics_refresh = app.run_company_metrics_refresh()
            if main_sync.returncode == 0 and metrics_refresh["ok"]:
                sync_result = app.json_object_from_output(main_sync.stdout)
                log_sheet_id = str(sync_result.get("log_sheet_id") or "")
                agent_run_id = str(app.load_curation_status().get("run_id") or "")
                if log_sheet_id and agent_run_id:
                    agent_trace_sync = app.append_agent_trace_to_feishu_log(log_sheet_id, agent_run_id)
        result = {
            "ok": proc.returncode == 0
            and (main_sync is None or main_sync.returncode == 0)
            and (performance_sync is None or performance_sync["ok"])
            and (metrics_refresh is None or metrics_refresh["ok"])
            and (agent_trace_sync is None or agent_trace_sync["ok"]),
            "returnCode": proc.returncode,
            "durationMs": round((app.time.time() - started) * 1000),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "mainFeishuSync": None
            if main_sync is None
            else {
                "ok": main_sync.returncode == 0,
                "stdout": main_sync.stdout.strip(),
                "stderr": main_sync.stderr.strip(),
            },
            "carrierPerformanceSync": performance_sync,
            "companyMetricsRefresh": metrics_refresh,
            "agentTraceFeishuSync": agent_trace_sync,
            "status": app.build_status(),
        }
        result["crawlRunRegistry"] = app.register_crawl_run(
            crawl_return_code=proc.returncode,
            duration_ms=result["durationMs"],
            sync_result=app.json_object_from_output(main_sync.stdout) if main_sync and main_sync.returncode == 0 else {},
            metrics_refresh=metrics_refresh or {},
            trace_sync=agent_trace_sync or {},
            trigger="api-crawl",
        )
        return result

    publish(app, run_crawl)

    def run_company_metrics_refresh() -> dict:
        started = app.time.time()
        # A full web crawl must act on high-priority evidence gaps, not merely record
        # them. Keep the retry bounded to one round and six rows.
        command = [
            app.sys.executable,
            str(app.ROOT / "run_data_curation.py"),
            "--recrawl-gaps",
            "--max-recrawl-rows",
            "6",
            "--max-recrawl-rounds",
            "1",
            "--ai-workers",
            app.os.environ.get("CMHK_AI_WORKERS", "3"),
            "--search-verify-workers",
            app.os.environ.get("CMHK_SEARCH_VERIFY_WORKERS", "4"),
        ]
        search_verify_online = app.os.environ.get("CMHK_SEARCH_VERIFY_ONLINE", "1").lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if search_verify_online:
            command.extend(
                [
                    "--search-verify-online",
                    "--search-verify-online-limit",
                    app.os.environ.get("CMHK_SEARCH_VERIFY_ONLINE_LIMIT", "0"),
                ]
            )
        proc = app.subprocess.run(
            command,
            cwd=str(app.ROOT),
            text=True,
            capture_output=True,
            timeout=2400,
        )
        payload = app.build_company_metrics_payload()
        return {
            "ok": proc.returncode == 0,
            "returnCode": proc.returncode,
            "durationMs": round((app.time.time() - started) * 1000),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "summary": payload.get("summary", {}),
        }

    publish(app, run_company_metrics_refresh)

    def stream_company_metrics_refresh(
        handler: BaseHTTPRequestHandler,
        extra_args: list[str] | None = None,
    ) -> dict:
        started = app.time.time()
        command = [
            app.sys.executable,
            "-u",
            str(app.ROOT / "run_data_curation.py"),
            "--recrawl-gaps",
            "--max-recrawl-rows",
            "6",
            "--max-recrawl-rounds",
            "1",
            "--ai-workers",
            app.os.environ.get("CMHK_AI_WORKERS", "3"),
            "--search-verify-workers",
            app.os.environ.get("CMHK_SEARCH_VERIFY_WORKERS", "4"),
            *(extra_args or []),
        ]
        search_verify_online = app.os.environ.get("CMHK_SEARCH_VERIFY_ONLINE", "1").lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if search_verify_online:
            command.extend(
                [
                    "--search-verify-online",
                    "--search-verify-online-limit",
                    app.os.environ.get("CMHK_SEARCH_VERIFY_ONLINE_LIMIT", "0"),
                ]
            )
        env = app.os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        app.write_sse(
            handler,
            {
                "type": "agent_trace",
                "trace": {
                    "ts": app.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "node": "多 Agent 编排器",
                    "phase": "tool_call",
                    "event_type": "tool_call",
                    "message": "启动 LangGraph 多 Agent 数据整理进程。",
                    "tool": "run_data_curation.py",
                    "input": {
                        "command": command,
                        "workflow": [
                            "证据接收",
                            "来源分类",
                            "事实抽取",
                            "主体校验",
                            "质量审计",
                            "冲突仲裁",
                            "搜索验证",
                            "缺口规划",
                            "Supervisor 工具决策",
                            "定向补爬（最多 6 行、1 轮）",
                            "发布",
                        ],
                    },
                },
            },
        )
        proc = app.subprocess.Popen(
            command,
            cwd=str(app.ROOT),
            env=env,
            stdout=app.subprocess.PIPE,
            stderr=app.subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        line_queue: queue.Queue[str | None] = app.queue.Queue()
        output_lines: list[str] = []

        def read_output() -> None:
            if proc.stdout:
                for raw_line in proc.stdout:
                    line_queue.put(raw_line.rstrip("\n"))
            line_queue.put(None)

        app.threading.Thread(target=read_output, daemon=True).start()
        finished_reading = False
        while not finished_reading:
            try:
                line = line_queue.get(timeout=10)
            except app.queue.Empty:
                elapsed = round(app.time.time() - started)
                app.write_sse(
                    handler,
                    {
                        "type": "agent_trace",
                        "trace": {
                            "ts": app.datetime.now().astimezone().isoformat(timespec="seconds"),
                            "node": "多 Agent 编排器",
                            "phase": "observe",
                            "event_type": "agent",
                            "message": f"Agent 仍在处理，已运行 {elapsed} 秒；正在等待当前工具或模型返回。",
                            "output": {"elapsedSeconds": elapsed, "processId": proc.pid},
                        },
                    },
                )
                continue
            if line is None:
                finished_reading = True
                continue
            if not line:
                continue
            output_lines.append(line)
            app.write_sse(handler, app.sse_payload_from_process_line(line))

        proc.wait()
        payload = app.build_company_metrics_payload()
        duration_ms = round((app.time.time() - started) * 1000)
        app.write_sse(
            handler,
            {
                "type": "agent_trace",
                "trace": {
                    "ts": app.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "node": "多 Agent 编排器",
                    "phase": "tool_result",
                    "event_type": "tool_result",
                    "message": "LangGraph 多 Agent 数据整理进程已结束。",
                    "tool": "run_data_curation.py",
                    "result": {
                        "returnCode": proc.returncode,
                        "durationMs": duration_ms,
                        "summary": payload.get("summary", {}),
                    },
                },
            },
        )
        return {
            "ok": proc.returncode == 0,
            "returnCode": proc.returncode,
            "durationMs": duration_ms,
            "stdout": "\n".join(output_lines),
            "stderr": "",
            "summary": payload.get("summary", {}),
        }

    publish(app, stream_company_metrics_refresh)

    def run_carrier_performance_sync() -> dict:
        env = app.os.environ.copy()
        proc = app.subprocess.run(
            [app.sys.executable, str(app.ROOT / "tools" / "integrations" / "sync_carrier_performance_feishu.py")],
            cwd=str(app.ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        return {
            "ok": proc.returncode == 0,
            "returnCode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }

    publish(app, run_carrier_performance_sync)

    def build_weekly_report_generation_preview(now: datetime | None = None) -> dict[str, object]:
        """Describe the exact input window and approved rows a new weekly run would use."""
        from generate_weekly_report import resolve_weekly_period
        from cmhk.intelligence.news_review_sheet import load_weekly_report_candidates

        period = resolve_weekly_period(now)
        effective_range = period.effective_range
        rows, selection_audit = load_weekly_report_candidates(
            effective_range["start"],
            effective_range["end"],
        )
        return {
            "windowStart": effective_range["start"],
            "windowEnd": effective_range["end"],
            "newsCount": len(rows),
            "acceptedRows": int(selection_audit.get("acceptedRows") or 0),
            "excludedRows": int(selection_audit.get("excludedRows") or 0),
            "refreshedAt": period.as_of.isoformat(timespec="seconds"),
            "selectionSource": str(selection_audit.get("selectionSource") or ""),
        }

    publish(app, build_weekly_report_generation_preview)

    def run_report_generation() -> dict:
        started = app.time.time()
        proc = app.subprocess.run(
            [app.sys.executable, str(app.ROOT / "generate_weekly_report.py")],
            cwd=str(app.ROOT),
            text=True,
            capture_output=True,
            timeout=2400,
        )
        status = app.build_status()
        from cmhk.reporting.report_audio_pipeline import audio_result_from_output
        audio_result = audio_result_from_output(proc.stdout or "") if proc.returncode == 0 else None
        if proc.returncode == 0 and audio_result is None:
            try:
                latest_path = app.latest_output_path(status, "weekly")
                audio_result = app.synthesize_report_audio(latest_path, force=False)
                status = app.build_status()
            except Exception as exc:
                audio_result = {"ok": False, "error": str(exc)}
        return {
            "ok": proc.returncode == 0,
            "returnCode": proc.returncode,
            "durationMs": round((app.time.time() - started) * 1000),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "reportGenerated": proc.returncode == 0,
            "completedWithWarnings": proc.returncode == 0 and bool(audio_result and not audio_result.get("ok")),
            "audio": audio_result,
            "status": status,
        }

    publish(app, run_report_generation)

    def run_carrier_performance_generation() -> dict:
        started = app.time.time()
        env = app.os.environ.copy()
        proc = app.subprocess.run(
            [app.sys.executable, str(app.ROOT / "generate_carrier_performance_report.py")],
            cwd=str(app.ROOT),
            text=True,
            capture_output=True,
            timeout=2400,
        )
        status = app.build_status()
        from cmhk.reporting.report_audio_pipeline import audio_result_from_output
        audio_result = audio_result_from_output(proc.stdout or "") if proc.returncode == 0 else None
        if proc.returncode == 0 and audio_result is None:
            try:
                latest_path = app.latest_output_path(status, "carrier-performance")
                audio_result = app.synthesize_report_audio(latest_path, force=False)
                status = app.build_status()
            except Exception as exc:
                audio_result = {"ok": False, "error": str(exc)}
        return {
            "ok": proc.returncode == 0,
            "returnCode": proc.returncode,
            "durationMs": round((app.time.time() - started) * 1000),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "reportGenerated": proc.returncode == 0,
            "completedWithWarnings": proc.returncode == 0 and bool(audio_result and not audio_result.get("ok")),
            "audio": audio_result,
            "status": status,
        }

    publish(app, run_carrier_performance_generation)

    def latest_output_path(status: dict, report_type: str) -> Path:
        output = next((item for item in status.get("outputs", []) if item.get("reportType") == report_type), None)
        if not output:
            raise FileNotFoundError(f"未找到最新输出：{report_type}")
        return app.ROOT / output["path_str"]

    publish(app, latest_output_path)

    def stream_report_generation(
        handler: BaseHTTPRequestHandler,
        script_name: str,
        report_type: str,
        script_args: list[str] | None = None,
    ) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()

        started = app.time.time()
        proc = app.subprocess.Popen(
            [app.sys.executable, "-u", str(app.ROOT / script_name), *(script_args or [])],
            cwd=str(app.ROOT),
            stdout=app.subprocess.PIPE,
            stderr=app.subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        handler._task_worker_pid = proc.pid
        handler._task_monitor_phase = "报告生成"
        handler._task_monitor_detail = "报告生成进程正在执行。"
        from cmhk.reporting.report_audio_pipeline import audio_result_from_output, RESULT_PREFIX
        audio_result = None
        created_path = None
        if proc.stdout:
            for line in proc.stdout:
                text = line.strip()
                if text.startswith(RESULT_PREFIX):
                    audio_result = audio_result_from_output(text)
                    continue
                if text.startswith("[生成语音摘要]"):
                    handler._task_monitor_phase = "生成语音摘要"
                    handler._task_monitor_detail = "报告文档已完成，正在自动生成对应语音。"
                app.write_sse(handler, app.sse_payload_from_process_line(text))
                if text.startswith("->"):
                    candidate = app.Path(text[2:].strip())
                    if candidate.exists() and candidate.name.endswith(".docx") and "template" not in candidate.name:
                        created_path = candidate
        proc.wait()
        handler._task_worker_pid = 0

        status = app.build_status()
        if proc.returncode == 0 and audio_result is None:
            try:
                latest_path = created_path if created_path and created_path.exists() else app.latest_output_path(status, report_type)
                app.write_sse(handler, {"type": "log", "text": "报告生成完成。开始生成语音摘要..."})
                code = "import sys, json\nfrom pathlib import Path\nfrom tts_service import synthesize_report_audio\ntry:\n    res = synthesize_report_audio(Path(sys.argv[1]), force=sys.argv[2] == 'True')\n    print(json.dumps({'ok': True, 'result': res}))\nexcept Exception as e:\n    print(json.dumps({'ok': False, 'error': str(e)}))"
                handler._task_monitor_phase = "生成语音摘要"
                handler._task_monitor_detail = "报告文档已完成，正在调用公司内部语音模型。"
                proc_audio = app.subprocess.Popen(
                    [app.sys.executable, "-c", code, str(latest_path), "False"],
                    stdout=app.subprocess.PIPE,
                    stderr=app.subprocess.PIPE,
                    text=True,
                )
                handler._task_worker_pid = proc_audio.pid
                audio_stdout, audio_stderr = proc_audio.communicate()
                handler._task_worker_pid = 0
                try:
                    out = app.json.loads(audio_stdout)
                    if not out.get("ok"):
                        raise Exception(out.get("error"))
                    audio_result = out.get("result")
                    if not audio_result.get("ok"):
                        raise Exception(audio_result.get("error"))
                except Exception as e:
                    raise Exception(f"Audio generation failed: {audio_stderr} | {e}")
                status = app.build_status()
                app.write_sse(handler, {"type": "log", "text": "✅ 语音摘要生成完成。"})
            except Exception as exc:
                audio_result = {"ok": False, "error": str(exc)}
                app.write_sse(handler, {"type": "log", "text": f"❌ 语音摘要生成失败: {exc}"})

        audio_failed = isinstance(audio_result, dict) and audio_result.get("ok") is False
        task_ok = proc.returncode == 0
        warning_detail = str((audio_result or {}).get("error") or "") if audio_failed else ""
        report_label = "周报" if report_type == "weekly" else "业绩摘要"
        if task_ok and audio_failed:
            message = f"{report_label}已生成；语音摘要未完成：{warning_detail}"
        elif task_ok:
            message = "报告及语音摘要均已生成。"
        else:
            message = f"{report_label}生成进程未成功完成。"
        app.write_sse(
            handler,
            {
                "type": "done",
                "ok": task_ok,
                "completedWithWarnings": task_ok and audio_failed,
                "reportGenerated": task_ok,
                "error": "" if task_ok else message,
                "warning": warning_detail,
                "message": message,
                "durationMs": round((app.time.time() - started) * 1000),
                "audio": audio_result,
                "status": status,
            },
        )

    publish(app, stream_report_generation)
