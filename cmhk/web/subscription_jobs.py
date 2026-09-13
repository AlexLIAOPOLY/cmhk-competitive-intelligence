from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from cmhk.services.subscriptions import SubscriptionService

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def push_latest_subscription_content(
        service: SubscriptionService,
        *,
        target_open_id: str = "",
        confirm_bulk: bool = False,
        weekly_report_path: str = "",
        performance_report_path: str = "",
        progress_callback=None,
    ) -> dict:
        """Send each active subscription's latest formal content without a second form."""
        summary = service.list_summary()
        active = [item for item in summary.get("subscribers", []) if item.get("status") == "active"]
        if target_open_id:
            active = [item for item in active if item.get("open_id") == target_open_id]
            if not active:
                raise ValueError("该订阅者未启用，无法人工推送")
        elif not confirm_bulk:
            raise ValueError("一键推送必须在后台完成二次确认")
        if not active:
            raise ValueError("当前没有有效订阅者")

        selected_services = {
            item
            for subscriber in active
            for item in (subscriber.get("services") or [])
            if item in {"weekly", "performance", "news"}
        }
        if not selected_services:
            raise ValueError("接收范围内没有已启用的订阅内容")

        status = app.build_status()
        explicit_weekly_path = bool(weekly_report_path)
        if not weekly_report_path:
            preference_reader = getattr(service, "weekly_report_preference", None)
            if callable(preference_reader):
                weekly_report_path = str((preference_reader() or {}).get("path") or "")
        selected_weekly: dict | None = None
        if weekly_report_path:
            selected_weekly = next(
                (
                    item
                    for item in (status.get("outputs") or [])
                    if isinstance(item, dict)
                    and item.get("path_str") == weekly_report_path
                    and item.get("reportType") == "weekly"
                ),
                None,
            )
            if not selected_weekly:
                if explicit_weekly_path:
                    raise ValueError("选中的周报不在当前报告库中，请刷新后重新选择")
                preference_writer = getattr(service, "update_weekly_report_preference", None)
                if callable(preference_writer):
                    preference_writer("")
                weekly_report_path = ""

        explicit_performance_path = bool(performance_report_path)
        if not performance_report_path:
            preference_reader = getattr(service, "performance_report_preference", None)
            if callable(preference_reader):
                performance_report_path = str((preference_reader() or {}).get("path") or "")
        selected_performance: dict | None = None
        if performance_report_path:
            selected_performance = next(
                (
                    item
                    for item in (status.get("outputs") or [])
                    if isinstance(item, dict)
                    and item.get("path_str") == performance_report_path
                    and item.get("reportType") == "carrier-performance"
                ),
                None,
            )
            if not selected_performance:
                if explicit_performance_path:
                    raise ValueError("选中的业绩摘要不在当前报告库中，请刷新后重新选择")
                preference_writer = getattr(service, "update_performance_report_preference", None)
                if callable(preference_writer):
                    preference_writer("")
                performance_report_path = ""

        content: dict[str, dict[str, object]] = {}
        for service_key, report_type in (("weekly", "weekly"), ("performance", "carrier-performance")):
            if service_key not in selected_services:
                continue
            try:
                if service_key == "weekly" and selected_weekly:
                    output = selected_weekly
                elif service_key == "performance" and selected_performance:
                    output = selected_performance
                else:
                    output = next(
                        (
                            item
                            for item in (status.get("outputs") or [])
                            if isinstance(item, dict)
                            and item.get("reportType") == report_type
                            and not item.get("isEdited")
                        ),
                        None,
                    )
                    if not output:
                        output = next(
                            (
                                item
                                for item in (status.get("outputs") or [])
                                if isinstance(item, dict) and item.get("reportType") == report_type
                            ),
                            None,
                        )
                    if not output:
                        raise FileNotFoundError(report_type)
                content[service_key] = {
                    "mode": "pdf_audio",
                    "path": str(output.get("path_str") or ""),
                    "isEdited": bool(output.get("isEdited")),
                }
            except (FileNotFoundError, ValueError):
                continue
        latest_news: list[dict] = []
        if "news" in selected_services:
            from strategic_briefing import latest_reviewed_news

            # Category filtering must happen before the per-recipient limit, so use
            # the complete verified pool rather than truncating it globally first.
            latest_news = latest_reviewed_news()
        if not content and not latest_news:
            raise ValueError("当前没有可供人工推送的最新正式内容")

        results = []
        total_steps = len(content) + sum(
            1 for subscriber in active
            if latest_news and "news" in (subscriber.get("services") or [])
        )
        completed_steps = 0
        if callable(progress_callback):
            progress_callback(completed_steps, total_steps, "发送内容已准备完成")
        for service_key in ("weekly", "performance"):
            if service_key not in content:
                continue
            item = content[service_key]
            result = service.push(
                service=service_key,
                mode=str(item["mode"]),
                path=str(item.get("path") or ""),
                title=str(item.get("title") or ""),
                body=str(item.get("body") or ""),
                target_open_id=target_open_id,
                confirm_bulk=confirm_bulk,
                allow_user_edited=service_key == "weekly" and bool(item.get("isEdited")),
                manual_report_selection=bool(selected_weekly if service_key == "weekly" else selected_performance),
            )
            results.append(result)
            completed_steps += 1
            if callable(progress_callback):
                progress_callback(
                    completed_steps,
                    total_steps,
                    f"{'周报' if service_key == 'weekly' else '业绩摘要'}已发送并回读",
                )
        if latest_news:
            for subscriber in active:
                if "news" not in (subscriber.get("services") or []):
                    continue
                news_categories = subscriber.get("news_categories")
                news_items = service.select_personal_news(
                    latest_news, open_id=str(subscriber.get("open_id") or ""),
                )
                result = service.push(
                    service="news",
                    mode="text",
                    title=("CMHK个人新闻精选" if subscriber.get("news_personal_skill") else
                           f"CMHK战略新闻｜最新{len(news_items)}条｜{app.news_category_summary(news_categories)}"),
                    body=app.encode_strategic_news_digest(news_items),
                    target_open_id=str(subscriber.get("open_id") or ""),
                )
                results.append(result)
                completed_steps += 1
                if callable(progress_callback):
                    detail = ("战略新闻已进入重试队列" if result.get("queued_count") else
                              "战略新闻发送失败" if result.get("failed_count") else "战略新闻已发送并回读")
                    progress_callback(completed_steps, total_steps, detail)
        return {
            "batch_id": f"manual-latest-{app.uuid.uuid4().hex[:12]}",
            "target_open_id": target_open_id,
            "service_count": len(results),
            "weekly_report_path": str((content.get("weekly") or {}).get("path") or ""),
            "weekly_report_selection": "manual" if selected_weekly else "automatic",
            "performance_report_path": str((content.get("performance") or {}).get("path") or ""),
            "performance_report_selection": "manual" if selected_performance else "automatic",
            "recipient_count": sum(int(item.get("recipient_count") or 0) for item in results),
            "verified_count": sum(int(item.get("verified_count") or 0) for item in results),
            "failed_count": sum(int(item.get("failed_count") or 0) for item in results),
            "queued_count": sum(int(item.get("queued_count") or 0) for item in results),
            "results": results,
        }

    publish(app, push_latest_subscription_content)

    def _read_subscription_push_jobs() -> list[dict]:
        try:
            payload = app.json.loads(app.SUBSCRIPTION_PUSH_JOBS_PATH.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return []
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        return [item for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []

    publish(app, _read_subscription_push_jobs)

    def _write_subscription_push_jobs(jobs: list[dict]) -> None:
        app._task_atomic_json(app.SUBSCRIPTION_PUSH_JOBS_PATH, {"jobs": jobs[:100]})

    publish(app, _write_subscription_push_jobs)

    def _fail_stale_subscription_push_jobs(jobs: list[dict]) -> bool:
        changed = False
        now = app.datetime.now().astimezone().isoformat(timespec="seconds")
        for job in jobs:
            if str(job.get("status") or "") not in {"queued", "running"}:
                continue
            if int(job.get("backend_pid") or 0) == app.os.getpid():
                continue
            job.update({
                "status": "failed",
                "detail": "服务重启，后台推送任务已中断",
                "error": "服务重启后无法继续原后台任务，请核对推送记录后重试",
                "updated_at": now,
            })
            changed = True
        return changed

    publish(app, _fail_stale_subscription_push_jobs)

    def subscription_push_job_snapshot(job_id: str = "") -> dict | None:
        with app.SUBSCRIPTION_PUSH_JOBS_LOCK:
            jobs = app._read_subscription_push_jobs()
            if app._fail_stale_subscription_push_jobs(jobs):
                app._write_subscription_push_jobs(jobs)
        if job_id:
            return next((dict(item) for item in jobs if str(item.get("job_id") or "") == job_id), None)
        return dict(jobs[0]) if jobs else None

    publish(app, subscription_push_job_snapshot)

    def _update_subscription_push_job(job_id: str, **changes) -> dict | None:
        with app.SUBSCRIPTION_PUSH_JOBS_LOCK:
            jobs = app._read_subscription_push_jobs()
            updated = None
            for job in jobs:
                if str(job.get("job_id") or "") != job_id:
                    continue
                job.update(changes)
                job["updated_at"] = app.datetime.now().astimezone().isoformat(timespec="seconds")
                updated = dict(job)
                break
            if updated:
                app._write_subscription_push_jobs(jobs)
            return updated

    publish(app, _update_subscription_push_job)

    def start_subscription_push_job(
        service: SubscriptionService,
        *,
        target_open_id: str = "",
        confirm_bulk: bool = False,
        weekly_report_path: str = "",
        performance_report_path: str = "",
    ) -> dict:
        """Queue a manual push so Feishu sends/readback do not hold the browser request open."""
        if target_open_id and not app.re.fullmatch(r"ou_[A-Za-z0-9_-]+", target_open_id):
            raise ValueError("手动推送接收人格式无效")
        if not target_open_id and not confirm_bulk:
            raise ValueError("一键推送必须在后台完成二次确认")
        now = app.datetime.now().astimezone().isoformat(timespec="seconds")
        job_id = "subscription-push:" + app.uuid.uuid4().hex[:16]
        job = {
            "job_id": job_id,
            "status": "queued",
            "target_open_id": target_open_id,
            "completed_steps": 0,
            "total_steps": 0,
            "queued_count": 1,
            "detail": "后台已接收推送任务",
            "error": "",
            "result": {},
            "backend_pid": app.os.getpid(),
            "created_at": now,
            "updated_at": now,
        }
        with app.SUBSCRIPTION_PUSH_JOBS_LOCK:
            jobs = app._read_subscription_push_jobs()
            if app._fail_stale_subscription_push_jobs(jobs):
                app._write_subscription_push_jobs(jobs)
            active_job = next(
                (item for item in jobs if str(item.get("status") or "") in {"queued", "running"}),
                None,
            )
            if active_job:
                raise ValueError("已有人工推送正在后台发送，请等待当前任务完成")
            jobs.insert(0, job)
            app._write_subscription_push_jobs(jobs)

        def progress(completed_steps: int, total_steps: int, detail: str) -> None:
            app._update_subscription_push_job(
                job_id,
                status="running",
                completed_steps=max(0, int(completed_steps)),
                total_steps=max(0, int(total_steps)),
                detail=str(detail or "正在发送并回读"),
            )

        def worker() -> None:
            app._update_subscription_push_job(job_id, status="running", detail="正在准备最新推送内容")
            try:
                result = app.push_latest_subscription_content(
                    service,
                    target_open_id=target_open_id,
                    confirm_bulk=confirm_bulk,
                    weekly_report_path=weekly_report_path,
                    performance_report_path=performance_report_path,
                    progress_callback=progress,
                )
                failed_count = int(result.get("failed_count") or 0)
                queued_count = int(result.get("queued_count") or 0)
                app._update_subscription_push_job(
                    job_id,
                    status="completed",
                    detail=(f"已确认 {int(result.get('verified_count') or 0)} 项，{queued_count} 项等待重试，{failed_count} 项失败"
                            if queued_count or failed_count else "推送完成"),
                    error="",
                    result=result,
                )
            except Exception as exc:
                app.logging.exception("订阅人工推送后台任务失败")
                app._update_subscription_push_job(
                    job_id,
                    status="failed",
                    detail="推送失败",
                    error=str(exc)[:900],
                )

        app.threading.Thread(
            target=worker,
            name="subscription-push-" + job_id.rsplit(":", 1)[-1],
            daemon=True,
        ).start()
        return dict(job)

    publish(app, start_subscription_push_job)

