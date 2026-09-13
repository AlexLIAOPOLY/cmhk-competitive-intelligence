from __future__ import annotations



def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    class ReadRoutes:
        def do_HEAD(self) -> None:
            parsed = app.urlparse(self.path)
            if parsed.path.startswith("/data-releases/quarterly/"):
                if not self.authorize_data_release():
                    return
                target = app.resolve_release_request(app.QUARTERLY_RELEASE_ROOT, parsed.path)
                if target is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.serve_head(target)
                return
            if parsed.path in {"/", "/company-data", "/company-data.html", "/executive-dashboard-demo", "/executive-dashboard-demo.html", "/static/index.html"}:
                if not app.AUTH.authorize_page(self, parsed.path):
                    return
            if parsed.path.startswith(("/static/", "/outputs/", "/audio/", "/generated-charts/", "/references/", "/references-raw/")):
                if not app.AUTH.authorize_resource(self, parsed.path):
                    return
            if parsed.path == "/":
                self.serve_head(app.STATIC_DIR / "index.html")
                return
            if parsed.path in {"/company-data", "/company-data.html"}:
                self.serve_head(app.STATIC_DIR / "company-data.html")
                return
            if parsed.path.startswith("/static/"):
                self.serve_head(app.STATIC_DIR / parsed.path.removeprefix("/static/"))
                return
            if parsed.path.startswith("/outputs/"):
                name = app.Path(app.unquote(parsed.path.removeprefix("/outputs/"))).name
                target = app.ROOT / name
                if app.is_report_path(target):
                    self.serve_head(target, download=True)
                    return
            if parsed.path.startswith("/audio/"):
                name = app.Path(app.unquote(parsed.path.removeprefix("/audio/"))).name
                target = app.AUDIO_DIR / name
                if target.exists() and target.suffix.lower() in {".wav", ".mp3"}:
                    self.serve_audio(target, head_only=True)
                    return
            if parsed.path.startswith("/generated-charts/"):
                target = app.generated_chart_path(app.unquote(parsed.path.removeprefix("/generated-charts/")))
                if target and target.exists():
                    self.serve_head(target)
                    return
            if parsed.path.startswith("/references/"):
                target = app.reference_path(app.unquote(parsed.path.removeprefix("/references/")))
                if target and target.exists():
                    self.serve_reference_head(target)
                    return
            if parsed.path.startswith("/references-raw/"):
                target = app.reference_path(app.unquote(parsed.path.removeprefix("/references-raw/")))
                if target and target.exists():
                    self.serve_head(target)
                    return
            if parsed.path.startswith("/archives/"):
                target = app.ROOT / app.unquote(parsed.path.lstrip("/"))
                if app.is_report_path(target):
                    self.serve_head(target, download=True)
                    return
            self.send_response(404)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = app.urlparse(self.path)
            path = parsed.path
            if app.AUTH.handle(self, "GET", parsed):
                return
            if path.startswith("/data-releases/quarterly/"):
                if not self.authorize_data_release():
                    return
                target = app.resolve_release_request(app.QUARTERLY_RELEASE_ROOT, path)
                if target is None:
                    app.json_response(self, {"ok": False, "error": "release file not found"}, 404)
                    return
                self.serve_file(target)
                return
            if path in {"/", "/company-data", "/company-data.html", "/executive-dashboard-demo", "/executive-dashboard-demo.html", "/static/index.html"}:
                if not app.AUTH.authorize_page(self, path):
                    return
            if path.startswith(("/static/", "/outputs/", "/audio/", "/generated-charts/", "/references/", "/references-raw/")):
                if not app.AUTH.authorize_resource(self, path):
                    return
            if path.startswith("/api/") and not app.AUTH.authorize_api(self, path, "GET"):
                return
            if path == "/":
                self.serve_file(app.STATIC_DIR / "index.html")
                return
            if path in {"/company-data", "/company-data.html"}:
                self.serve_file(app.STATIC_DIR / "company-data.html")
                return
            if path in {"/executive-dashboard-demo", "/executive-dashboard-demo.html"}:
                self.serve_file(app.STATIC_DIR / "executive-dashboard-demo.html")
                return
            if path == "/api/status":
                app.json_response(self, {"ok": True, "status": app.build_status()})
                return
            if path == "/api/ai-capacity":
                app.json_response(self, {"ok": True, "capacity": app.capacity_status()})
                return
            if path == "/api/health":
                app.json_response(self, {"ok": True, "status": app.build_status()})
                return
            if path == "/api/weekly-report-preview":
                try:
                    app.json_response(self, {"ok": True, "preview": app.build_weekly_report_generation_preview()})
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=503)
                return
            if path == "/api/report-audio":
                path_str = (app.parse_qs(parsed.query).get("path") or [""])[0]
                target = app.report_target_from_rel(path_str)
                if not target:
                    app.json_response(self, {"ok": False, "error": "report file not found"}, 404)
                    return
                app.json_response(self, {"ok": True, "audio": app.audio_info_for_report(target)})
                return
            if path == "/api/report-editor":
                path_str = (app.parse_qs(parsed.query).get("path") or [""])[0]
                try:
                    app.json_response(self, {"ok": True, **app.load_report_editor_payload(path_str)})
                except FileNotFoundError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 404)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if path == "/api/chat-starters":
                app.json_response(self, {"ok": True, "starters": app.sample_chat_starters()})
                return
            if path == "/api/strategic-briefs":
                try:
                    from strategic_briefing import public_snapshot

                    app.json_response(self, {"ok": True, **public_snapshot()})
                except Exception as exc:
                    app.json_response(
                        self,
                        {"ok": False, "error": str(exc), "items": []},
                        status=500,
                    )
                return
            if path == "/api/weekly-report-preference":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "周报推送版本仅允许本机管理"}, status=403)
                    return
                try:
                    app.json_response(self, {
                        "ok": True,
                        "preference": app.weekly_report_preference_payload(app.subscription_service()),
                    })
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            if path == "/api/performance-report-preference":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "业绩摘要推送版本仅允许本机管理"}, status=403)
                    return
                try:
                    app.json_response(self, {
                        "ok": True,
                        "preference": app.performance_report_preference_payload(app.subscription_service()),
                    })
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            if path == "/api/subscriptions/news-deliveries":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "个人推送记录仅允许本机管理端访问"}, status=403)
                    return
                try:
                    from cmhk.services.news_delivery_history import news_delivery_history
                    params = app.parse_qs(parsed.query)
                    delivery_id = int(params["id"][0]) if params.get("id") else None
                    result = news_delivery_history(
                        app.ROOT / "var" / "subscriptions" / "subscriptions.sqlite3",
                        selected_date=str((params.get("date") or [""])[0]), delivery_id=delivery_id,
                    )
                    app.json_response(self, result)
                except ValueError:
                    app.json_response(self, {"ok": False, "error": "请使用有效日期或推送记录编号"}, status=400)
                except LookupError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=404)
                except Exception:
                    app.logging.exception("news delivery history read failed")
                    app.json_response(self, {"ok": False, "error": "个人推送记录暂时无法读取，请稍后重试"}, status=500)
                return
            if path == "/api/subscriptions/push-status":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "订阅管理后台仅允许本机访问"}, status=403)
                    return
                job_id = str((app.parse_qs(parsed.query).get("id") or [""])[0])
                job = app.subscription_push_job_snapshot(job_id)
                if not job:
                    app.json_response(self, {"ok": False, "error": "找不到该推送任务"}, status=404)
                    return
                app.json_response(self, {"ok": True, "job": job})
                return
            if path == "/api/subscriptions":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "订阅管理后台仅允许本机访问"}, status=403)
                    return
                try:
                    service = app.subscription_service()
                    summary = service.list_summary()
                    status = app.build_status()
                    reports = [
                        {
                            "name": str(item.get("name") or ""),
                            "path": str(item.get("path_str") or ""),
                            "report_type": str(item.get("reportType") or ""),
                            "mtime_text": str(item.get("mtimeText") or ""),
                            "is_edited": bool(item.get("isEdited")),
                            "edit_revision": int(item.get("editRevision") or 0),
                            "edited_at": str(item.get("editedAt") or ""),
                            "edited_by": str(item.get("editedBy") or ""),
                            "source_path": str(item.get("sourcePath") or ""),
                            "note": str(item.get("note") or ""),
                            "audio": bool((item.get("audio") or {}).get("exists")) if isinstance(item.get("audio"), dict) else False,
                        }
                        for item in (status.get("outputs") or [])
                        if isinstance(item, dict) and item.get("reportType") in {"weekly", "carrier-performance"}
                    ]
                    card_actions = service.config.get("card_actions") if isinstance(service.config.get("card_actions"), dict) else {}
                    app.json_response(self, {
                        "ok": True,
                        **summary,
                        "targets": service.available_targets(),
                        "frequencies": [
                            {"key": key, "label": app.FREQUENCY_LABELS[key]}
                            for key in ("twice_daily", "once_daily")
                        ],
                        "frequency_scope": "news",
                        "report_cadence": {
                            "key": "biweekly_on_publish",
                            "label": app.REPORT_CADENCE_LABEL,
                        },
                        "report_modes": [
                            {"key": key, "label": app.REPORT_MODE_LABELS[key]}
                            for key in ("pdf", "pdf_audio", "audio")
                        ],
                        "news_categories": [
                            {"key": key, "label": label}
                            for key, label in app.NEWS_CATEGORY_LABELS.items()
                        ],
                        "reports": reports,
                        "manual_push_job": app.subscription_push_job_snapshot(),
                        "test_target": {
                            "callback_open_id": str(card_actions.get("primary_handler_open_id") or ""),
                            "delivery_open_id": str(card_actions.get("primary_handler_open_id") or ""),
                            "name": str(card_actions.get("primary_handler_expected_name") or "系统管理员"),
                        },
                    })
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            if path == "/api/subscriptions/avatar":
                if not app.is_loopback_client(str(self.client_address[0])):
                    app.json_response(self, {"ok": False, "error": "订阅管理后台仅允许本机访问"}, status=403)
                    return
                try:
                    open_id = (app.parse_qs(parsed.query).get("openId") or [""])[0]
                    source_url = app.subscription_service().avatar_source_url(open_id)
                    request = app.urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
                    with app.urllib.request.urlopen(request, timeout=15) as response:
                        body = response.read(2_000_000)
                        content_type = str(response.headers.get_content_type() or "image/png")
                    if not content_type.startswith("image/") or not body:
                        raise ValueError("飞书头像返回格式无效")
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "private, max-age=3600")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                except ValueError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=404)
                except Exception as exc:
                    app.json_response(self, {"ok": False, "error": f"飞书头像读取失败：{exc}"}, status=502)
                return
            if path == "/api/news-review-sheet":
                try:
                    app.json_response(self, app.build_news_review_sheet_payload())
                except Exception as exc:
                    app.json_response(
                        self,
                        {"ok": False, "error": str(exc), "headers": [], "rows": []},
                        status=503,
                    )
                return
            if path == "/api/executive-intelligence":
                try:
                    from cmhk.intelligence.executive import build_executive_intelligence_snapshot

                    app.json_response(
                        self,
                        {"ok": True, **build_executive_intelligence_snapshot()},
                    )
                except Exception as exc:
                    app.json_response(
                        self,
                        {"ok": False, "error": str(exc), "domains": [], "relations": []},
                        status=500,
                    )
                return
            if path == "/api/competitor-intelligence-map":
                try:
                    from cmhk.intelligence.competitor_map import build_competitor_intelligence_map

                    app.json_response(self, build_competitor_intelligence_map(app.ROOT))
                except Exception as exc:
                    app.json_response(
                        self,
                        {"ok": False, "error": str(exc), "items": []},
                        status=500,
                    )
                return
            if path == "/api/scheduler-overview":
                try:
                    query = app.parse_qs(parsed.query)
                    live = str(query.get("live", [""])[0] or "").lower() in {
                        "1", "true", "yes",
                    }
                    app.json_response(self, app.build_scheduler_overview(force=live))
                except Exception as exc:
                    app.json_response(
                        self,
                        {"ok": False, "error": str(exc), "configured_rows": 0, "source_groups": [], "next_runs": []},
                        status=503,
                    )
                return
            if path == "/api/executive-company-benchmarks":
                try:
                    app.json_response(self, app.build_company_benchmarks())
                except Exception as exc:
                    app.json_response(
                        self,
                        {"ok": False, "error": str(exc), "companies": [], "metrics": {}, "values": {}},
                        status=500,
                    )
                return
            if path == "/api/company-metrics":
                app.json_response(
                    self,
                    {
                        "ok": True,
                        "data": app.build_company_metrics_payload(),
                        "curation": app.load_curation_status(),
                    },
                )
                return
            if path == "/api/data-curation":
                app.json_response(self, {"ok": True, "curation": app.load_curation_status()})
                return
            if path == "/api/agent-trace":
                query = app.parse_qs(parsed.query)
                try:
                    limit = max(1, min(1000, int(query.get("limit", ["300"])[0])))
                except Exception:
                    limit = 300
                app.json_response(
                    self,
                    {
                        "ok": True,
                        "trace": app.load_agent_trace(limit=limit),
                        "summary": app.load_curation_status(),
                    },
                )
                return
            if path == "/api/agent-skills":
                app.json_response(self, {"ok": True, "skills": app.available_agent_skills()})
                return
            if path == "/api/agent-runs":
                query = app.parse_qs(parsed.query)
                try:
                    limit = max(1, min(100, int(query.get("limit", ["20"])[0])))
                except Exception:
                    limit = 20
                app.json_response(self, {"ok": True, "runs": app.list_agent_runs(limit=limit)})
                return
            if path == "/api/agent-memory":
                query = app.parse_qs(parsed.query)
                try:
                    limit = max(1, min(100, int(query.get("limit", ["50"])[0])))
                except Exception:
                    limit = 50
                app.json_response(self, {"ok": True, "memories": app.load_memories(limit=limit)})
                return
            if path == "/api/chat-threads":
                query = app.parse_qs(parsed.query)
                thread_id = str(query.get("id", [""])[0] or "")
                if thread_id:
                    thread = app.get_chat_thread(thread_id)
                    app.json_response(self, {"ok": bool(thread), "thread": thread}, 200 if thread else 404)
                else:
                    app.json_response(self, {"ok": True, "threads": app.chat_thread_summaries()})
                return
            if path == "/api/agent-dataset-lineage":
                query = app.parse_qs(parsed.query)
                raw_ids = query.get("datasetId", []) + query.get("datasetIds", [])
                dataset_ids = {item for raw in raw_ids for item in str(raw).split(",") if item}
                app.json_response(self, {"ok": True, "lineage": app.dataset_lineage(dataset_ids or None)})
                return
            if path == "/api/agent-datasets":
                app.json_response(
                    self,
                    {
                        "ok": True,
                        "root": "agent_knowledge",
                        "allowedExtensions": sorted(app.UPLOAD_ALLOWED_SUFFIXES),
                        "datasets": app.list_knowledge_datasets(),
                    },
                )
                return
            if path == "/api/task-runs":
                query = app.parse_qs(parsed.query)
                try:
                    limit = max(1, min(100, int(query.get("limit", ["50"])[0])))
                except Exception:
                    limit = 50
                app.json_response(self, {"ok": True, "tasks": app.load_unified_task_index(limit)})
                return
            if path == "/api/project-incidents":
                query = app.parse_qs(parsed.query)
                try:
                    limit = max(1, min(500, int(query.get("limit", ["100"])[0])))
                except Exception:
                    limit = 100
                sync_requested = str(query.get("sync", ["1"])[0] or "1").lower() not in {
                    "0", "false", "no",
                }
                sheet_sync = (
                    app.sync_project_monitor_sheet_handlers()
                    if sync_requested
                    else {"status": "skipped", "changes": 0, "reason": "local_snapshot_read"}
                )
                incidents = app.load_project_incident_index(limit)
                app.json_response(
                    self,
                    {
                        "ok": True,
                        "incidents": incidents,
                        "total": app.count_project_incidents(),
                        "sheetSync": sheet_sync,
                    },
                )
                return
            if path in {"/api/alert-report.pdf", "/api/log-report.pdf"}:
                report_type = "alert" if path == "/api/alert-report.pdf" else "log"
                period = str((app.parse_qs(parsed.query).get("period") or ["daily"])[0]).lower()
                try:
                    records = app.load_project_incident_index(100_000) if report_type == "alert" else app.load_unified_task_index(100_000)
                    body, _model = app.generate_operational_report_pdf(report_type, period, records)
                except ValueError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, status=400)
                    return
                except Exception as exc:
                    app.logging.exception("operational report PDF generation failed")
                    app.json_response(self, {"ok": False, "error": f"PDF 生成失败：{exc}"}, status=500)
                    return
                filename = app.report_filename(report_type, period)
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/task-run-log":
                query = app.parse_qs(parsed.query)
                task_id = str(query.get("id", [""])[0] or "")
                result = app.load_unified_task_log(task_id)
                app.json_response(self, result, 200 if result.get("ok") else 404)
                return
            if path == "/api/news-monitoring-keywords":
                app.json_response(self, app.monitoring_keywords_snapshot())
                return
            if path == "/api/news-research":
                from data_curation.research_readback import research_snapshot

                query = app.parse_qs(parsed.query)
                try:
                    result = research_snapshot(app.ROOT, str(query.get("date", [""])[0]))
                    app.json_response(self, result)
                except ValueError as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            if path == "/api/research-formal-table":
                from data_curation.research_table_view import formal_table_view

                query = app.parse_qs(parsed.query)
                try:
                    result = formal_table_view(
                        app.ROOT,
                        run_id=str(query.get("runId", [""])[0]),
                        table_id=str(query.get("table", [""])[0]),
                        page=int(query.get("page", ["1"])[0]),
                        page_size=int(query.get("pageSize", ["100"])[0]),
                        query=str(query.get("query", [""])[0]),
                        highlight_only=str(query.get("highlightOnly", [""])[0]).lower()
                        in {"1", "true", "yes"},
                    )
                    app.json_response(self, result)
                except (TypeError, ValueError) as exc:
                    app.json_response(self, {"ok": False, "error": str(exc)}, 400)
                except FileNotFoundError:
                    app.json_response(self, {"ok": False, "error": "正式表或研究批次档案不存在"}, 404)
                return
            if path == "/api/fixed-source-summary":
                app.json_response(self, app.fixed_source_summary())
                return
            if path == "/api/crawl-runs":
                query = app.parse_qs(parsed.query)
                try:
                    limit = max(1, min(500, int(query.get("limit", ["20"])[0])))
                except Exception:
                    limit = 20
                task_kind = str(query.get("taskKind", [""])[0] or "").strip()
                runs = app.load_crawl_run_history(task_kind=task_kind)
                app.json_response(
                    self,
                    {
                        "ok": True,
                        "runs": runs[:limit],
                        "total": len(runs),
                        "taskKind": task_kind,
                        "truncated": len(runs) > limit,
                    },
                )
                return
            if path == "/api/crawl-run-log":
                query = app.parse_qs(parsed.query)
                crawl_run_id = str(query.get("id", [""])[0] or "")
                result = app.load_crawl_run_log(crawl_run_id)
                if result.get("ok"):
                    result["newsItems"] = app.strategic_news_items_for_crawl_run(result.get("run"))
                    result["monitoringKeywords"] = app.monitoring_keywords_snapshot(crawl_run_id)
                    result.update(app.strategic_news_process_items_for_crawl_run(result.get("run")))
                    result["crawlItems"] = app.main_crawl_items_for_crawl_run(result.get("run"))
                    result["fixedSourceSummary"] = app.fixed_source_summary()
                    run = result.get("run") if isinstance(result.get("run"), dict) else {}
                    curation = run.get("curation") if isinstance(run.get("curation"), dict) else {}
                    agent_run_id = str(curation.get("agent_run_id") or "")
                    quality = app.load_curation_quality_records(agent_run_id) if agent_run_id else {"ok": False, "records": []}
                    result["agentReviewItems"] = quality.get("records", []) if quality.get("ok") else []
                    result["agentReviewSummary"] = quality.get("summary", {}) if quality.get("ok") else {}
                    research_trace, research_reports = app.load_agent_research_for_run(agent_run_id)
                    result["companyAgentTrace"] = research_trace
                    result["companyAgentReports"] = research_reports
                    progress = app.load_company_agent_progress_for_run(agent_run_id)
                    result["companyAgentProgress"] = {
                        key: value for key, value in progress.items() if key != "reports"
                    }
                    result["newsSelectionItems"] = app.news_selection_items_for_crawl_run(run)
                app.json_response(self, result, 200 if result.get("ok") else 404)
                return
            if path == "/api/curation-quality-records":
                query = app.parse_qs(parsed.query)
                run_id = str(query.get("runId", [""])[0] or "")
                result = app.load_curation_quality_records(run_id)
                status = 200 if result.get("ok") else (202 if result.get("pending") else 400)
                app.json_response(self, result, status)
                return

            if path == "/api/ai-config":
                app.json_response(self, {"ok": True, "config": app.load_ai_config(include_key=False)})
                return
            if path.startswith("/outputs/"):
                name = app.Path(app.unquote(path.removeprefix("/outputs/"))).name
                target = app.ROOT / name
                if not app.is_report_path(target):
                    app.json_response(self, {"ok": False, "error": "file not allowed"}, 404)
                    return
                self.serve_file(target, download=True)
                return
            if path.startswith("/audio/"):
                name = app.Path(app.unquote(path.removeprefix("/audio/"))).name
                target = app.AUDIO_DIR / name
                if not target.exists() or target.suffix.lower() not in {".wav", ".mp3"} or target.parent != app.AUDIO_DIR:
                    app.json_response(self, {"ok": False, "error": "audio not found"}, 404)
                    return
                self.serve_audio(target)
                return
            if path.startswith("/generated-charts/"):
                target = app.generated_chart_path(app.unquote(path.removeprefix("/generated-charts/")))
                if not target or not target.exists():
                    app.json_response(self, {"ok": False, "error": "chart not found"}, 404)
                    return
                self.serve_file(target)
                return
            if path.startswith("/references/"):
                target = app.reference_path(app.unquote(path.removeprefix("/references/")))
                if not target:
                    app.json_response(self, {"ok": False, "error": "reference not allowed"}, 404)
                    return
                self.serve_reference(target)
                return
            if path.startswith("/references-raw/"):
                target = app.reference_path(app.unquote(path.removeprefix("/references-raw/")))
                if not target:
                    app.json_response(self, {"ok": False, "error": "reference not allowed"}, 404)
                    return
                self.serve_file(target)
                return
            if path.startswith("/static/"):
                self.serve_file(app.STATIC_DIR / path.removeprefix("/static/"))
                return
            app.json_response(self, {"ok": False, "error": "not found"}, 404)

    app.ReadRoutes = ReadRoutes
