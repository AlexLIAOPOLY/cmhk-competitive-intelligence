from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from pathlib import Path

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def current_crawl_result_files() -> list[Path]:
        """Return only result files listed by the latest crawl coverage report."""
        coverage_path = app.ROOT / "coverage_report.tsv"
        if coverage_path.exists():
            try:
                with coverage_path.open(encoding="utf-8", newline="") as fh:
                    rows = list(app.csv.DictReader(fh, delimiter="\t"))
                current: list[Path] = []
                results_root = app.RESULTS_DIR.resolve()
                for row in rows:
                    raw_path = str(row.get("result_file") or "").strip()
                    if not raw_path:
                        continue
                    candidate = (app.ROOT / raw_path).resolve()
                    if candidate.parent == results_root and candidate.name.startswith("row_") and candidate.exists():
                        current.append(candidate)
                if current:
                    return current
            except (OSError, app.csv.Error):
                pass
        return sorted(app.RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1]))

    publish(app, current_crawl_result_files)

    def build_status() -> dict:
        from strategic_briefing import SCAN_TIMES

        result_files = app.current_crawl_result_files()
        running_tasks = [
            task
            for task in app.load_unified_task_index(limit=1000)
            if str(task.get("run_status") or "") == "running"
        ]

        outputs = [app.file_info(path) for path in app.current_report_files()]

        ok_count = 0
        partial_count = 0
        quality_rejected_count = 0
        operational_failed_count = 0
        block_counts: dict[str, int] = {}
        source_type_counts: dict[str, int] = {}
        jurisdiction_counts: dict[str, int] = {}
        method_counts: dict[str, int] = {}
        entity_counts: dict[str, int] = {}
        field_total = 0
        missing_total = 0
        raw_total = 0

        valid_results_count = 0
        for path in result_files:
            valid_results_count += 1
            try:
                data = app.json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            row_status = str(data.get("status") or "")
            if row_status == "ok":
                ok_count += 1
            elif row_status == "partial":
                partial_count += 1
            elif row_status == "quality_rejected":
                quality_rejected_count += 1
            else:
                operational_failed_count += 1
            block = str(data.get("need") or data.get("block") or "未分类")
            if "香港" in block:
                block = "香港本地"
            elif any(token in block for token in ["国际", "全球", "欧盟", "国家"]):
                block = "国际监管"
            elif any(token in block for token in ["收入", "ARPU", "EBITDA", "利润", "客户"]):
                block = "经营指标"
            elif any(token in block for token in ["套餐", "资费", "产品", "服务"]):
                block = "产品资费"
            else:
                block = "运营动态"
            block_counts[block] = block_counts.get(block, 0) + 1
            selected_fields = data.get("selected_fields") or []
            missing_fields = data.get("missing_fields") or []
            if isinstance(selected_fields, list):
                field_total += len(selected_fields)
            if isinstance(missing_fields, list):
                missing_total += len(missing_fields)
            for entity in data.get("entities") or []:
                name = str(entity).strip()
                if name:
                    entity_counts[name] = entity_counts.get(name, 0) + 1
            for record in data.get("raw_records") or []:
                if not isinstance(record, dict):
                    continue
                raw_total += 1
                source_type = str(record.get("source_type") or "unknown")
                source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
                jurisdiction = str(record.get("jurisdiction") or "unknown")
                jurisdiction_counts[jurisdiction] = jurisdiction_counts.get(jurisdiction, 0) + 1
                method = str(record.get("method") or "unknown")
                method_counts[method] = method_counts.get(method, 0) + 1

        # Calculate latest timestamp from crawler output rather than HTML reports
        latest_crawl_time = max((path.stat().st_mtime for path in result_files if path.exists()), default=None)
        settings = app.build_settings_payload()
        latest_news_funnel = app.build_latest_news_funnel()
        today_news_rounds = app.build_today_news_rounds()

        # Sort outputs by mtime descending
        outputs.sort(key=lambda x: x["mtime"], reverse=True)

        return {
            "template": {
                "path": str(app.TEMPLATE_PATH),
                "exists": app.TEMPLATE_PATH.exists(),
                "mtimeText": app.time.strftime("%Y-%m-%d %H:%M:%S", app.time.localtime(app.TEMPLATE_PATH.stat().st_mtime))
                if app.TEMPLATE_PATH.exists()
                else "",
            },
            "results": {
                "count": valid_results_count,
                "ok": ok_count,
                "partial": partial_count,
            },
            "visuals": {
                "crawl": app.build_crawl_result_visuals(),
                "quality": {
                    "ok": ok_count,
                    "partial": partial_count,
                    "failed": operational_failed_count,
                    "operationalFailed": operational_failed_count,
                    "qualityRejected": quality_rejected_count,
                    "nonPromoted": quality_rejected_count + operational_failed_count,
                    "fieldTotal": field_total,
                    "missingFields": missing_total,
                    "rawSources": raw_total,
                },
                "blocks": sorted(
                    [{"label": key, "value": value} for key, value in block_counts.items()],
                    key=lambda item: item["value"],
                    reverse=True,
                ),
                "sourceTypes": sorted(
                    [{"label": key, "value": value} for key, value in source_type_counts.items()],
                    key=lambda item: item["value"],
                    reverse=True,
                )[:6],
                "jurisdictions": sorted(
                    [{"label": key, "value": value} for key, value in jurisdiction_counts.items()],
                    key=lambda item: item["value"],
                    reverse=True,
                )[:6],
                "methods": sorted(
                    [{"label": key, "value": value} for key, value in method_counts.items()],
                    key=lambda item: item["value"],
                    reverse=True,
                )[:6],
                "rejection": app.build_curation_rejection_visuals(),
                "newsFunnel": latest_news_funnel,
                "todayNewsRounds": today_news_rounds,
                "newsScanTimes": [
                    {"label": "上午" if scan_time.hour < 12 else "下午", "time": scan_time.strftime("%H:%M")}
                    for scan_time in SCAN_TIMES
                ],
                "entities": sorted(
                    [{"label": key, "value": value} for key, value in entity_counts.items()],
                    key=lambda item: item["value"],
                    reverse=True,
                )[:8],
                "outputs": [
                    {
                        "name": item["name"],
                        "mtime": item["mtime"],
                        "mtimeText": item["mtimeText"],
                        "audio": bool(item.get("audio", {}).get("exists")),
                    }
                    for item in outputs[:8]
                ],
            },
            "outputs": outputs,
            "settings": settings["summary"],
            "ai": app.load_ai_config(include_key=False),
            "tasks": {
                "runningCount": len(running_tasks),
                "hasRunning": bool(running_tasks),
            },
            "latestOutputText": app.time.strftime("%Y-%m-%d %H:%M:%S", app.time.localtime(latest_crawl_time)) if latest_crawl_time else "未生成",
        }

    publish(app, build_status)

    def build_scheduler_overview(*, force: bool = False) -> dict[str, object]:
        """Return a read-only, cached view of every effective crawl schedule and its downstream jobs."""
        now_monotonic = app.time.monotonic()
        with app.SCHEDULER_OVERVIEW_LOCK:
            cached_at = float(app.SCHEDULER_OVERVIEW_CACHE.get("cached_at_monotonic") or 0)
            cached_payload = app.SCHEDULER_OVERVIEW_CACHE.get("payload")
            if not force and isinstance(cached_payload, dict) and now_monotonic - cached_at < app.SCHEDULER_OVERVIEW_CACHE_SECONDS:
                return dict(cached_payload)

            import scheduler

            now = app.datetime.now(scheduler.HKT)
            state = scheduler.load_state()
            _due, rows = scheduler.due_rows(now, state)
            active_rows = [item for item in rows if item.get("status") != "disabled"]
            frequency_counts = {"daily": 0, "weekly": 0, "monthly": 0, "other": 0}
            for item in active_rows:
                frequency = str(item.get("frequency") or "")
                key = "daily" if frequency.startswith("每天") else "weekly" if frequency.startswith("每周") else "monthly" if frequency.startswith("每月") else "other"
                frequency_counts[key] += 1

            row_numbers = {int(item.get("row") or 0) for item in active_rows}
            source_groups = [
                {"id": "local", "label": "香港本地竞对", "count": len(row_numbers.intersection(range(2, 19)))},
                {"id": "benchmark", "label": "全球标杆运营商", "count": len(row_numbers.intersection(range(19, 22)))},
                {"id": "hong-kong-news", "label": "香港重点资讯", "count": len(row_numbers.intersection(range(22, 26)))},
                {"id": "international", "label": "国际政策与行业", "count": len(row_numbers.intersection(range(26, 35)))},
            ]

            run_history = app.load_crawl_run_history(task_kind="")
            latest_main = next((item for item in run_history if str(item.get("trigger") or "") == "定时爬虫"), {})
            latest_news = next((item for item in run_history if str(item.get("task_kind") or "") == "strategic-news"), {})
            latest_intelligence = next((item for item in run_history if str(item.get("task_kind") or "") == "executive-intelligence-refresh"), {})
            try:
                from strategic_briefing import public_snapshot as strategic_public_snapshot

                strategic_monitor = dict(strategic_public_snapshot().get("monitor") or {})
            except Exception as exc:
                app.logging.warning("strategic monitor snapshot unavailable: %s", exc)
                strategic_monitor = {
                    "enabled": False,
                    "status": "unavailable",
                    "last_error": str(exc)[:240],
                }
            latest_news_summary = (
                latest_news.get("operational_summary")
                if isinstance(latest_news.get("operational_summary"), dict)
                else {}
            )
            latest_news_slot = str(latest_news_summary.get("slot") or "").strip()
            if not latest_news_slot:
                latest_news_slot_match = app.re.search(
                    r"(\d{4}-\d{2}-\d{2}@\d{2}:\d{2})",
                    str(latest_news.get("scope") or ""),
                )
                latest_news_slot = latest_news_slot_match.group(1) if latest_news_slot_match else ""
            starting_slot = dict(strategic_monitor.get("latest_scan_slot") or {})
            starting_slot_key = str(starting_slot.get("slot") or "").strip()
            starting_slot_has_registered_run = bool(
                starting_slot_key
                and latest_news_slot
                and starting_slot_key == latest_news_slot
            )
            if str(latest_news.get("run_status") or "") == "running":
                strategic_monitor.update(
                    {
                        "status": "running",
                        "active_task_kind": "strategic-news",
                        "active_task_id": str(latest_news.get("crawl_run_id") or ""),
                        "active_phase": str(latest_news.get("phase") or "执行中"),
                        "active_progress": str(latest_news.get("progress_detail") or "任务正在执行。"),
                        "active_heartbeat_at": str(latest_news.get("heartbeat_at_hkt") or ""),
                        "active_started_at": str(latest_news.get("started_at_hkt") or ""),
                        "task_visible": True,
                    }
                )
            elif (
                str(starting_slot.get("status") or "") == "starting"
                and not starting_slot_has_registered_run
            ):
                strategic_monitor.update(
                    {
                        "status": "starting",
                        "active_task_kind": "strategic-news",
                        "active_task_id": f"slot:{starting_slot.get('slot') or ''}",
                        "active_phase": "调度已交接",
                        "active_progress": "调度器已开始启动战略爬虫，等待任务登记。",
                        "active_heartbeat_at": str(starting_slot.get("at") or ""),
                        "active_started_at": str(starting_slot.get("scheduled_for") or starting_slot.get("at") or ""),
                        "task_visible": True,
                    }
                )
            else:
                strategic_monitor.update(
                    {
                        "active_task_kind": "",
                        "active_task_id": "",
                        "active_phase": "",
                        "active_progress": "",
                        "active_heartbeat_at": "",
                        "active_started_at": "",
                        "task_visible": False,
                    }
                )
            next_runs = sorted(
                {str(item.get("next_run_hkt") or "") for item in active_rows if item.get("next_run_hkt")}
            )
            payload: dict[str, object] = {
                "ok": True,
                "checked_at_hkt": now.isoformat(timespec="seconds"),
                "timezone": "Asia/Hong_Kong",
                "configured_rows": len(active_rows),
                "frequency_counts": frequency_counts,
                "source_groups": source_groups,
                "next_runs": next_runs,
                "strategic_monitor": strategic_monitor,
                "latest": {
                    "main_crawl": latest_main,
                    "strategic_news": latest_news,
                    "four_database_refresh": latest_intelligence,
                },
                "pipeline": {
                    "main_crawl": ["页面抓取", "Agent证据审核", "飞书归档", "页面变化线索"],
                    "four_databases": ["local", "international", "cloud", "macro"],
                    "four_database_stages": ["数据库刷新", "质量门禁", "17项AI洞察", "主页与公开页发布"],
                    "strategic_news": ["线索补缺", "确定性门禁", "AI语义审核", "历史语义去重", "写入与推送"],
                },
            }
            app.SCHEDULER_OVERVIEW_CACHE.clear()
            app.SCHEDULER_OVERVIEW_CACHE.update({"cached_at_monotonic": now_monotonic, "payload": payload})
            return dict(payload)

    publish(app, build_scheduler_overview)
