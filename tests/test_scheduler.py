from __future__ import annotations

import json
import multiprocessing
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import daily_crawl_and_write
import cmhk.crawl.run_registry as crawl_run_registry
import scheduler


def _save_registry_record_in_process(
    registry_dir_text: str,
    crawl_run_id: str,
    ready: multiprocessing.Queue,
    start: multiprocessing.Event,
) -> None:
    registry_dir = Path(registry_dir_text)
    crawl_run_registry.REGISTRY_DIR = registry_dir
    crawl_run_registry.RUNS_DIR = registry_dir / "runs"
    crawl_run_registry.INDEX_JSON = registry_dir / "index.json"
    crawl_run_registry.LATEST_JSON = registry_dir / "latest.json"
    crawl_run_registry.INDEX_MD = registry_dir / "index.md"
    crawl_run_registry.LOCK_FILE = registry_dir / ".registry.lock"
    ready.put(crawl_run_id)
    start.wait(timeout=5)
    crawl_run_registry._save_run_record(
        {
            "crawl_run_id": crawl_run_id,
            "run_status": "completed",
            "completed_at_hkt": "2026-08-07T03:27:09+08:00",
        }
    )


class FeishuCliEnvironmentTests(unittest.TestCase):
    def test_live_schedule_uses_recent_verified_cache_after_transient_failures(self) -> None:
        failed = subprocess.CompletedProcess(
            ["lark-cli"],
            1,
            stdout="",
            stderr=json.dumps({
                "ok": False,
                "error": {"type": "network", "subtype": "timeout", "message": "dial tcp: i/o timeout"},
            }),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "live_schedule_cache.json"
            cache_path.write_text(json.dumps({
                "version": 1,
                "verified_at_hkt": scheduler.datetime.now(scheduler.HKT).isoformat(timespec="seconds"),
                "rows": [{"row": 2, "frequency": "每天 03:00"}],
            }), encoding="utf-8")
            with (
                mock.patch.object(scheduler, "LIVE_SCHEDULE_CACHE_PATH", cache_path),
                mock.patch.object(scheduler, "SCHEDULE_READ_ATTEMPTS", 3),
                mock.patch.object(scheduler.subprocess, "run", return_value=failed) as run,
                mock.patch.object(scheduler.time, "sleep"),
            ):
                rows = scheduler.read_live_schedule()

        self.assertEqual(rows, [{"row": 2, "frequency": "每天 03:00"}])
        self.assertEqual(run.call_count, 3)

    def test_live_schedule_does_not_mask_non_transient_permission_error(self) -> None:
        failed = subprocess.CompletedProcess(
            ["lark-cli"],
            1,
            stdout="",
            stderr='{"ok":false,"error":{"type":"permission","message":"forbidden"}}',
        )
        with (
            mock.patch.object(scheduler.subprocess, "run", return_value=failed) as run,
            mock.patch.object(scheduler.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                scheduler.read_live_schedule()
        self.assertEqual(run.call_count, 1)

    def test_financial_frontend_publish_requires_verified_public_version(self) -> None:
        completed = subprocess.CompletedProcess(
            ["publish"],
            0,
            stdout=(
                '{"status":"published","site_version":"version-1",'
                '"public_url":"https://example.github.io/site/","commit":"abc"}\n'
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            with (
                mock.patch.dict(
                    scheduler.os.environ,
                    {"CMHK_FORCE_FINANCIAL_FRONTEND_PUBLISH_FOR_TESTS": "1"},
                ),
                mock.patch.object(scheduler.subprocess, "run", return_value=completed),
            ):
                result = scheduler._publish_financial_frontend(log_path)

        self.assertTrue(result["ok"])
        self.assertEqual(result["site_version"], "version-1")
        self.assertEqual(result["commit"], "abc")

    def test_json_object_parser_keeps_last_complete_sync_summary(self) -> None:
        output = (
            'progress {not json}\n'
            '{"phase":"partial","ok":true}\n'
            'done\n'
            '{"ok":true,"log_sheet_id":"sheet-final","nested":{"rows":4}}\n'
        )

        self.assertEqual(
            scheduler._json_object_from_output(output),
            {"ok": True, "log_sheet_id": "sheet-final", "nested": {"rows": 4}},
        )

    def test_run_cmd_always_disables_proxy(self) -> None:
        completed = subprocess.CompletedProcess(["lark-cli"], 0, stdout="{}", stderr="")
        with (
            mock.patch.dict(
                daily_crawl_and_write.os.environ,
                {
                    "HTTP_PROXY": "http://127.0.0.1:7897",
                    "HTTPS_PROXY": "http://127.0.0.1:7897",
                },
            ),
            mock.patch.object(daily_crawl_and_write.subprocess, "run", return_value=completed) as run,
        ):
            daily_crawl_and_write.run_cmd(["lark-cli", "auth", "status"])

        command_env = run.call_args.kwargs["env"]
        self.assertEqual(command_env["LARK_CLI_NO_PROXY"], "1")
        self.assertNotIn("HTTP_PROXY", command_env)
        self.assertNotIn("HTTPS_PROXY", command_env)


class CrawlRunReconciliationTests(unittest.TestCase):
    def test_index_uses_authoritative_terminal_run_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_dir = Path(temp_dir)
            runs_dir = registry_dir / "runs"
            runs_dir.mkdir()
            (registry_dir / "index.json").write_text(
                json.dumps([{"crawl_run_id": "crawl-1", "run_status": "running"}]),
                encoding="utf-8",
            )
            (runs_dir / "crawl-1.json").write_text(
                json.dumps({"crawl_run_id": "crawl-1", "run_status": "completed"}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(crawl_run_registry, "INDEX_JSON", registry_dir / "index.json"),
                mock.patch.object(crawl_run_registry, "RUNS_DIR", runs_dir),
            ):
                index = crawl_run_registry.load_index()

        self.assertEqual(index[0]["run_status"], "completed")

    def test_delayed_heartbeat_cannot_reopen_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_dir = Path(temp_dir)
            runs_dir = registry_dir / "runs"
            runs_dir.mkdir()
            completed = {"crawl_run_id": "crawl-1", "run_status": "completed"}
            (runs_dir / "crawl-1.json").write_text(json.dumps(completed), encoding="utf-8")
            (registry_dir / "index.json").write_text(json.dumps([completed]), encoding="utf-8")
            patches = (
                mock.patch.object(crawl_run_registry, "REGISTRY_DIR", registry_dir),
                mock.patch.object(crawl_run_registry, "RUNS_DIR", runs_dir),
                mock.patch.object(crawl_run_registry, "INDEX_JSON", registry_dir / "index.json"),
                mock.patch.object(crawl_run_registry, "LATEST_JSON", registry_dir / "latest.json"),
                mock.patch.object(crawl_run_registry, "INDEX_MD", registry_dir / "index.md"),
                mock.patch.object(crawl_run_registry, "LOCK_FILE", registry_dir / ".registry.lock"),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                saved = crawl_run_registry._save_run_record(
                    {"crawl_run_id": "crawl-1", "run_status": "running"}
                )

        self.assertEqual(saved["run_status"], "completed")

    def test_concurrent_process_writes_do_not_lose_index_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            context = multiprocessing.get_context("fork")
            ready = context.Queue()
            start = context.Event()
            processes = [
                context.Process(
                    target=_save_registry_record_in_process,
                    args=(temp_dir, crawl_run_id, ready, start),
                )
                for crawl_run_id in ("crawl-parent", "crawl-child")
            ]
            for process in processes:
                process.start()
            self.assertEqual({ready.get(timeout=5), ready.get(timeout=5)}, {"crawl-parent", "crawl-child"})
            start.set()
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            index = json.loads((Path(temp_dir) / "index.json").read_text(encoding="utf-8"))

        self.assertEqual(
            {item["crawl_run_id"] for item in index},
            {"crawl-parent", "crawl-child"},
        )

    def test_live_external_scheduler_is_not_marked_interrupted(self) -> None:
        record = {
            "crawl_run_id": "crawl-live-external",
            "run_status": "running",
            "backend_pid": 12345,
            "worker_pid": 0,
        }
        with (
            mock.patch.object(crawl_run_registry, "load_index", return_value=[record]),
            mock.patch.object(
                crawl_run_registry,
                "_pid_alive",
                side_effect=lambda pid: pid == 12345,
            ),
            mock.patch.object(
                crawl_run_registry,
                "mark_crawl_run_interrupted",
            ) as mark_interrupted,
        ):
            updated = crawl_run_registry.reconcile_interrupted_crawl_runs()

        self.assertEqual(updated, [])
        mark_interrupted.assert_not_called()

    def test_run_cmd_retries_eof_without_enabling_proxy(self) -> None:
        failed = subprocess.CompletedProcess(
            ["lark-cli"],
            1,
            stdout='{"ok":false,"error":{"message":"API call failed: EOF"}}',
            stderr="",
        )
        succeeded = subprocess.CompletedProcess(["lark-cli"], 0, stdout='{"ok":true}', stderr="")
        with (
            mock.patch.object(daily_crawl_and_write.subprocess, "run", side_effect=[failed, succeeded]) as run,
            mock.patch.object(daily_crawl_and_write.time, "sleep"),
        ):
            output = daily_crawl_and_write.run_cmd(["lark-cli", "sheets", "+read"])

        self.assertEqual(json.loads(output), {"ok": True})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"]["LARK_CLI_NO_PROXY"], "1")


class ScheduledAgentAuditTests(unittest.TestCase):
    def test_validated_summary_accepts_only_verified_review_isolation(self) -> None:
        run_id = "scheduled-quarantined"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs = root / "curation_data" / "runs"
            runs.mkdir(parents=True)
            summary = {
                "run_id": run_id, "completed_at": "2026-09-03T09:00:00+08:00", "accepted": 1,
                "extra": {
                    "search_verification": {"online_search": True, "online_coverage_complete": True},
                    "company_agent_summary": {"required": True, "coverage_complete": False, "publish_ready": False},
                    "overall_status": "completed_with_review",
                    "publication_review": {"policy": "quarantine_unresolved_companies_v1", "companies": ["AWS"],
                                           "entities": ["aws"], "candidate_ids": ["bad"]},
                },
            }
            (runs / f"{run_id}.json").write_text(json.dumps(summary))
            (runs / f"{run_id}_agent_trace.jsonl").write_text("\n".join(
                json.dumps({"run_id": run_id, "node": node}) for node in scheduler.REQUIRED_AGENT_NODES))
            facts = [{"id": "bad", "company": "AWS", "decision": "review"},
                     {"id": "good", "company": "HKT", "decision": "accepted"}]
            candidate_path = runs / f"{run_id}_candidate_facts.jsonl"
            candidate_path.write_text("\n".join(json.dumps(fact) for fact in facts))
            with mock.patch.object(scheduler, "ROOT", root):
                self.assertEqual(scheduler._validated_curation_summary(run_id)[1], [])
                facts[0]["decision"] = "accepted"
                candidate_path.write_text("\n".join(json.dumps(fact) for fact in facts))
                self.assertIn("待复核隔离清单与候选数据不一致", scheduler._validated_curation_summary(run_id)[1])

    def test_validated_summary_rejects_unresolved_company_agents(self) -> None:
        run_id = "scheduled-unresolved"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs = root / "curation_data" / "runs"
            runs.mkdir(parents=True)
            (runs / f"{run_id}.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "completed_at": "2026-09-01T09:00:00+08:00",
                        "extra": {
                            "search_verification": {
                                "online_search": True,
                                "online_coverage_complete": True,
                            },
                            "company_agent_summary": {
                                "required": True,
                                "expected": 41,
                                "completed": 41,
                                "coverage_complete": True,
                                "expected_metrics": 120,
                                "completed_metrics": 119,
                                "metric_coverage_complete": False,
                                "publish_ready": False,
                                "unresolved_companies": ["AWS"],
                            },
                            "overall_status": "partial",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (runs / f"{run_id}_agent_trace.jsonl").write_text(
                "".join(
                    json.dumps({"run_id": run_id, "node": node}, ensure_ascii=False) + "\n"
                    for node in scheduler.REQUIRED_AGENT_NODES
                ),
                encoding="utf-8",
            )
            with mock.patch.object(scheduler, "ROOT", root):
                _summary, problems = scheduler._validated_curation_summary(run_id)

        self.assertTrue(any("尚有未解决主体：AWS" in problem for problem in problems))
        self.assertTrue(any("尚有未解决指标：119/120" in problem for problem in problems))
        self.assertTrue(any("总体状态未完成：partial" in problem for problem in problems))

    def test_scheduled_agent_uses_stable_checkpoint_and_bounded_online_search(self) -> None:
        self.assertIn("公司研究 Agent", scheduler.REQUIRED_AGENT_NODES)
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            proc = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
            summary = {"agent_run_id": "scheduled_crawl-123", "tasks": 3}
            with (
                mock.patch.object(scheduler.subprocess, "run", return_value=proc) as run,
                mock.patch.object(scheduler, "_validated_curation_summary", return_value=(summary, [])),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.dict(
                    scheduler.os.environ,
                    {"CMHK_SEARCH_VERIFY_ONLINE": "1"},
                    clear=False,
                ),
            ):
                ok, code, curation, trace_sync, error = scheduler._run_scheduled_agent_audit(
                    "crawl-123",
                    log_path,
                    log_sheet_id="",
                    agent_run_id="scheduled_crawl-123",
                )

        self.assertTrue(ok)
        self.assertEqual(code, 0)
        self.assertEqual(curation, summary)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--run-id") + 1], "scheduled_crawl-123")
        self.assertIn("--resume", command)
        self.assertEqual(
            command[command.index("--search-verify-online-limit") + 1],
            scheduler.DEFAULT_AGENT_AUDIT_ONLINE_LIMIT,
        )
        self.assertTrue(trace_sync["skipped"])
        self.assertEqual(error, "")

    def test_scheduled_agent_timeout_retains_checkpoint_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            timeout = subprocess.TimeoutExpired(
                cmd=["python"],
                timeout=scheduler.AGENT_AUDIT_TIMEOUT_SECONDS,
                output='AGENT_TRACE={"run_id":"scheduled_crawl-timeout"}\n',
                stderr="still working\n",
            )
            with (
                mock.patch.object(scheduler.subprocess, "run", side_effect=timeout),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
            ):
                ok, code, curation, trace_sync, error = scheduler._run_scheduled_agent_audit(
                    "crawl-timeout",
                    log_path,
                    agent_run_id="scheduled_crawl-timeout",
                )
            log_text = log_path.read_text(encoding="utf-8")

        self.assertFalse(ok)
        self.assertEqual(code, 124)
        self.assertEqual(curation["agent_run_id"], "scheduled_crawl-timeout")
        self.assertTrue(curation["checkpointed"])
        self.assertEqual(trace_sync, {})
        self.assertIn("超过", error)
        self.assertIn("still working", log_text)

    def test_agent_success_is_not_rejected_when_feishu_log_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            proc = subprocess.CompletedProcess(
                ["python"],
                0,
                stdout='AGENT_TRACE={"run_id":"agent-123"}\n',
                stderr="",
            )
            summary = {"agent_run_id": "agent-123", "tasks": 3}
            with (
                mock.patch.object(scheduler.subprocess, "run", return_value=proc),
                mock.patch.object(scheduler, "_validated_curation_summary", return_value=(summary, [])),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
            ):
                ok, code, curation, trace_sync, error = scheduler._run_scheduled_agent_audit(
                    "crawl-123",
                    log_path,
                    log_sheet_id="",
                )

        self.assertTrue(ok)
        self.assertEqual(code, 0)
        self.assertEqual(curation, summary)
        self.assertTrue(trace_sync["skipped"])
        self.assertEqual(error, "")

    def test_feishu_sync_failure_does_not_skip_agent_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            crawl = subprocess.CompletedProcess(["crawl"], 0, stdout="crawl ok\n", stderr="")
            sync = subprocess.CompletedProcess(["sync"], 1, stdout="", stderr="API call failed: EOF\n")
            curation = {"agent_run_id": "agent-after-sync-failure", "tasks": 4}
            with (
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run"),
                mock.patch.object(
                    scheduler,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "crawl-sync-failure",
                        "stream_log_path": str(log_path),
                    },
                ),
                mock.patch.object(scheduler, "append_crawl_run_event"),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.object(scheduler.subprocess, "run", side_effect=[crawl, sync]),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(True, 0, curation, {"skipped": True}, ""),
                ) as audit,
                mock.patch.object(scheduler, "register_crawl_run") as register,
            ):
                ok = scheduler.run_due_rows([3], {})

        self.assertFalse(ok)
        audit.assert_called_once_with(
            "crawl-sync-failure",
            log_path,
            log_sheet_id="",
            agent_run_id="scheduled_crawl-sync-failure",
        )
        self.assertEqual(register.call_args.kwargs["failure_stage"], "feishu_sync")
        self.assertEqual(register.call_args.kwargs["curation_summary"], curation)
        self.assertIn("Agent 审核已完整执行", register.call_args.kwargs["progress_detail"])

    def test_successful_scheduled_run_captures_news_bridge_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.jsonl"
            log_path.write_text("", encoding="utf-8")
            crawl = subprocess.CompletedProcess(["crawl"], 0, stdout="crawl ok\n", stderr="")
            sync = subprocess.CompletedProcess(
                ["sync"],
                0,
                stdout='{"log_sheet_id":"sheet-1"}',
                stderr="",
            )
            curation = {"agent_run_id": "agent-success", "tasks": 4}
            bridge = {
                "crawl_run_id": "crawl-success",
                "bootstrap": False,
                "page_count": 12,
                "signal_count": 2,
            }
            call_order: list[str] = []
            with (
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run"),
                mock.patch.object(
                    scheduler,
                    "start_crawl_run",
                    return_value={
                        "crawl_run_id": "crawl-success",
                        "stream_log_path": str(log_path),
                    },
                ),
                mock.patch.object(scheduler, "append_crawl_run_event") as append,
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.object(scheduler.subprocess, "run", side_effect=[crawl, sync]),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(True, 0, curation, {"ok": True}, ""),
                ),
                mock.patch.object(
                    scheduler,
                    "capture_completed_crawl",
                    return_value=bridge,
                ) as capture,
                mock.patch.object(
                    scheduler,
                    "read_live_schedule",
                    return_value=[{"row": 3, "frequency": "每天 03:00"}],
                ),
                mock.patch.object(
                    scheduler,
                    "register_crawl_run",
                    side_effect=lambda **kwargs: call_order.append("register") or kwargs,
                ) as register,
                mock.patch.object(
                    scheduler,
                    "_launch_executive_intelligence_refresh",
                    side_effect=lambda *args: call_order.append("launch") or {"ok": True, "launched": True},
                ),
            ):
                state = {}
                ok = scheduler.run_due_rows([3], state)

        self.assertTrue(ok)
        self.assertIn("3", state["last_completed"])
        capture.assert_called_once()
        self.assertEqual(capture.call_args.args[:2], ("crawl-success", [3]))
        self.assertEqual(
            register.call_args.kwargs["curation_summary"]["news_bridge"],
            bridge,
        )
        self.assertEqual(call_order, ["register", "launch", "register"])
        self.assertTrue(
            any(
                call.args[1].get("type") == "news_bridge"
                and call.args[1].get("signalCount") == 2
                for call in append.call_args_list
            )
        )

    def test_interrupted_sync_completed_run_is_recovered_from_archived_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("agent_knowledge/crawl_run_logs/runs/recover.jsonl")
            log_path = root / relative
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '{"log_sheet_id": "sheet-recover"}\n'
                '{"type":"monitor","detail":"网页抓取和飞书同步已完成，正在执行完整 Agent 审核流程。"}\n',
                encoding="utf-8",
            )
            record = {
                "crawl_run_id": "crawl-recover",
                "trigger": "定时爬虫",
                "scope": "定时指定行（第3行、第4行）",
                "run_status": "failed",
                "phase": "已中断",
                "interrupted": True,
                "started_at_hkt": "2026-07-29T15:19:27+08:00",
                "local_files": {"stream_log": str(relative)},
            }
            with (
                mock.patch.object(scheduler, "ROOT", root),
                mock.patch.object(
                    scheduler,
                    "PENDING_RUN_PATH",
                    root / "scheduler_pending_run.json",
                ),
                mock.patch.object(
                    scheduler,
                    "load_crawl_run_index",
                    return_value=[record],
                ),
            ):
                recovered = scheduler._recover_interrupted_pending_run()

        self.assertEqual(recovered["stage"], "sync_completed")
        self.assertEqual(recovered["rows"], [3, 4])
        self.assertEqual(recovered["log_sheet_id"], "sheet-recover")

    def test_resume_from_sync_checkpoint_skips_web_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "resume.jsonl"
            log_path.write_text("", encoding="utf-8")
            pending = {
                "stage": "sync_completed",
                "crawl_run_id": "crawl-resume",
                "rows": [3, 4],
                "scope": "定时指定行（第3行、第4行）",
                "started_at_hkt": "2026-07-29T15:19:27+08:00",
                "stream_log_path": str(log_path),
                "log_sheet_id": "sheet-resume",
                "sync_return_code": 0,
            }
            state = {
                "attempts": {
                    "3": "2026-07-29T15:19:27+08:00",
                    "4": "2026-07-29T15:19:27+08:00",
                }
            }
            with (
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run") as clear_pending,
                mock.patch.object(scheduler, "resume_crawl_run"),
                mock.patch.object(scheduler, "append_crawl_run_event"),
                mock.patch.object(scheduler, "heartbeat_crawl_run"),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(
                        True,
                        0,
                        {"agent_run_id": "agent-resume"},
                        {"ok": True},
                        "",
                    ),
                ) as audit,
                mock.patch.object(
                    scheduler,
                    "capture_completed_crawl",
                    return_value={"page_count": 10, "signal_count": 2},
                ) as bridge,
                mock.patch.object(
                    scheduler,
                    "read_live_schedule",
                    return_value=[
                        {"row": 3, "frequency": "每天 03:00"},
                        {"row": 4, "frequency": "每天 03:00"},
                    ],
                ),
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "register_crawl_run") as register,
                mock.patch.object(scheduler.subprocess, "run") as subprocess_run,
            ):
                ok = scheduler.resume_pending_run(pending, state)

        self.assertTrue(ok)
        audit.assert_called_once_with(
            "crawl-resume",
            log_path,
            log_sheet_id="sheet-resume",
            agent_run_id="scheduled_crawl-resume",
        )
        bridge.assert_called_once()
        subprocess_run.assert_not_called()
        self.assertEqual(state["attempts"], {})
        self.assertIn("3", state["last_completed"])
        self.assertIn("4", state["last_completed"])
        self.assertEqual(register.call_args.kwargs["crawl_return_code"], 0)
        clear_pending.assert_called_once()

    def test_resume_agent_timeout_updates_backoff_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "resume-timeout.jsonl"
            log_path.write_text("", encoding="utf-8")
            pending = {
                "stage": "sync_completed",
                "crawl_run_id": "crawl-timeout",
                "rows": [3],
                "scope": "定时指定行（第3行）",
                "started_at_hkt": "2026-08-27T03:00:00+08:00",
                "stream_log_path": str(log_path),
                "log_sheet_id": "sheet-timeout",
                "sync_return_code": 0,
            }
            with (
                mock.patch.object(scheduler, "_write_pending_run") as write_pending,
                mock.patch.object(scheduler, "resume_crawl_run"),
                mock.patch.object(scheduler, "append_crawl_run_event"),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(
                        False,
                        124,
                        {"agent_run_id": "scheduled_crawl-timeout", "checkpointed": True},
                        {},
                        "Agent 审核超过 3600 秒",
                    ),
                ),
                mock.patch.object(scheduler, "register_crawl_run") as register,
            ):
                ok = scheduler.resume_pending_run(pending, {})

        self.assertFalse(ok)
        self.assertEqual(pending["stage"], "sync_completed")
        self.assertEqual(pending["agent_audit_run_id"], "scheduled_crawl-timeout")
        self.assertEqual(pending["agent_audit_attempt_count"], 1)
        self.assertIn("超过", pending["agent_audit_last_error"])
        self.assertTrue(pending["last_attempt_at_hkt"])
        self.assertGreaterEqual(write_pending.call_count, 3)
        self.assertEqual(register.call_args.kwargs["failure_stage"], "agent_review")

    def test_intelligence_refresh_is_never_spawned_during_packaged_unittest_discovery(self) -> None:
        with mock.patch.object(scheduler, "ROOT", Path(scheduler.__file__).resolve().parent):
            result = scheduler._launch_executive_intelligence_refresh(
                "crawl-test",
                Path("/tmp/test-stream.jsonl"),
                {"agent_run_id": "agent-test"},
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["launched"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "non_production_root")

    def test_resume_from_sync_checkpoint_reapplies_financial_and_frontend_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "resume-finance.jsonl"
            log_path.write_text("", encoding="utf-8")
            pending = {
                "stage": "sync_completed",
                "crawl_run_id": "crawl-finance-resume",
                "rows": [2],
                "scope": "定时指定行（第2行）",
                "started_at_hkt": "2026-08-14T03:00:00+08:00",
                "stream_log_path": str(log_path),
                "log_sheet_id": "sheet-finance",
                "sync_return_code": 0,
            }
            refresh = {
                "generated_at_hkt": "2026-08-14T03:10:00+08:00",
                "schedule_policy": "next-day",
                "database_path": "cmhk.data.local_financial_results.json",
                "database_updated": True,
                "database_changed": False,
                "quality": {"ok": True, "failures": []},
                "last_check": [{
                    "row": 2,
                    "company": "HKT",
                    "verification_status": "official_document_extracted",
                    "period": "H1 2026",
                    "publication_date": "2026-07-29",
                    "due_at_hkt": "2026-07-30T03:00:00+08:00",
                    "source_url": "https://www.hkt.com/report.pdf",
                    "core_metric_count": 2,
                    "metrics": [],
                }],
            }
            state: dict[str, object] = {"attempts": {"2": "2026-08-14T03:00:00+08:00"}}
            with (
                mock.patch("cmhk.data.local_financial_results.rebuild_local_financial_database", return_value=refresh) as rebuild,
                mock.patch.object(scheduler, "_publish_financial_frontend", return_value={
                    "ok": True,
                    "status": "verified",
                    "site_version": "site-finance",
                    "public_url": "https://example.github.io/project/",
                }) as publish,
                mock.patch.object(scheduler, "_write_pending_run") as write_pending,
                mock.patch.object(scheduler, "_clear_pending_run"),
                mock.patch.object(scheduler, "resume_crawl_run"),
                mock.patch.object(scheduler, "append_crawl_run_event"),
                mock.patch.object(
                    scheduler,
                    "_run_scheduled_agent_audit",
                    return_value=(
                        True,
                        0,
                        {"agent_run_id": "scheduled_crawl-finance-resume"},
                        {"ok": True},
                        "",
                    ),
                ) as audit,
                mock.patch.object(scheduler, "capture_completed_crawl", return_value={}),
                mock.patch.object(scheduler, "read_live_schedule", return_value=[{"row": 2, "frequency": "每天 03:00"}]),
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "register_crawl_run"),
                mock.patch.object(scheduler, "_launch_executive_intelligence_refresh", return_value={"ok": True}),
            ):
                ok = scheduler.resume_pending_run(pending, state)

        self.assertTrue(ok)
        audit.assert_called_once_with(
            "crawl-finance-resume",
            log_path,
            log_sheet_id="sheet-finance",
            agent_run_id="scheduled_crawl-finance-resume",
        )
        rebuild.assert_called_once_with(rows=[2])
        publish.assert_called_once_with(log_path)
        self.assertTrue(any(call.args[0].get("stage") == "financial_completed" for call in write_pending.call_args_list))

    def test_resume_recrawls_missing_financial_report_before_closing_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "resume-finance-recrawl.jsonl"
            log_path.write_text("", encoding="utf-8")
            pending = {
                "stage": "audit_completed",
                "crawl_run_id": "crawl-finance-recrawl",
                "rows": [2],
                "scope": "定时指定行（第2行）",
                "started_at_hkt": "2026-08-28T03:00:00+08:00",
                "stream_log_path": str(log_path),
                "log_sheet_id": "sheet-finance",
                "sync_return_code": 0,
                "curation": {"agent_run_id": "scheduled_crawl-finance-recrawl"},
                "trace_sync": {"ok": True},
            }
            failed_refresh = {
                "quality": {"ok": False, "failures": ["第2行 HKT 未发现可读取的官方财报"]},
                "last_check": [{"row": 2, "company": "HKT", "status": "no_official_report_discovered"}],
                "database_updated": False,
            }
            recovered_refresh = {
                "generated_at_hkt": "2026-08-28T09:30:00+08:00",
                "schedule_policy": "next-day",
                "database_path": "cmhk.data.local_financial_results.json",
                "database_updated": True,
                "database_changed": True,
                "quality": {"ok": True, "failures": []},
                "last_check": [{
                    "row": 2,
                    "company": "HKT",
                    "verification_status": "official_document_extracted",
                    "period": "H1 2026",
                    "publication_date": "2026-07-29",
                    "source_url": "https://www.hkt.com/report.pdf",
                    "core_metric_count": 5,
                    "metrics": [],
                }],
            }
            state: dict[str, object] = {"attempts": {"2": "2026-08-28T03:00:00+08:00"}}
            completed = subprocess.CompletedProcess(
                [scheduler.PYTHON, str(scheduler.ROOT / "crawl.py")],
                0,
                stdout="recovered",
                stderr="",
            )
            with (
                mock.patch(
                    "cmhk.data.local_financial_results.rebuild_local_financial_database",
                    side_effect=[failed_refresh, recovered_refresh],
                ) as rebuild,
                mock.patch.object(scheduler.subprocess, "run", return_value=completed) as run,
                mock.patch.object(scheduler, "_publish_financial_frontend", return_value={
                    "ok": True,
                    "status": "verified",
                    "site_version": "site-finance",
                    "public_url": "https://example.github.io/project/",
                }),
                mock.patch.object(scheduler, "_write_pending_run"),
                mock.patch.object(scheduler, "_clear_pending_run") as clear_pending,
                mock.patch.object(scheduler, "resume_crawl_run"),
                mock.patch.object(scheduler, "append_crawl_run_event") as append_event,
                mock.patch.object(scheduler, "capture_completed_crawl", return_value={}),
                mock.patch.object(scheduler, "read_live_schedule", return_value=[{"row": 2, "frequency": "每天 03:00"}]),
                mock.patch.object(scheduler, "save_state"),
                mock.patch.object(scheduler, "register_crawl_run"),
                mock.patch.object(scheduler, "_launch_executive_intelligence_refresh", return_value={"ok": True}),
            ):
                ok = scheduler.resume_pending_run(pending, state)

        self.assertTrue(ok)
        self.assertEqual(rebuild.call_count, 2)
        self.assertEqual(run.call_args.args[0], [scheduler.PYTHON, str(scheduler.ROOT / "crawl.py")])
        self.assertEqual(run.call_args.kwargs["env"]["CMHK_ROWS"], "2")
        self.assertTrue(any(call.args[1].get("type") == "financial_recovery_recrawl" for call in append_event.call_args_list))
        clear_pending.assert_called_once()

    def test_pending_attempt_does_not_advance_schedule_from_partial_row_output(self) -> None:
        now = scheduler.datetime(2026, 7, 29, 16, 0, tzinfo=scheduler.HKT)
        attempt = now - scheduler.timedelta(hours=1)
        previous_success = scheduler.datetime(2026, 7, 28, 3, 0, tzinfo=scheduler.HKT)
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 3, "frequency": "每天 03:00"}],
            ),
            mock.patch.object(
                scheduler,
                "last_success",
                return_value=previous_success,
            ) as last_success,
        ):
            due, audit = scheduler.due_rows(
                now,
                {"attempts": {"3": attempt.isoformat(timespec="seconds")}},
            )

        self.assertEqual(due, [3])
        self.assertEqual(audit[0]["status"], "due")
        last_success.assert_called_once_with(3, before=attempt)

    def test_completed_ledger_prevents_immediate_repeat_with_stale_result_time(self) -> None:
        now = scheduler.datetime(2026, 7, 30, 11, 7, tzinfo=scheduler.HKT)
        stale_result = scheduler.datetime(2026, 7, 29, 3, 0, tzinfo=scheduler.HKT)
        completed = scheduler.datetime(2026, 7, 30, 11, 6, tzinfo=scheduler.HKT)
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 3, "frequency": "每天 03:00"}],
            ),
            mock.patch.object(
                scheduler,
                "last_success",
                return_value=stale_result,
            ),
        ):
            due, audit = scheduler.due_rows(
                now,
                {
                    "attempts": {},
                    "last_completed": {
                        "3": completed.isoformat(timespec="seconds"),
                    },
                },
            )

        self.assertEqual(due, [])
        self.assertEqual(audit[0]["status"], "waiting")
        self.assertEqual(
            audit[0]["last_success_hkt"],
            completed.isoformat(timespec="seconds"),
        )

    def test_completed_ledger_is_restored_from_successful_run_archive(self) -> None:
        state = {"last_completed": {}, "last_scheduled_for": {}}
        with mock.patch.object(
            scheduler,
            "load_crawl_run_history",
            return_value=[
                {
                    "trigger": "定时爬虫",
                    "run_status": "completed",
                    "scope": "定时指定行（第2行、第3行）",
                    "started_at_hkt": "2026-07-29T03:00:00+08:00",
                    "completed_at_hkt": "2026-07-30T11:06:15+08:00",
                },
                {
                    "trigger": "战略新闻定时爬虫",
                    "run_status": "completed",
                    "scope": "晨间扫描（2026-07-30@09:00）",
                    "completed_at_hkt": "2026-07-30T10:56:36+08:00",
                },
            ],
        ):
            scheduler._restore_completed_rows_from_run_archive(state)

        self.assertEqual(
            state["last_completed"],
            {
                "2": "2026-07-30T11:06:15+08:00",
                "3": "2026-07-30T11:06:15+08:00",
            },
        )
        self.assertEqual(
            state["last_scheduled_for"],
            {
                "2": "2026-07-29T03:00:00+08:00",
                "3": "2026-07-29T03:00:00+08:00",
            },
        )

    def test_cross_day_completion_does_not_consume_next_daily_slot(self) -> None:
        now = scheduler.datetime(2026, 8, 21, 8, 3, tzinfo=scheduler.HKT)
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 3, "frequency": "每天 03:00"}],
            ),
            mock.patch.object(
                scheduler,
                "last_success",
                return_value=scheduler.datetime(2026, 8, 21, 8, 2, tzinfo=scheduler.HKT),
            ),
        ):
            due, audit = scheduler.due_rows(
                now,
                {
                    "attempts": {},
                    "last_completed": {"3": "2026-08-21T08:02:53+08:00"},
                    "last_scheduled_for": {"3": "2026-08-20T03:00:22+08:00"},
                },
            )

        self.assertEqual(due, [3])
        self.assertEqual(audit[0]["status"], "due")
        self.assertEqual(audit[0]["last_success_hkt"], "2026-08-20T03:00:22+08:00")

    def test_mark_rows_completed_preserves_schedule_occurrence_across_midnight(self) -> None:
        state = {"attempts": {"3": "2026-08-20T03:00:22+08:00"}}
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 3, "frequency": "每天 03:00"}],
            ),
            mock.patch.object(scheduler, "save_state"),
        ):
            scheduler._mark_rows_completed(
                state,
                [3],
                scheduled_for_hkt="2026-08-20T03:00:22+08:00",
            )

        self.assertEqual(state["last_scheduled_for"]["3"], "2026-08-20T03:00:22+08:00")
        self.assertNotIn("3", state["attempts"])

    def test_interrupted_pending_resume_bypasses_retry_backoff(self) -> None:
        pending = {
            "stage": "sync_completed",
            "crawl_run_id": "crawl-restart",
            "last_attempt_at_hkt": scheduler.datetime.now(scheduler.HKT).isoformat(
                timespec="seconds"
            ),
        }
        with (
            mock.patch.object(scheduler, "load_state", return_value={}),
            mock.patch.object(scheduler, "_load_pending_run", return_value=pending),
            mock.patch.object(
                scheduler,
                "_pending_run_was_interrupted",
                return_value=True,
            ),
            mock.patch.object(scheduler, "crawl_process_running", return_value=False),
            mock.patch.object(
                scheduler,
                "agent_audit_process_running",
                return_value=False,
            ),
            mock.patch.object(
                scheduler,
                "resume_pending_run",
                return_value=True,
            ) as resume,
        ):
            result = scheduler.legacy_run_cycle()

        self.assertTrue(result["resumed"])
        resume.assert_called_once_with(pending, {})

    def test_agent_control_upgrade_bypasses_retry_backoff_once(self) -> None:
        pending = {
            "stage": "sync_completed",
            "crawl_run_id": "crawl-upgrade",
            "agent_audit_control_version": 1,
            "last_attempt_at_hkt": scheduler.datetime.now(scheduler.HKT).isoformat(
                timespec="seconds"
            ),
        }
        with (
            mock.patch.object(scheduler, "load_state", return_value={}),
            mock.patch.object(scheduler, "_load_pending_run", return_value=pending),
            mock.patch.object(
                scheduler,
                "_pending_run_was_interrupted",
                return_value=False,
            ),
            mock.patch.object(scheduler, "crawl_process_running", return_value=False),
            mock.patch.object(
                scheduler,
                "agent_audit_process_running",
                return_value=False,
            ),
            mock.patch.object(
                scheduler,
                "resume_pending_run",
                return_value=True,
            ) as resume,
        ):
            result = scheduler.legacy_run_cycle()

        self.assertTrue(result["resumed"])
        resume.assert_called_once_with(pending, {})


class FinancialResultScheduleTests(unittest.TestCase):
    def test_weekly_financial_rows_are_overlaid_with_daily_next_day_sla(self) -> None:
        now = scheduler.datetime(2026, 8, 14, 3, 1, tzinfo=scheduler.HKT)
        previous = scheduler.datetime(2026, 8, 13, 3, 0, tzinfo=scheduler.HKT)
        with (
            mock.patch.object(
                scheduler,
                "read_live_schedule",
                return_value=[{"row": 2, "frequency": "每周一 03:00"}],
            ),
            mock.patch.object(scheduler, "last_success", return_value=previous),
        ):
            due, audit = scheduler.due_rows(now, {"attempts": {}})

        self.assertEqual(due, [2])
        self.assertEqual(audit[0]["frequency"], "每天 03:00")
        self.assertEqual(audit[0]["configured_frequency"], "每周一 03:00")
        self.assertEqual(audit[0]["schedule_policy"], "financial_results_next_day_sla")

    def test_0100_source_discovery_runs_once_and_records_handoff(self) -> None:
        now = scheduler.datetime(2026, 8, 25, 1, 1, tzinfo=scheduler.HKT)
        state: dict[str, object] = {}
        with (
            mock.patch.object(scheduler, "crawl_process_running", return_value=False),
            mock.patch.object(scheduler, "agent_audit_process_running", return_value=False),
            mock.patch("four_database_source_discovery.run_discovery", return_value={"ok": True, "run_id": "source-1", "signal_count": 2}),
            mock.patch.object(scheduler, "save_state") as save,
        ):
            result = scheduler.run_due_four_database_source_discovery(now, state)

        self.assertTrue(result["ok"])
        self.assertEqual(state["four_database_source_discovery_date"], "2026-08-25")
        self.assertEqual(state["four_database_source_discovery_run_id"], "source-1")
        save.assert_called_once_with(state)


class SubscriptionDispatchScheduleTests(unittest.TestCase):
    def test_frequency_scheduler_flushes_due_subscription_queue(self) -> None:
        with mock.patch("cmhk.services.subscriptions.SubscriptionService") as service_class:
            service_class.return_value.flush_due.return_value = {
                "processed_count": 2,
                "verified_count": 2,
            }
            result = scheduler.dispatch_subscription_queue()

        self.assertTrue(result["ok"])
        self.assertEqual(result["processed_count"], 2)
        service_class.assert_called_once_with(runtime_root=scheduler.ROOT)
        service_class.return_value.flush_due.assert_called_once_with()

    def test_subscription_dispatch_failure_does_not_raise_into_crawler_cycle(self) -> None:
        with mock.patch("cmhk.services.subscriptions.SubscriptionService", side_effect=RuntimeError("offline")):
            result = scheduler.dispatch_subscription_queue()
        self.assertFalse(result["ok"])
        self.assertIn("offline", result["error"])

    def test_frequency_scheduler_checks_saved_weekly_report_schedule(self) -> None:
        check_time = scheduler.datetime(2026, 8, 30, 9, 30, tzinfo=scheduler.HKT)
        with mock.patch("cmhk.services.subscriptions.SubscriptionService") as service_class:
            service_class.return_value.run_due_weekly_report.return_value = {
                "ok": True,
                "due": True,
                "slot": "2026-08-30@09:30",
            }
            result = scheduler.dispatch_scheduled_weekly_report(dry_run=True, now=check_time)

        self.assertTrue(result["due"])
        service_class.assert_called_once_with(runtime_root=scheduler.ROOT)
        service_class.return_value.run_due_weekly_report.assert_called_once_with(
            now=check_time,
            dry_run=True,
        )

    def test_frequency_scheduler_checks_saved_performance_report_schedule(self) -> None:
        check_time = scheduler.datetime(2026, 8, 30, 9, 30, tzinfo=scheduler.HKT)
        with mock.patch("cmhk.services.subscriptions.SubscriptionService") as service_class:
            service_class.return_value.run_due_performance_report.return_value = {
                "ok": True,
                "due": True,
                "slot": "2026-08-30@09:30",
            }
            result = scheduler.dispatch_scheduled_performance_report(dry_run=True, now=check_time)

        self.assertTrue(result["due"])
        service_class.assert_called_once_with(runtime_root=scheduler.ROOT)
        service_class.return_value.run_due_performance_report.assert_called_once_with(
            now=check_time,
            dry_run=True,
        )


class TaskLogScrollTests(unittest.TestCase):
    def test_running_task_log_scroll_waits_for_layout_and_stays_at_bottom(self) -> None:
        app = (scheduler.ROOT / "web/static/app.js").read_text(encoding="utf-8")
        helper_start = app.index("function scrollTaskLogToBottom")
        helper_end = app.index("function stopCrawlLogPolling", helper_start)
        helper = app[helper_start:helper_end]
        loader_start = app.index("async function loadCrawlRunLog")
        loader_end = app.index("async function loadCrawlRuns", loader_start)
        loader = app[loader_start:loader_end]

        self.assertIn('els.logBox.querySelectorAll(".task-run-process > pre")', helper)
        self.assertIn("processLog.scrollTop = processLog.scrollHeight", helper)
        self.assertIn("els.logBox.scrollTop = els.logBox.scrollHeight", helper)
        self.assertGreaterEqual(helper.count("requestAnimationFrame"), 2)
        running_branch = loader[loader.index('if (task.run_status === "running")'):]
        running_branch = running_branch[:running_branch.index("} else {")]
        self.assertIn("scrollTaskLogToBottom();", running_branch)
        self.assertNotIn("wasNearBottom", running_branch)


class SchedulerHeartbeatTests(unittest.TestCase):
    def test_heartbeat_records_process_and_long_running_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heartbeat.json"
            heartbeat = scheduler.SchedulerHeartbeat(interval_seconds=30)
            with mock.patch.object(scheduler, "HEARTBEAT_PATH", path):
                heartbeat.update(status="running", stage="crawl_running", crawl_run_id="run-1")
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["service"], "frequency-scheduler")
        self.assertEqual(payload["pid"], scheduler.os.getpid())
        self.assertEqual(payload["stage"], "crawl_running")
        self.assertEqual(payload["crawl_run_id"], "run-1")
        self.assertTrue(payload["updated_at_hkt"])


if __name__ == "__main__":
    unittest.main()
