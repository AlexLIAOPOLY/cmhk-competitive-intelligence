from __future__ import annotations



def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    class WriteRoutes:
        def do_POST(self):
            parsed = app.urlparse(self.path)
            if app.AUTH.handle(self, "POST", parsed):
                return
            if parsed.path.startswith("/api/") and not app.AUTH.authorize_api(self, parsed.path, "POST"):
                return
            actor = app.AUTH.current_actor(self) or {}
            with app.request_context(str(actor.get("id") or "anonymous")):
                return self._authorized_post(parsed)

        def _authorized_post(self, parsed):
            if parsed.path == "/api/project-incidents/resolve":
                actor = app.AUTH.current_actor(self)
                if not actor:
                    app.json_response(self, {"ok": False, "error": "登录状态已失效，请重新登录"}, 401)
                    return
                incident_id = ""
                try:
                    payload = app.read_request_json(self)
                    incident_id = str(payload.get("incidentId") or "").strip()
                    result = app.CardActionHandler(runtime_root=app.ROOT).mark_incident_handled_from_web(
                        incident_id,
                        str(actor.get("feishuOpenId") or ""),
                        str(actor.get("feishuUnionId") or ""),
                    )
                    try:
                        app.record_ui_runtime_incident(
                            "fault-resolution",
                            status="resolved",
                            context={"incident_id": incident_id},
                        )
                    except Exception:
                        app.logging.exception("failed to resolve fault-resolution runtime incident")
                    app.AUTH.record_operation(
                        actor=actor,
                        action="fault.mark_handled",
                        target=incident_id,
                        origin=app.AUTH.operation_origin(self),
                        details={
                            "handler_name": result.get("operator_name"),
                            "feishu_sync": result.get("feishu_sync"),
                            "sheet_row": result.get("sheet_row"),
                        },
                    )
                    records = app.load_project_incident_index(500)
                    incident = next((item for item in records if item.get("incident_id") == incident_id), None)
                    app.json_response(self, {"ok": True, "result": result, "incident": incident})
                except ValueError as exc:
                    app.AUTH.record_operation(
                        actor=actor,
                        action="fault.mark_handled",
                        target=incident_id,
                        result="failure",
                        origin=app.AUTH.operation_origin(self),
                        details={"error": str(exc)[:240]},
                    )
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                except RuntimeError as exc:
                    app.AUTH.record_operation(
                        actor=actor,
                        action="fault.mark_handled",
                        target=incident_id,
                        result="failure",
                        origin=app.AUTH.operation_origin(self),
                        details={"error": str(exc)[:240]},
                    )
                    try:
                        app.record_ui_runtime_incident(
                            "fault-resolution",
                            status="open",
                            error=f"{type(exc).__name__}: {exc}",
                            context={"incident_id": incident_id, "http_status": 409},
                        )
                    except Exception:
                        app.logging.exception("failed to persist fault-resolution runtime incident")
                    app.json_response(self, {"ok": False, "error": str(exc)}, 409)
                except Exception as exc:
                    app.AUTH.record_operation(
                        actor=actor,
                        action="fault.mark_handled",
                        target=incident_id,
                        result="failure",
                        origin=app.AUTH.operation_origin(self),
                        details={"error": "飞书同步失败"},
                    )
                    try:
                        app.record_ui_runtime_incident(
                            "fault-resolution",
                            status="open",
                            error=f"{type(exc).__name__}: {exc}",
                            context={"incident_id": incident_id, "http_status": 502},
                        )
                    except Exception:
                        app.logging.exception("failed to persist fault-resolution runtime incident")
                    app.json_response(self, {"ok": False, "error": f"飞书同步失败：{exc}"}, 502)
                return
            if parsed.path == "/api/competitor-intelligence-map/insights-stream":
                try:
                    payload = app.read_request_json(self)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Content-Encoding", "identity")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    from cmhk.intelligence.market_news_insights import generate_market_news_insights

                    result = generate_market_news_insights(
                        app.ROOT,
                        force=bool(payload.get("force")),
                        requested_revision=str(payload.get("evidenceHash") or ""),
                        generation_nonce=str(payload.get("generationNonce") or "")[:160],
                        stream_callback=lambda event: app.write_interactive_sse(self, event),
                    )
                    app.write_sse(self, {"type": "done", **result})
                except ValueError as exc:
                    app.write_sse(self, {"type": "error", "status": 409, "error": str(exc)})
                except app.AIRequestCancelled:
                    pass
                except Exception as exc:
                    app.logging.error("UI_RUNTIME_INCIDENT market-news-ai-insight: %s: %s", type(exc).__name__, exc)
                    app.write_sse(self, {"type": "error", "status": getattr(exc, "status_code", 503),
                                     "retryable": isinstance(exc, app.AIQueueBusy), "error": str(exc)})
                self.close_connection = True
                return
            if parsed.path == "/api/competitor-insight-stream":
                try:
                    payload = app.read_request_json(self)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Content-Encoding", "identity")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    result = app.generate_competitor_insight(payload, stream_callback=lambda event: app.write_interactive_sse(self, event))
                    app.record_ui_runtime_incident(
                        "competitor-ai-insight",
                        status="resolved",
                        context={"request_id": payload.get("requestId") or "", "metric": (payload.get("metric") or {}).get("key") or ""},
                    )
                    app.write_sse(self, {"type": "done", "ok": True, **result})
                except app.AIQueueBusy as exc:
                    app.write_sse(self, {"type": "error", "ok": False, "status": 429,
                                     "retryable": True, "retryAfter": exc.retry_after, "error": str(exc)})
                except Exception as exc:
                    if isinstance(exc, (app.AIRequestCancelled, BrokenPipeError, ConnectionResetError)):
                        self.close_connection = True
                        return
                    app.logging.error("UI_RUNTIME_INCIDENT competitor-ai-insight: %s: %s", type(exc).__name__, exc)
                    app.record_ui_runtime_incident(
                        "competitor-ai-insight",
                        status="open",
                        error=f"{type(exc).__name__}: {exc}",
                        context={"request_id": payload.get("requestId") or "", "metric": (payload.get("metric") or {}).get("key") or ""},
                    )
                    try:
                        app.write_sse(self, {"type": "error", "ok": False, "error": str(exc)})
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                self.close_connection = True
                return
            if parsed.path == "/api/competitor-insight":
                try:
                    payload = app.read_request_json(self)
                    result = app.generate_competitor_insight(payload)
                    app.record_ui_runtime_incident(
                        "competitor-ai-insight",
                        status="resolved",
                        context={"request_id": payload.get("requestId") or "", "metric": (payload.get("metric") or {}).get("key") or ""},
                    )
                    app.json_response(self, {"ok": True, **result})
                except ValueError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                except Exception as exc:
                    app.logging.error("UI_RUNTIME_INCIDENT competitor-ai-insight: %s: %s", type(exc).__name__, exc)
                    app.record_ui_runtime_incident(
                        "competitor-ai-insight",
                        status="open",
                        error=f"{type(exc).__name__}: {exc}",
                        context={"request_id": payload.get("requestId") or "", "metric": (payload.get("metric") or {}).get("key") or ""},
                    )
                    app.json_response(self, {"ok": False, "error": str(exc)}, 503)
                return
            if parsed.path == "/api/subscriptions":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "订阅管理后台仅允许本机访问"}, 403)
                    return
                actor = app.AUTH.current_actor(self)
                payload: dict = {}
                action = ""
                operation_completed = False
                try:
                    payload = app.read_request_json(self)
                    action = str(payload.get("action") or "")
                    service = app.subscription_service()
                    if action == "publish":
                        result = service.publish_entry_card(
                            target_id=str(payload.get("targetId") or ""),
                            target_type=str(payload.get("targetType") or "chat"),
                        )
                    elif action == "update":
                        services = payload.get("services") if isinstance(payload.get("services"), list) else []
                        result = service.update_subscriber(
                            str(payload.get("openId") or ""),
                            services=services,
                            status=str(payload.get("status") or "active"),
                            frequency=str(payload.get("newsFrequency") or payload.get("frequency") or "once_daily"),
                            report_mode=str(payload.get("reportMode") or "pdf"),
                            news_item_limit=int(payload.get("newsItemLimit") or 10),
                            news_categories=payload.get("newsCategories"),
                            news_region_preference=payload.get("newsRegionPreference"),
                            news_delivery_times=payload.get("newsDeliveryTimes"),
                        )
                    elif action == "resetSubscriber":
                        result = service.reset_subscriber(str(payload.get("openId") or ""))
                    elif action == "updateReportSchedule":
                        result = service.update_report_schedule(
                            days=payload.get("days"),
                            time_hm=payload.get("time"),
                            enabled=payload.get("enabled") is True,
                        )
                    elif action == "updatePerformanceSchedule":
                        result = service.update_performance_schedule(
                            days=payload.get("days"),
                            time_hm=payload.get("time"),
                            enabled=payload.get("enabled") is True,
                        )
                    elif action == "updateNewsSchedule":
                        result = service.update_news_schedule(
                            enabled=payload.get("enabled") is True,
                        )
                    elif action == "setWeeklyReportPreference":
                        result = app.update_weekly_report_preference(
                            service,
                            str(payload.get("weeklyReportPath") or ""),
                        )
                    elif action == "setPerformanceReportPreference":
                        result = app.update_performance_report_preference(
                            service,
                            str(payload.get("performanceReportPath") or ""),
                        )
                    elif action == "refreshDirectory":
                        result = service.refresh_people_directory()
                    elif action == "searchPeople":
                        result = {
                            "query": str(payload.get("query") or ""),
                            "people": service.search_people_directory(str(payload.get("query") or "")),
                        }
                    elif action == "searchDirectory":
                        query = str(payload.get("query") or "")
                        result = {
                            "query": query,
                            "people": service.search_people_directory(query),
                            "chats": service.search_chat_directory(query),
                        }
                    elif action == "addCandidates":
                        ids = payload.get("directoryOpenIds") if isinstance(payload.get("directoryOpenIds"), list) else []
                        result = service.add_directory_candidates(ids)
                    elif action == "invite":
                        ids = payload.get("callbackOpenIds") if isinstance(payload.get("callbackOpenIds"), list) else []
                        result = service.invite_users(
                            ids,
                            confirm_invite=payload.get("confirmInvite") is True,
                            invited_by="local_admin",
                        )
                    elif action == "inviteTarget":
                        result = service.invite_target(
                            str(payload.get("targetId") or ""),
                            target_type=str(payload.get("targetType") or ""),
                            confirm_invite=payload.get("confirmInvite") is True,
                        )
                    elif action == "pushLatest":
                        result = app.push_latest_subscription_content(
                            service,
                            target_open_id=str(payload.get("targetOpenId") or ""),
                            confirm_bulk=payload.get("confirmBulk") is True,
                            weekly_report_path=str(payload.get("weeklyReportPath") or ""),
                            performance_report_path=str(payload.get("performanceReportPath") or ""),
                        )
                    elif action == "pushLatestAsync":
                        result = app.start_subscription_push_job(
                            service,
                            target_open_id=str(payload.get("targetOpenId") or ""),
                            confirm_bulk=payload.get("confirmBulk") is True,
                            weekly_report_path=str(payload.get("weeklyReportPath") or ""),
                            performance_report_path=str(payload.get("performanceReportPath") or ""),
                        )
                    elif action == "push":
                        result = service.push(
                            service=str(payload.get("service") or ""),
                            mode=str(payload.get("mode") or "text"),
                            path=str(payload.get("path") or ""),
                            title=str(payload.get("title") or ""),
                            body=str(payload.get("body") or ""),
                            test_open_id=str(payload.get("testOpenId") or ""),
                            target_open_id=str(payload.get("targetOpenId") or ""),
                            confirm_bulk=payload.get("confirmBulk") is True,
                        )
                    else:
                        raise ValueError("未知订阅管理动作")
                    operation_completed = True
                    app.record_subscription_operation_footprint(
                        actor=actor,
                        action=action,
                        payload=payload,
                        operation_result=result,
                        origin=app.AUTH.operation_origin(self),
                    )
                    subscriptions = service.list_summary()
                    app.json_response(self, {"ok": True, "result": result, "subscriptions": subscriptions})
                except ValueError as exc:
                    if not operation_completed:
                        app.record_subscription_operation_footprint(
                            actor=actor,
                            action=action,
                            payload=payload,
                            audit_result="failure",
                            error=str(exc),
                            origin=app.AUTH.operation_origin(self),
                        )
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                except Exception as exc:
                    if not operation_completed:
                        app.record_subscription_operation_footprint(
                            actor=actor,
                            action=action,
                            payload=payload,
                            audit_result="failure",
                            error=str(exc),
                            origin=app.AUTH.operation_origin(self),
                        )
                    app.json_response(self, {"ok": False, "error": str(exc)}, 500)
                return
            if parsed.path == "/api/executive-intelligence/regenerate-discovery":
                if not app.INTELLIGENCE_INSIGHT_REFRESH_LOCK.acquire(timeout=60):
                    app.json_response(self, {"ok": False, "error": "数据解读服务仍在处理上一项任务，请稍后重试。"}, 409)
                    return
                try:
                    from executive_intelligence_pipeline import regenerate_model_discovery

                    payload = app.read_request_json(self)
                    index = int(payload.get("index"))
                    source_domain = str(payload.get("from") or "").strip()
                    target_domain = str(payload.get("to") or "").strip()
                    if not source_domain or not target_domain:
                        raise ValueError("from和to不能为空")
                    app.json_response(self, regenerate_model_discovery(index, source_domain, target_domain))
                except (TypeError, ValueError) as exc:
                    app.json_response(self, {"ok": False, "error": app.public_intelligence_error_message(exc)}, 400)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": app.public_intelligence_error_message(exc)}, 500)
                finally:
                    app.INTELLIGENCE_INSIGHT_REFRESH_LOCK.release()
                return
            if parsed.path == "/api/executive-intelligence/regenerate-insight":
                if not app.INTELLIGENCE_INSIGHT_REFRESH_LOCK.acquire(timeout=60):
                    app.json_response(self, {"ok": False, "error": "数据解读服务仍在处理上一项任务，请稍后重试。"}, 409)
                    return
                try:
                    from executive_intelligence_pipeline import regenerate_model_focus_summary

                    payload = app.read_request_json(self)
                    domain_id = str(payload.get("domain") or "").strip()
                    focus_id = str(payload.get("focus") or "").strip()
                    if not domain_id or not focus_id:
                        raise ValueError("domain和focus不能为空")
                    if payload.get("stream"):
                        app.start_ndjson_response(self)
                        try:
                            result = regenerate_model_focus_summary(
                                domain_id,
                                focus_id,
                                progress=lambda message: app.write_ndjson_event(
                                    self, {"type": "status", "message": message}
                                ),
                            )
                            for chunk in app.re.findall(r"[^，。；！？]+[，。；！？]?", result.get("analysis") or ""):
                                app.write_ndjson_event(self, {"type": "delta", "text": chunk})
                            app.write_ndjson_event(self, {
                                "type": "complete",
                                **{key: value for key, value in result.items() if key != "analysis"},
                            })
                        except Exception as exc:
                            app.write_ndjson_event(self, {
                                "type": "error",
                                "message": app.public_intelligence_error_message(exc),
                            })
                        self.close_connection = True
                    else:
                        app.json_response(self, regenerate_model_focus_summary(domain_id, focus_id))
                except ValueError as exc:
                    app.json_response(self, {"ok": False, "error": app.public_intelligence_error_message(exc)}, 400)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": app.public_intelligence_error_message(exc)}, 500)
                finally:
                    app.INTELLIGENCE_INSIGHT_REFRESH_LOCK.release()
                return
            if parsed.path == "/api/news-review-sheet/update":
                actor = app.AUTH.current_actor(self)
                changes = []
                try:
                    from cmhk.intelligence.news_review_sheet import update_review_sheet_cells

                    payload = app.read_request_json(self)
                    changes = payload.get("changes")
                    if not isinstance(changes, list):
                        raise ValueError("changes 必须是数组")
                    has_decision_change = any(
                        isinstance(item, dict)
                        and int(item.get("columnIndex", -1))
                        in app.NEWS_REVIEW_DECISION_COLUMNS
                        for item in changes
                    )
                    mention_identity = (
                        app.resolve_news_review_mention_identity(actor)
                        if has_decision_change
                        else {}
                    )
                    screener = None
                    if (
                        mention_identity.get("resolved") is True
                        and str(mention_identity.get("name") or "").strip()
                        and (
                            mention_identity.get("isSystem") is True
                            or str(mention_identity.get("mentionToken") or "").strip()
                        )
                    ):
                        screener = {
                            "name": str(mention_identity.get("name") or ""),
                            "mentionToken": str(
                                mention_identity.get("mentionToken") or ""
                            ),
                            "notify": False,
                        }
                    result = update_review_sheet_cells(
                        changes,
                        screener=screener,
                    )
                    if has_decision_change and isinstance(result.get("screener"), dict):
                        result["screener"].update(
                            {
                                "identityResolution": str(
                                    mention_identity.get("resolutionSource") or "pending"
                                ),
                                "fullyReconciled": bool(screener)
                                and result["screener"].get("readbackVerified") is True,
                            }
                        )
                    app.sync_news_review_sheet_audit(result, ignored_changes=changes)
                    decision_rows = sorted({
                        int(item.get("rowNumber") or 0)
                        for item in changes
                        if isinstance(item, dict)
                        and int(item.get("columnIndex", -1))
                        in app.NEWS_REVIEW_DECISION_COLUMNS
                        and str(item.get("before") or "") != str(item.get("value") or "")
                    })
                    if not int(result.get("changedCount") or 0):
                        decision_rows = []
                    result_rows = [
                        row for row in (result.get("rows") or []) if isinstance(row, dict)
                    ]
                    rows_by_record_id = {
                        str(row.get("recordId") or ""): row
                        for row in result_rows
                        if str(row.get("recordId") or "")
                    }
                    rows_by_number = {
                        int(row.get("rowNumber") or 0): row
                        for row in result_rows
                        if int(row.get("rowNumber") or 0) >= 2
                    }
                    headers = (
                        result.get("headers")
                        if isinstance(result.get("headers"), list)
                        else []
                    )
                    candidate_review_changes = [
                        item
                        for item in changes[:200]
                        if isinstance(item, dict)
                        and int(item.get("columnIndex", -1))
                        in app.NEWS_REVIEW_DECISION_COLUMNS
                        and str(item.get("before") or "")
                        != str(item.get("value") or "")
                    ]
                    # update_review_sheet_cells may report an already-applied
                    # value from a stale browser. In an ambiguous mixed batch,
                    # omit the cells from human-learning evidence rather than
                    # falsely attributing a no-op to the current person.
                    auditable_changes = (
                        candidate_review_changes
                        if int(result.get("changedCount") or 0)
                        == len(candidate_review_changes)
                        else []
                    )
                    audited_cells = []
                    for item in auditable_changes:
                        if not isinstance(item, dict):
                            continue
                        row_number = int(item.get("rowNumber") or 0)
                        column_index = int(item.get("columnIndex", -1))
                        record_id = str(item.get("recordId") or "")
                        result_row = rows_by_record_id.get(record_id) or rows_by_number.get(
                            row_number
                        ) or {}
                        values = (
                            result_row.get("values")
                            if isinstance(result_row.get("values"), list)
                            else []
                        )
                        audited_cells.append(
                            {
                                "row": row_number,
                                "column": column_index,
                                "field": str(
                                    headers[column_index]
                                    if 0 <= column_index < len(headers)
                                    else ""
                                ),
                                "record_id": record_id
                                or str(result_row.get("recordId") or ""),
                                "news_id": record_id
                                or str(result_row.get("recordId") or ""),
                                "title": str(
                                    values[app.NEWS_REVIEW_TITLE_COLUMN]
                                    if len(values) > app.NEWS_REVIEW_TITLE_COLUMN
                                    else ""
                                )[:500],
                                "before": str(item.get("before") or "")[:120],
                                "after": str(item.get("value") or "")[:120],
                            }
                        )
                    app.AUTH.record_operation(
                        actor=actor,
                        action="news_review.update",
                        target=str(result.get("sheetId") or "news-review-sheet"),
                        origin=app.AUTH.operation_origin(self),
                        details={
                            "changed_count": int(result.get("changedCount") or 0),
                            "decision_rows": decision_rows,
                            "cells": audited_cells,
                            "feishu_readback": bool(result.get("readbackVerified")),
                        },
                    )
                    app.json_response(self, {"ok": True, **app.attach_news_review_actors(result)})
                except (ValueError, RuntimeError) as exc:
                    app.AUTH.record_operation(
                        actor=actor,
                        action="news_review.update",
                        target="news-review-sheet",
                        result="failure",
                        origin=app.AUTH.operation_origin(self),
                        details={"error": str(exc)[:240]},
                    )
                    app.json_response(self, {"ok": False, "error": str(exc)}, 409)
                except Exception as exc:
                    app.AUTH.record_operation(
                        actor=actor,
                        action="news_review.update",
                        target="news-review-sheet",
                        result="failure",
                        origin=app.AUTH.operation_origin(self),
                        details={"error": str(exc)[:240]},
                    )
                    app.json_response(self, {"ok": False, "error": str(exc)}, 500)
                return
            if parsed.path == "/api/crawl":
                if not app.CRAWL_PIPELINE_LOCK.acquire(blocking=False):
                    app.json_response(
                        self,
                        {"ok": False, "error": "已有手动全量爬虫正在运行，请等待其完成。", "active": dict(app.CRAWL_PIPELINE_STATE)},
                        409,
                    )
                    return
                app.CRAWL_PIPELINE_STATE.clear()
                app.CRAWL_PIPELINE_STATE.update({"status": "running", "startedAt": app.datetime.now().astimezone().isoformat(timespec="seconds")})
                try:
                    app.json_response(self, app.run_crawl())
                finally:
                    app.CRAWL_PIPELINE_STATE.clear()
                    app.CRAWL_PIPELINE_LOCK.release()
                return
            if parsed.path == "/api/crawl-stream":
                # crawl-pipeline-lock:v1
                if not app.CRAWL_PIPELINE_LOCK.acquire(blocking=False):
                    app.json_response(
                        self,
                        {"ok": False, "error": "已有手动全量爬虫正在运行，请等待其完成。", "active": dict(app.CRAWL_PIPELINE_STATE)},
                        409,
                    )
                    return
                app.CRAWL_PIPELINE_STATE.clear()
                app.CRAWL_PIPELINE_STATE.update({"status": "starting", "startedAt": app.datetime.now().astimezone().isoformat(timespec="seconds")})
                crawl_run_id = ""
                proc = None
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()

                    started = app.time.time()
                    started_at_hkt = app.datetime.now().astimezone().isoformat(timespec="seconds")
                    crawl_scope = "全量（第2-34行）"
                    started_record = app.start_crawl_run(trigger="手动全量", scope=crawl_scope)
                    crawl_run_id = str(started_record["crawl_run_id"])
                    app.CRAWL_PIPELINE_STATE.update({"status": "running", "crawlRunId": crawl_run_id, "startedAt": started_at_hkt, "scope": crawl_scope})
                    self._crawl_stream_log_path = app.Path(started_record["stream_log_path"])
                    self._crawl_stream_mirror_path = app.ROOT / "latest_crawl_stream.log"
                    app.start_task_lifecycle_monitor(self, "crawl", crawl_run_id, "网页抓取")
                    try:
                        self._crawl_stream_mirror_path.write_text("", encoding="utf-8")
                    except OSError:
                        pass
                    app.write_sse(
                        self,
                        {
                            "type": "run_start",
                            "crawlRunId": crawl_run_id,
                            "startedAt": started_at_hkt,
                            "trigger": "手动全量",
                            "scope": crawl_scope,
                        },
                    )
                    crawl_env = app.os.environ.copy()
                    crawl_env.pop("CMHK_ROWS", None)
                    crawl_env["CMHK_CRAWL_TRIGGER"] = "手动全量"
                    crawl_env["CMHK_CRAWL_SCOPE"] = "全量（第2-34行）"
                    proc = app.subprocess.Popen(
                        [app.sys.executable, "-u", str(app.ROOT / "crawl.py")],
                        cwd=str(app.ROOT),
                        env=crawl_env,
                        stdout=app.subprocess.PIPE,
                        stderr=app.subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    self._task_worker_pid = proc.pid
                    for line in proc.stdout:
                        app.write_sse(self, app.sse_payload_from_process_line(line.strip()))

                    proc.wait()
                    self._task_worker_pid = 0
                    self._task_monitor_phase = "飞书同步"
                    self._task_monitor_detail = "网页抓取进程已结束，正在同步结果并执行后续审核。"
                    log_sheet_id = ""
                    log_sheet_title = ""
                    crawl_failed_count = 0
                    sync_result = {}
                    metrics_refresh = {}
                    trace_sync = {}

                    # Sync to Feishu after full crawl
                    if proc.returncode == 0 and (app.ROOT / "write_payload.json").exists():
                        sync_proc = app.subprocess.run(
                            [app.sys.executable, str(app.ROOT / "daily_crawl_and_write.py"), "--sync-only"],
                            env=crawl_env,
                            capture_output=True,
                            text=True,
                        )
                        if sync_proc.returncode != 0:
                            app.write_sse(self, {"type": "log", "text": f"同步飞书失败: {sync_proc.stderr[-500:]}"})
                            proc.returncode = sync_proc.returncode
                        else:
                            sync_result = app.json_object_from_output(sync_proc.stdout)
                            log_sheet_id = str(sync_result.get("log_sheet_id") or "")
                            log_sheet_title = str(sync_result.get("log_sheet_title") or "")
                            app.write_sse(
                                self,
                                {
                                    "type": "log",
                                    "text": "✅ 飞书表格同步成功！"
                                    + (f" 日志页：{log_sheet_title}" if log_sheet_title else ""),
                                },
                            )

                        # Update supplementary JSON configs with newly extracted data
                        update_proc = app.subprocess.run(
                            [app.sys.executable, str(app.ROOT / "tools" / "maintenance" / "update_sources_from_crawl.py")],
                            capture_output=True,
                            text=True,
                        )
                        if update_proc.returncode != 0:
                            app.write_sse(self, {"type": "log", "text": f"⚠️ 业绩补充桥接更新异常: {update_proc.stderr[-200:]}"})
                        else:
                            if update_proc.stdout.strip():
                                app.write_sse(self, {"type": "log", "text": f"ℹ️ 业绩补充配置同步：{update_proc.stdout.strip()}"})

                        performance_sync = app.run_carrier_performance_sync()
                        if performance_sync["ok"]:
                            payload = app.json.dumps(
                                {"type": "log", "text": "✅ 运营商业绩摘要补充页已同步并通过五类字段校验。"},
                                ensure_ascii=False,
                            )
                        else:
                            payload = app.json.dumps(
                                {
                                    "type": "log",
                                    "text": "运营商业绩摘要补充页同步失败: "
                                    + (performance_sync["stderr"] or performance_sync["stdout"])[-500:],
                                },
                                ensure_ascii=False,
                            )
                            proc.returncode = proc.returncode or performance_sync["returnCode"]
                        app.write_sse(self, app.json.loads(payload))

                        payload = app.json.dumps(
                            {
                                "type": "log",
                                "text": "开始多 Agent 数据整理：来源分类、事实抽取、主体校验、质量审计、冲突仲裁和缺口补爬...",
                            },
                            ensure_ascii=False,
                        )
                        app.write_sse(self, app.json.loads(payload))
                        metrics_refresh = app.stream_company_metrics_refresh(self)
                        if metrics_refresh["ok"]:
                            summary = metrics_refresh["summary"]
                            payload = app.json.dumps(
                                {
                                    "type": "log",
                                    "text": (
                                        "✅ 公司指标页已更新："
                                        f"{summary.get('companies', 0)} 家公司、"
                                        f"{summary.get('metrics', 0)} 类指标、"
                                        f"{summary.get('records', 0)} 条通过校验的记录。"
                                    ),
                                },
                                ensure_ascii=False,
                            )
                        else:
                            payload = app.json.dumps(
                                {
                                    "type": "log",
                                    "text": "❌ 公司指标页 AI 整理失败: "
                                    + (metrics_refresh["stderr"] or metrics_refresh["stdout"])[-500:],
                                },
                                ensure_ascii=False,
                            )
                            proc.returncode = proc.returncode or metrics_refresh["returnCode"]
                        app.write_sse(self, app.json.loads(payload))

                        if metrics_refresh["ok"] and log_sheet_id:
                            latest_curation = app.load_curation_status()
                            agent_run_id = str(latest_curation.get("run_id") or "")
                            app.write_sse(
                                self,
                                {
                                    "type": "agent_trace",
                                    "trace": {
                                        "ts": app.datetime.now().astimezone().isoformat(timespec="seconds"),
                                        "run_id": agent_run_id,
                                        "node": "飞书审计日志",
                                        "phase": "tool_call",
                                        "event_type": "tool_call",
                                        "message": f"将 Agent 处理流程和结果写入飞书日志页 {log_sheet_title or log_sheet_id}。",
                                        "tool": "daily_crawl_and_write.py --append-agent-trace",
                                        "input": {
                                            "sheetId": log_sheet_id,
                                            "sheetTitle": log_sheet_title,
                                            "runId": agent_run_id,
                                        },
                                    },
                                },
                            )
                            trace_sync = app.append_agent_trace_to_feishu_log(log_sheet_id, agent_run_id)
                            trace_result = trace_sync.get("result") or {}
                            app.write_sse(
                                self,
                                {
                                    "type": "agent_trace",
                                    "trace": {
                                        "ts": app.datetime.now().astimezone().isoformat(timespec="seconds"),
                                        "run_id": agent_run_id,
                                        "node": "飞书审计日志",
                                        "phase": "tool_result",
                                        "event_type": "tool_result",
                                        "message": (
                                            f"Agent 流程已写入飞书，共 {trace_result.get('trace_rows', 0)} 条并完成回读校验。"
                                            if trace_sync["ok"]
                                            else "Agent 流程写入飞书失败。"
                                        ),
                                        "tool": "daily_crawl_and_write.py --append-agent-trace",
                                        "result": {
                                            "ok": trace_sync["ok"],
                                            "sheetId": log_sheet_id,
                                            "sheetTitle": log_sheet_title,
                                            "range": trace_result.get("range", ""),
                                            "traceRows": trace_result.get("trace_rows", 0),
                                            "error": (trace_sync["stderr"] or trace_sync["stdout"])[-500:]
                                            if not trace_sync["ok"]
                                            else "",
                                        },
                                    },
                                },
                            )
                            if not trace_sync["ok"]:
                                app.write_sse(
                                    self,
                                    {
                                        "type": "log",
                                        "text": (
                                            "⚠️ 爬取、主表同步和 Agent 整理均已完成；"
                                            "仅飞书审计日志追加失败，可稍后重试，不影响本轮数据结果。"
                                        ),
                                    },
                                )
                        elif metrics_refresh["ok"]:
                            app.write_sse(
                                self,
                                {
                                    "type": "log",
                                    "text": "⚠️ Agent 已完成，但未取得本次飞书日志页 ID，未能追加 Agent 审计区块。",
                                },
                            )

                    try:
                        run_log_path = app.ROOT / "run_log.json"
                        if run_log_path.exists():
                            with run_log_path.open("r", encoding="utf-8") as f:
                                run_log_data = app.json.load(f)
                            success_items = []
                            failure_items = []
                            for item in run_log_data:
                                url = item.get("url", "")
                                status = int(item.get("http_status") or 0)
                                used_fallback = str(
                                    item.get("evidence_fallback_used") or ""
                                ).lower() in {"1", "true", "yes"}
                                if 200 <= status < 400 and not used_fallback:
                                    success_items.append({"url": url, "reason": "OK"})
                                else:
                                    reason = (
                                        item.get("fallback_reason")
                                        if used_fallback
                                        else item.get("error")
                                        or item.get("skip_reason")
                                        or f"HTTP {status}"
                                    )
                                    failure_items.append({"url": url, "reason": reason})
                            crawl_failed_count = len(failure_items)
                            summary_payload = app.json.dumps({
                                "type": "crawl_summary",
                                "success": success_items,
                                "failed": failure_items,
                                "total": len(run_log_data)
                            }, ensure_ascii=False)
                            app.write_sse(self, app.json.loads(summary_payload))
                    except Exception as e:
                        pass

                    duration_ms = round((app.time.time() - started) * 1000)
                    runtime_sync_script = app.ROOT / "sync_scheduler_runtime.sh"
                    if proc.returncode == 0 and runtime_sync_script.exists():
                        try:
                            runtime_sync = app.subprocess.run(
                                [str(runtime_sync_script)],
                                cwd=str(app.ROOT),
                                capture_output=True,
                                text=True,
                                timeout=120,
                            )
                        except Exception as exc:
                            app.write_sse(
                                self,
                                {
                                    "type": "log",
                                    "text": (
                                        "后台调度运行副本同步异常，已保留本轮结果并继续登记："
                                        f"{type(exc).__name__}: {exc}"
                                    ),
                                },
                            )
                        else:
                            if runtime_sync.returncode != 0:
                                app.write_sse(
                                    self,
                                    {
                                        "type": "log",
                                        "text": f"后台调度运行副本同步失败，已继续登记：{runtime_sync.stderr[-500:]}",
                                    },
                                )
                    crawl_run_record = app.register_crawl_run(
                        crawl_return_code=proc.returncode,
                        duration_ms=duration_ms,
                        sync_result=sync_result,
                        metrics_refresh=metrics_refresh,
                        trace_sync=trace_sync,
                        trigger="手动全量",
                        scope=crawl_scope,
                        crawl_run_id=crawl_run_id,
                        started_at_hkt=started_at_hkt,
                        stream_log_path=self._crawl_stream_log_path,
                    )
                    app.write_sse(
                        self,
                        {
                            "type": "log",
                            "text": (
                                "爬虫运行日志索引已保存："
                                f"{crawl_run_record.get('crawl_run_id')}；"
                                f"飞书日志页：{(crawl_run_record.get('feishu') or {}).get('log_sheet_title') or '未写入'}。"
                            ),
                        },
                    )
                    app.write_sse(self, {
                        "type": "done",
                        "ok": proc.returncode == 0,
                        "completedWithWarnings": proc.returncode == 0 and crawl_failed_count > 0,
                        "failedUrlCount": crawl_failed_count,
                        "durationMs": duration_ms,
                        "status": app.build_status(),
                        "crawlRunRegistry": crawl_run_record,
                    })
                    return
                except Exception as exc:
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except app.subprocess.TimeoutExpired:
                            proc.kill()
                    detail = f"爬虫流水线异常中断：{type(exc).__name__}: {exc}"
                    if crawl_run_id:
                        app.mark_crawl_run_interrupted(crawl_run_id, detail)
                    try:
                        app.write_sse(self, {"type": "log", "text": "[任务中断] " + detail})
                        app.write_sse(self, {"type": "done", "ok": False, "interrupted": True, "message": detail})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                finally:
                    app.stop_task_lifecycle_monitor(self)
                    app.CRAWL_PIPELINE_STATE.clear()
                    app.CRAWL_PIPELINE_LOCK.release()
            if parsed.path == "/api/generate-stream":
                app.stream_report_generation(self, "generate_weekly_report.py", "weekly")
                return

            if parsed.path == "/api/generate-carrier-performance-stream":
                app.stream_report_generation(
                    self,
                    "generate_carrier_performance_report.py",
                    "carrier-performance",
                )
                return

            if parsed.path == "/api/generate":
                app.json_response(self, app.run_report_generation())
                return

            if parsed.path == "/api/generate-carrier-performance":
                app.json_response(self, app.run_carrier_performance_generation())
                return

            if parsed.path == "/api/agent-datasets/upload":
                try:
                    result = app.write_uploaded_knowledge_dataset(app.read_request_json(self))
                    app.json_response(self, {"ok": True, **result, "datasets": app.list_knowledge_datasets()})
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return

            if parsed.path == "/api/audio/generate":
                try:
                    body = app.read_request_json(self)
                    target = app.report_target_from_rel(str(body.get("path") or ""))
                    if not target:
                        raise ValueError("文件不存在或不允许生成音频")
                    task, created = app.start_audio_generation_task(target, bool(body.get("force", False)))
                    app.json_response(
                        self,
                        {
                            "ok": True,
                            "queued": created,
                            "alreadyRunning": not created,
                            "task": task,
                        },
                        202,
                    )
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/report-file":
                try:
                    app.json_response(self, {"ok": True, "status": app.update_report_file(app.read_request_json(self))})
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/report-editor":
                try:
                    if int(self.headers.get("Content-Length") or 0) > 24 * 1024 * 1024:
                        app.json_response(self, {"ok": False, "error": "编辑内容超过 24 MB 上限"}, 413)
                        return
                    body = app.read_request_json(self)
                    actor = app.AUTH.current_actor(self)
                    result = app.save_report_editor_payload(body, actor=actor)
                    try:
                        app.AUTH.record_operation(
                            actor=actor,
                            action="report.content_edit",
                            target=str(result.get("path") or "")[:240],
                            result="success",
                            origin=app.AUTH.operation_origin(self),
                            details={
                                "source_label": "报告全屏编辑器",
                                "page": "weekly" if (result.get("file") or {}).get("reportType") == "weekly" else "performance",
                                "source_path": str(result.get("sourcePath") or "")[:240],
                                "saved_path": str(result.get("path") or "")[:240],
                                "editor_revision": int((result.get("file") or {}).get("editRevision") or 0),
                            },
                        )
                    except Exception:
                        app.logging.exception("failed to record report editor footprint")
                    app.json_response(self, {"ok": True, **result})
                except app.ReportEditConflict as exc:
                    app.json_response(self, {"ok": False, "error": str(exc), "conflict": True}, 409)
                except FileNotFoundError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 404)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/delete-files":
                try:
                    body = app.read_request_json(self)
                    result = app.delete_report_files(body.get("paths", []))
                    app.json_response(self, {"ok": True, **result})
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/ai-config":
                try:
                    app.json_response(self, {"ok": True, "config": app.save_ai_config(app.read_request_json(self)), "status": app.build_status()})
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/chat-image-analyze":
                try:
                    app.json_response(self, {"ok": True, **app.analyze_chat_image(app.read_request_json(self))})
                except app.urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="ignore")[:600]
                    app.json_response(self, {"ok": False, "error": f"视觉模型返回 HTTP {exc.code}：{detail}"}, 400)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/chat-audio-transcribe":
                try:
                    content_length = int(self.headers.get("Content-Length") or 0)
                    if content_length > (app.CHAT_AUDIO_MAX_BYTES * 2):
                        raise ValueError("单次语音不能超过 20 MB")
                    app.json_response(self, {"ok": True, **app.transcribe_chat_audio(app.read_request_json(self))})
                except app.urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="ignore")[:600]
                    app.json_response(self, {"ok": False, "error": f"语音模型返回 HTTP {exc.code}：{detail}"}, 400)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/ai-models":
                try:
                    payload = app.read_request_json(self)
                    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
                    if not app.re.match(r"^https?://", base_url, flags=app.re.I):
                        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
                    if not app.is_internal_ai_base_url(base_url):
                        raise ValueError("只能访问指定的 AI 模型服务")
                    saved = app.load_ai_config(include_key=True)
                    api_key = str(payload.get("api_key") or saved.get("api_key") or "").strip()
                    if not api_key:
                        raise ValueError("请输入 API Key，或先保存一个有效 Key")
                    request = app.urllib.request.Request(
                        f"{base_url}/models",
                        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                        method="GET",
                    )
                    with app.open_llm_request(
                        request,
                        timeout=30,
                        config=saved,
                        requested_key=api_key,
                    ) as response:
                        model_payload = app.json.loads(response.read().decode("utf-8"))
                    models = sorted(
                        {
                            str(item.get("id") or "").strip()
                            for item in (model_payload.get("data") or [])
                            if isinstance(item, dict) and str(item.get("id") or "").strip()
                        },
                        key=str.lower,
                    )
                    if not models:
                        raise ValueError("服务已连接，但没有返回可用模型")
                    app.json_response(self, {"ok": True, "models": models, "count": len(models)})
                except app.urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="ignore")[:600]
                    app.json_response(self, {"ok": False, "error": f"模型服务返回 HTTP {exc.code}：{detail}"}, 400)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/ai-test":
                started = app.time.monotonic()
                try:
                    payload = app.read_request_json(self)
                    config = app.load_ai_config(include_key=True)
                    provider = str(payload.get("provider") or config.get("provider") or "deepseek").lower()
                    base_url = str(payload.get("base_url") or config.get("base_url") or "").strip().rstrip("/")
                    model = str(payload.get("model") or config.get("model") or "").strip()
                    api_key = str(payload.get("api_key") or config.get("api_key") or "").strip()
                    if not base_url or not model or not api_key:
                        raise ValueError("Base URL、模型和 API Key 均不能为空")
                    if not app.re.match(r"^https?://", base_url, flags=app.re.I):
                        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
                    if not app.is_internal_ai_base_url(base_url):
                        raise ValueError("只能访问指定的 AI 模型服务")
                    if provider == "openai":
                        url = f"{base_url}/responses"
                        body = {"model": model, "input": "Reply OK", "max_output_tokens": 16}
                    else:
                        url = f"{base_url}/chat/completions"
                        body = {
                            "model": model,
                            "messages": [{"role": "user", "content": "只回复OK"}],
                            "max_tokens": 32,
                            "stream": False,
                        }
                    body.update(config.get("extra_parameters") or {})
                    if provider != "openai":
                        from cmhk.ai.ai_response_compat import deepseek_nonthinking_parameters
                        body = deepseek_nonthinking_parameters(body)
                    request = app.urllib.request.Request(
                        url,
                        data=app.json.dumps(body, ensure_ascii=False).encode("utf-8"),
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        method="POST",
                    )
                    with app.open_llm_request(
                        request,
                        timeout=45,
                        config=config,
                        requested_key=api_key,
                        model=model,
                        operation="ai-settings-test",
                    ) as response:
                        response.read()
                    result = {
                        "ok": True,
                        "provider": provider,
                        "model": model,
                        "latency_ms": round((app.time.monotonic() - started) * 1000),
                    }
                    app.json_response(self, {"ok": True, "result": result, "status": app.build_status()})
                except app.urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="ignore")[:600]
                    app.json_response(self, {"ok": False, "error": f"模型服务返回 HTTP {exc.code}：{detail}"}, 400)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/rag-token-estimate":
                payload = app.read_request_json(self)
                text = str(payload.get("text") or "")
                model = str(payload.get("model") or "")
                app.json_response(
                    self,
                    {
                        "ok": True,
                        "tokens": app.estimate_tokens(text, model=model or None),
                        "chars": len(text),
                        "model": model or None,
                        "counter": "tiktoken_or_heuristic",
                    },
                )
                return
            if parsed.path == "/api/agent-memory/delete":
                payload = app.read_request_json(self)
                memory_id = str(payload.get("id") or "")
                app.json_response(self, {"ok": app.delete_memory(memory_id), "id": memory_id})
                return
            if parsed.path == "/api/chat-approval":
                payload = app.read_request_json(self)
                request_id = str(payload.get("requestId") or "")
                action_id = str(payload.get("actionId") or "")
                decision = "allow" if payload.get("decision") == "allow" else "deny"
                resolved = app.resolve_chat_approval(request_id, action_id, decision)
                app.json_response(
                    self,
                    {"ok": resolved, "requestId": request_id, "actionId": action_id, "decision": decision},
                    200 if resolved else 404,
                )
                return
            if parsed.path == "/api/chat-threads":
                try:
                    payload = app.read_request_json(self)
                    action = str(payload.get("action") or "save")
                    if action == "delete":
                        thread_id = str(payload.get("id") or "")
                        app.json_response(self, {"ok": app.delete_chat_thread(thread_id), "threads": app.chat_thread_summaries()})
                    elif action == "pin":
                        thread_id = str(payload.get("id") or "")
                        pinned = bool(payload.get("pinned"))
                        thread = app.set_chat_thread_pinned(thread_id, pinned)
                        app.json_response(
                            self,
                            {"ok": bool(thread), "thread": thread, "threads": app.chat_thread_summaries()},
                            200 if thread else 404,
                        )
                    else:
                        thread = app.upsert_chat_thread(payload)
                        app.json_response(self, {"ok": True, "thread": thread, "threads": app.chat_thread_summaries()})
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/chat":
                app.json_response(self, {"ok": False, "error": "deprecated API, use stream"}, 404)
                return
            if parsed.path == "/api/chat-stream":
                payload = app.read_request_json(self)
                message = str(payload.get("message") or "")
                request_id = app.re.sub(r"[^A-Za-z0-9_.:-]", "", str(payload.get("requestId") or ""))[:160]
                if not request_id:
                    request_id = f"chat-{app.uuid.uuid4().hex}"
                web_search_enabled = bool(payload.get("webSearchEnabled"))
                thinking_enabled = bool(payload.get("thinkingEnabled"))
                selected_skill_ids = payload.get("selectedSkillIds")
                if not isinstance(selected_skill_ids, list):
                    selected_skill_ids = []
                selected_dataset_ids = payload.get("selectedDatasetIds")
                if not isinstance(selected_dataset_ids, list):
                    selected_dataset_ids = []
                approved_action_ids = payload.get("approvedActionIds")
                if not isinstance(approved_action_ids, list):
                    approved_action_ids = []
                conversation_history = payload.get("conversationHistory")
                if not isinstance(conversation_history, list):
                    conversation_history = []
                emit_context_events = bool(payload.get("emitContextEvents", True))
                loaded_skill_ids = payload.get("loadedSkillIds")
                if not isinstance(loaded_skill_ids, list):
                    loaded_skill_ids = []
                active_thread_id = app.re.sub(
                    r"[^A-Za-z0-9_.:-]", "", str(payload.get("threadId") or "")
                )[:160]
                try:
                    resume_after = max(0, int(payload.get("resumeAfter") or 0))
                except (TypeError, ValueError):
                    resume_after = 0
                runtime_context = app.request_runtime_context(self)
                try:
                    session = app.get_or_create_chat_stream_session(
                        request_id,
                        payload,
                        lambda: app.stream_agent_with_approvals(
                            message,
                            request_id=request_id,
                            force_web_search=web_search_enabled,
                            selected_skill_ids=[str(item) for item in selected_skill_ids],
                            selected_dataset_ids=[str(item) for item in selected_dataset_ids],
                            thinking_enabled=thinking_enabled,
                            approved_action_ids=[str(item) for item in approved_action_ids],
                            conversation_history=conversation_history,
                            emit_context_events=emit_context_events,
                            loaded_skill_ids=[str(item) for item in loaded_skill_ids],
                            runtime_context=runtime_context,
                            active_thread_id=active_thread_id,
                        ),
                    )
                except ValueError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 409)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("X-CMHK-Chat-Session", session.session_id)
                self.end_headers()

                try:
                    for event in session.events_after(resume_after):
                        body = app.json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        if event.get("type") == "done":
                            self.close_connection = True
                except (BrokenPipeError, ConnectionResetError):
                    # The producer is intentionally independent of this socket.
                    # A reconnect with resumeAfter replays only unseen events.
                    self.close_connection = True
                return
            app.json_response(self, {"ok": False, "error": "not found"}, 404)

    app.WriteRoutes = WriteRoutes
