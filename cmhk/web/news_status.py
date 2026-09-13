from __future__ import annotations

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def load_strategic_news_run(slot: str) -> dict:
        normalized_slot = str(slot or "").strip()
        if not app.re.fullmatch(r"\d{4}-\d{2}-\d{2}@\d{2}:\d{2}(?:[-A-Za-z0-9_.]+)?", normalized_slot):
            return {}
        path = app.STRATEGIC_BRIEFING_RUNS_DIR / f"{normalized_slot.replace(':', '-')}.json"
        try:
            payload = app.json.loads(path.read_text(encoding="utf-8"))
        except (OSError, app.json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    publish(app, load_strategic_news_run)

    def strategic_news_items_for_crawl_run(run: object) -> list[dict]:
        """Return the published news rows that belong to one archived strategic run."""
        if not isinstance(run, dict) or str(run.get("task_kind") or "") != "strategic-news":
            return []
        summary = run.get("operational_summary")
        slot = str(summary.get("slot") or "") if isinstance(summary, dict) else ""
        payload = app.load_strategic_news_run(slot)
        review_sheet = payload.get("review_sheet")
        raw_items = review_sheet.get("new_items") if isinstance(review_sheet, dict) else []
        if not isinstance(raw_items, list):
            return []
        items: list[dict] = []
        for raw in raw_items[:100]:
            if not isinstance(raw, dict):
                continue
            raw_url = str(raw.get("url") or "").strip()
            parsed_url = app.urlparse(raw_url)
            items.append(
                {
                    "newsId": str(raw.get("news_id") or ""),
                    "title": str(raw.get("title") or ""),
                    "summary": str(raw.get("summary") or ""),
                    "category": str(raw.get("category") or ""),
                    "region": str(raw.get("region") or ""),
                    "source": str(raw.get("source") or ""),
                    "publishedAt": str(raw.get("published_at") or ""),
                    "url": raw_url if parsed_url.scheme in {"http", "https"} else "",
                    "inclusionReason": str(raw.get("inclusion_reason") or ""),
                    "businessImpact": str(raw.get("business_impact") or ""),
                }
            )
        return items

    publish(app, strategic_news_items_for_crawl_run)

    def _strategic_process_item(raw: object) -> dict:
        if not isinstance(raw, dict):
            return {}
        raw_url = str(raw.get("url") or raw.get("source_url") or "").strip()
        parsed_url = app.urlparse(raw_url)
        return {
            "newsId": str(raw.get("news_id") or ""),
            "sourceTitle": str(raw.get("source_title") or raw.get("title") or ""),
            "sourceSummary": str(
                raw.get("source_summary")
                or raw.get("snippet")
                or raw.get("summary")
                or ""
            ),
            "source": str(raw.get("source") or raw.get("source_domain") or ""),
            "url": raw_url if parsed_url.scheme in {"http", "https"} else "",
            "publishedAt": str(raw.get("published_at") or raw.get("source_date") or ""),
            "module": str(raw.get("module") or raw.get("category") or ""),
            "matchedKeywords": str(raw.get("matched_keywords") or raw.get("keywords") or ""),
            "status": str(raw.get("status") or ""),
            "shouldInclude": raw.get("should_include") if isinstance(raw.get("should_include"), bool) else None,
            "aiTitle": str(raw.get("ai_title") or ""),
            "aiSummary": str(raw.get("ai_summary") or ""),
            "category": str(raw.get("category") or ""),
            "region": str(raw.get("region") or ""),
            "decisionPath": str(raw.get("decision_path") or ""),
            "signalType": str(raw.get("signal_type") or ""),
            "businessImpact": str(raw.get("business_impact") or ""),
            "exclusionCode": str(raw.get("exclusion_code") or ""),
            "reason": str(raw.get("reason") or raw.get("inclusion_reason") or ""),
            "duplicateOf": str(raw.get("duplicate_of") or ""),
            "errors": [str(item) for item in raw.get("errors") or []],
            "query": str(raw.get("query") or ""),
            "searchOrigin": str(raw.get("search_origin") or ""),
        }

    publish(app, _strategic_process_item)

    def monitoring_keywords_snapshot(run_id: str = "") -> dict:
        """Read captured keyword inputs without making a live Feishu call on page load."""
        if run_id:
            if not app.re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
                return {}
            path = app.STRATEGIC_BRIEFING_DIR / "monitoring_specs" / f"{run_id}.json"
        else:
            path = app.STRATEGIC_BRIEFING_DIR / "monitoring_keywords_latest.json"
        try:
            payload = app.json.loads(path.read_text(encoding="utf-8"))
        except (OSError, app.json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or (run_id and payload.get("runId") != run_id):
            return {}
        modules = [
            {"name": str(module.get("name") or "未命名模块"),
             "keywords": [str(word) for word in module.get("keywords", []) if isinstance(word, str) and word.strip()]}
            for module in payload.get("modules", [])
            if isinstance(module, dict) and isinstance(module.get("keywords"), list)
        ]
        return {"capturedAt": str(payload.get("capturedAt") or ""),
                "runId": str(payload.get("runId") or ""),
                "sourceUrl": str(payload.get("sourceUrl") or ""),
                "specHash": str(payload.get("specHash") or ""),
                "modules": modules, "keywordCount": sum(len(module["keywords"]) for module in modules)}

    publish(app, monitoring_keywords_snapshot)

    def strategic_news_process_items_for_crawl_run(run: object) -> dict:
        """Expose per-object records for each strategic-news node, not only totals."""
        empty = {"discoveryItems": [], "aiReviewItems": [], "dedupeItems": []}
        if not isinstance(run, dict) or str(run.get("task_kind") or "") != "strategic-news":
            return empty
        summary = run.get("operational_summary")
        slot = str(summary.get("slot") or "") if isinstance(summary, dict) else ""
        payload = app.load_strategic_news_run(slot)
        discovery = payload.get("news_discovery") if isinstance(payload.get("news_discovery"), dict) else {}
        raw_discovery = discovery.get("items") if isinstance(discovery.get("items"), list) else []
        if not raw_discovery:
            latest_path = app.STRATEGIC_BRIEFING_DIR / "news_discovery_latest.json"
            try:
                latest = app.json.loads(latest_path.read_text(encoding="utf-8"))
            except (OSError, app.json.JSONDecodeError):
                latest = {}
            generated_at = str(latest.get("generated_at") or "") if isinstance(latest, dict) else ""
            if slot and generated_at[:16] == slot.replace("@", "T")[:16]:
                raw_discovery = latest.get("items") if isinstance(latest.get("items"), list) else []
        review_sheet = payload.get("review_sheet") if isinstance(payload.get("review_sheet"), dict) else {}
        raw_ai = review_sheet.get("ai_review_items") if isinstance(review_sheet.get("ai_review_items"), list) else []
        if not raw_ai and raw_discovery:
            try:
                from strategic_briefing import reconstruct_ai_review_items

                raw_ai = reconstruct_ai_review_items(raw_discovery)
            except Exception:
                raw_ai = []
        raw_dedupe = review_sheet.get("semantic_review_items") if isinstance(review_sheet.get("semantic_review_items"), list) else []
        return {
            "discoveryItems": [item for raw in raw_discovery[:300] if (item := app._strategic_process_item(raw))],
            "aiReviewItems": [item for raw in raw_ai[:300] if (item := app._strategic_process_item(raw))],
            "dedupeItems": [item for raw in raw_dedupe[:300] if (item := app._strategic_process_item(raw))],
        }

    publish(app, strategic_news_process_items_for_crawl_run)

    def news_selection_items_for_crawl_run(run: object) -> list[dict]:
        """Expose every verified preference-Agent decision for the clickable lineage node."""
        if not isinstance(run, dict) or str(run.get("task_kind") or "") != "news-selection-agent":
            return []
        run_id = str(run.get("crawl_run_id") or "").strip()
        if not app.re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
            return []
        audit_path = app.ROOT / "agent_knowledge" / "news_selection_agent" / "decisions.jsonl"
        latest_records: dict[str, dict] = {}
        try:
            lines = audit_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                record = app.json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("event") != "decision":
                continue
            if str(record.get("agent_run_id") or "") != run_id:
                continue
            news_id = str(record.get("news_id") or "").strip()
            if news_id:
                latest_records[news_id] = record
        items: list[dict] = []
        for record in latest_records.values():
            app_status = str(record.get("app_status") or "未记录")
            weekly_status = str(record.get("weekly_status") or "未记录")
            automated_fields = [str(value) for value in record.get("automated_fields") or []]
            result_parts = []
            if "app" in automated_fields:
                result_parts.append(f"滚动栏{app_status}")
            if "weekly" in automated_fields:
                result_parts.append(f"周报{weekly_status}")
            items.append(
                {
                    "title": str(record.get("title") or record.get("news_id") or "未命名新闻"),
                    "summary": str(record.get("reason") or "本轮未保存判断原因。"),
                    "status": "included" if "接受" in (app_status, weekly_status) else "excluded",
                    "resultLabel": " / ".join(result_parts) or "未修改",
                    "reason": str(record.get("reason") or "本轮未保存判断原因。"),
                    "publishedAt": str(record.get("recorded_at") or ""),
                    "extra": "\n".join(
                        (
                            f"新闻ID：{record.get('news_id') or '未记录'}",
                            f"飞书行号：{record.get('row_number') or '未记录'}",
                            f"滚动栏：{record.get('app_before') or '未记录'} → {app_status}（置信度 {record.get('app_confidence', '—')}）",
                            f"周报：{record.get('weekly_before') or '未记录'} → {weekly_status}（置信度 {record.get('weekly_confidence', '—')}）",
                            f"模型：{record.get('model') or '未记录'}",
                            f"写入身份：{record.get('writer_identity') or '未记录'} · {record.get('writer_profile') or '未记录'}",
                            f"逐格回读：{'通过' if record.get('write_verified') is True else '未通过'}",
                        )
                    ),
                }
            )
        return items[:500]

    publish(app, news_selection_items_for_crawl_run)

    def main_crawl_items_for_crawl_run(run: object) -> list[dict]:
        """Return one auditable detail record per row handled by a main crawl run."""
        if not isinstance(run, dict) or str(run.get("trigger") or "") != "定时爬虫":
            return []
        curation = run.get("curation") if isinstance(run.get("curation"), dict) else {}
        agent_run_id = str(curation.get("agent_run_id") or "").strip()
        if not app.re.fullmatch(r"[A-Za-z0-9_.-]+", agent_run_id):
            return []
        artifact_path = app.ROOT / "curation_data" / "backups" / agent_run_id / "run_log.json"
        try:
            raw_items = app.json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, app.json.JSONDecodeError):
            return []
        if not isinstance(raw_items, list):
            return []
        grouped: dict[int, list[dict]] = {}
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                row_number = int(raw.get("row") or 0)
            except (TypeError, ValueError):
                continue
            if row_number > 0:
                grouped.setdefault(row_number, []).append(raw)
        items: list[dict] = []
        for row_number, row_items in sorted(grouped.items()):
            def fetched_successfully(item: dict) -> bool:
                try:
                    status_code = int(item.get("http_status") or 0)
                except (TypeError, ValueError):
                    status_code = 0
                return 200 <= status_code < 400 and not item.get("error")

            success_items = [item for item in row_items if fetched_successfully(item)]
            failed_items = [item for item in row_items if item not in success_items]
            titles = list(dict.fromkeys(str(item.get("title") or "").strip() for item in row_items if item.get("title")))
            source_types = list(dict.fromkeys(str(item.get("source_type") or "").strip() for item in row_items if item.get("source_type")))
            extracted_fields = list(dict.fromkeys(
                field.strip()
                for item in row_items
                for field in str(item.get("extracted_fields") or "").split(",")
                if field.strip()
            ))
            errors = list(dict.fromkeys(str(item.get("error") or item.get("skip_reason") or "").strip() for item in failed_items if item.get("error") or item.get("skip_reason")))
            urls: list[str] = []
            for item in row_items:
                raw_url = str(item.get("final_url") or item.get("url") or "").strip()
                parsed_url = app.urlparse(raw_url)
                if parsed_url.scheme in {"http", "https"} and raw_url not in urls:
                    urls.append(raw_url)
            row_statuses = {str(item.get("row_status") or "").strip() for item in row_items if item.get("row_status")}
            status = "failed" if not success_items else "partial" if failed_items or any(value not in {"ok", "success"} for value in row_statuses) else "completed"
            items.append(
                {
                    "rowNumber": row_number,
                    "title": f"第 {row_number} 行 · {titles[0] if titles else '未记录页面标题'}",
                    "summary": f"实际抓取 {len(row_items)} 个URL：成功 {len(success_items)}、失败 {len(failed_items)}。",
                    "status": status,
                    "urls": urls[:30],
                    "sourceTypes": source_types,
                    "extractedFields": extracted_fields,
                    "errors": errors,
                    "methodCounts": {
                        method: sum(1 for item in row_items if str(item.get("method") or "未记录") == method)
                        for method in sorted({str(item.get("method") or "未记录") for item in row_items})
                    },
                    "rowStatuses": sorted(row_statuses),
                }
            )
        return items

    publish(app, main_crawl_items_for_crawl_run)

    def fixed_source_summary() -> dict:
        """Describe the current Feishu-backed fixed-source input without conflating it with crawl output."""
        source_path = app.ROOT / "sources.json"
        try:
            rows = app.json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, app.json.JSONDecodeError):
            return {}
        if not isinstance(rows, list):
            return {}
        configured_urls: list[str] = []
        configured_rows = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            configured_rows += 1
            configured_urls.extend(app.crawl.urls_from_sources(str(row.get("sources") or "")))
        unique_urls = list(dict.fromkeys(configured_urls))
        return {
            "configuredRows": configured_rows,
            "configuredUrlOccurrences": len(configured_urls),
            "uniqueUrls": len(unique_urls),
            "source": "飞书爬虫配置表当前快照",
            "updatedAt": app.datetime.fromtimestamp(source_path.stat().st_mtime).astimezone().isoformat(),
        }

    publish(app, fixed_source_summary)

    def build_today_news_rounds(today_key: str = "") -> list[dict]:
        from strategic_briefing import HKT, SCAN_TIMES

        today = app.datetime.now(HKT).strftime("%Y-%m-%d")
        day = str(today_key or "").strip() or today
        if not app.re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            return []
        archives: dict[str, dict] = {}
        for path in app.STRATEGIC_BRIEFING_RUNS_DIR.glob(f"{day}@??-??.json"):
            match = app.re.fullmatch(rf"{app.re.escape(day)}@([0-2]\d)-([0-5]\d)\.json", path.name)
            if not match or int(match.group(1)) > 23:
                continue
            scan_time = f"{match.group(1)}:{match.group(2)}"
            try:
                candidate = app.json.loads(path.read_text(encoding="utf-8"))
            except (OSError, app.json.JSONDecodeError):
                continue
            if (isinstance(candidate, dict) and isinstance(candidate.get("review_sheet"), dict)
                    and candidate.get("slot", f"{day}@{scan_time}") == f"{day}@{scan_time}"):
                archives[scan_time] = candidate
        rounds: list[dict] = []
        used_slots: set[str] = set()
        for configured in SCAN_TIMES:
            scan_time = configured.strftime("%H:%M")
            morning = configured.hour < 12
            label = "上午" if morning else "下午"
            payload = archives.get(scan_time, {})
            # Historical archives retain their original scheduled time. Old 09/15
            # runs must neither replace today's configured slots nor be relabelled.
            if not payload and day < today:
                historical = sorted(t for t in archives if t not in used_slots
                                    and (int(t[:2]) < 12) == morning)
                if historical:
                    scan_time = historical[0]
                    payload = archives[scan_time]
            if not payload:
                continue
            used_slots.add(scan_time)
            review_sheet = payload.get("review_sheet") or {}
            dashboard_summary = payload.get("dashboard_summary") or {}
            news_discovery = payload.get("news_discovery") or {}
            discovered = max(
                0,
                int(
                    dashboard_summary.get("discovered")
                    or news_discovery.get("result_count")
                    or review_sheet.get("input_count")
                    or 0
                ),
            )
            confirmed = max(
                0,
                int(
                    dashboard_summary.get("confirmed")
                    or review_sheet.get("batch_count")
                    or max(0, discovered - int(review_sheet.get("filtered_count") or 0))
                ),
            )
            new_count = max(
                0,
                int(dashboard_summary.get("new_count") or review_sheet.get("new_count") or 0),
            )
            history_duplicates = max(
                0,
                min(
                    confirmed,
                    int(
                        dashboard_summary.get("history_duplicates")
                        or review_sheet.get("semantic_duplicate_count")
                        or 0
                    ),
                ),
            )
            deduplicated = max(0, confirmed - history_duplicates)
            status = str(dashboard_summary.get("status") or "").strip()
            if not status:
                status = "已完成" if payload.get("status") == "completed" else "已归档"
            stages = [
                {
                    "key": "discovered",
                    "label": "检索发现",
                    "value": discovered,
                    "detail": "固定监控与 Agentic Search 汇总的候选新闻。",
                },
                {
                    "key": "confirmed",
                    "label": "AI确认",
                    "value": confirmed,
                    "detail": "AI 结合竞对、政策及战略相关性完成审核。",
                },
                {
                    "key": "deduplicated",
                    "label": "历史去重",
                    "value": deduplicated,
                    "detail": f"与历史记录比对，排除 {history_duplicates} 条重复事件。",
                },
                {
                    "key": "new",
                    "label": "新增入库",
                    "value": new_count,
                    "detail": "已写入飞书、纳入今日信息资产的新增记录。",
                },
            ]
            rounds.append(
                {
                    "key": f"{day}-{scan_time.replace(':', '-')}",
                    "label": label,
                    "time": scan_time,
                    "status": status,
                    "discovered": discovered,
                    "confirmed": confirmed,
                    "historyDuplicates": history_duplicates,
                    "newCount": new_count,
                    "note": str(dashboard_summary.get("note") or "").strip(),
                    "categories": app._group_latest_news_categories(
                        review_sheet.get("new_category_counts")
                    ),
                    "impacts": app._group_latest_news_impacts(review_sheet.get("new_items")),
                    "stages": stages,
                }
            )
        return rounds

    publish(app, build_today_news_rounds)

    def _group_latest_news_categories(raw_counts: object) -> list[dict]:
        if not isinstance(raw_counts, dict):
            return []
        label_map = {
            "基础设施/网络/技术类": "网络与技术",
            "宏观经济&国际形势&地缘政治&其他国际性质关注词汇": "宏观与国际",
            "市场/产品类": "市场与产品",
            "竞争对手": "竞对动态",
        }
        grouped: dict[str, int] = {}
        for raw_label, raw_value in raw_counts.items():
            label = label_map.get(str(raw_label), str(raw_label).strip() or "其他")
            try:
                value = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                value = 0
            if value:
                grouped[label] = grouped.get(label, 0) + value
        label_priority = {
            "竞对动态": 0,
            "政策监管": 1,
            "网络与技术": 2,
            "市场与产品": 3,
            "宏观与国际": 4,
        }
        items = sorted(
            [{"label": label, "value": value} for label, value in grouped.items()],
            key=lambda item: (-item["value"], label_priority.get(item["label"], 99), item["label"]),
        )
        if len(items) <= 4:
            return items
        return items[:3] + [{"label": "其他", "value": sum(item["value"] for item in items[3:])}]

    publish(app, _group_latest_news_categories)

    def _group_latest_news_impacts(new_items: object) -> list[dict]:
        if not isinstance(new_items, list):
            return []
        counts: dict[str, int] = {}
        for item in new_items:
            if not isinstance(item, dict):
                continue
            label = str(item.get("business_impact") or "").strip()
            if label:
                counts[label] = counts.get(label, 0) + 1
        return sorted(
            [{"label": label, "value": value} for label, value in counts.items()],
            key=lambda item: (-item["value"], item["label"]),
        )

    publish(app, _group_latest_news_impacts)

    def build_latest_news_funnel() -> dict:
        for run in app.load_crawl_run_index():
            if str(run.get("task_kind") or "") != "strategic-news":
                continue
            if str(run.get("run_status") or "") != "completed":
                continue
            summary = run.get("operational_summary")
            if not isinstance(summary, dict):
                continue
            discovered = max(0, int(summary.get("discovered") or 0))
            ai_confirmed = max(0, int(summary.get("ai_retained") or 0))
            history_duplicates = max(
                0,
                min(ai_confirmed, int(summary.get("history_duplicates") or 0)),
            )
            new_count = max(0, int(summary.get("new_count") or 0))
            deduplicated = max(0, ai_confirmed - history_duplicates)
            slot = str(summary.get("slot") or "")
            run_payload = app.load_strategic_news_run(slot)
            review_sheet = run_payload.get("review_sheet")
            if not isinstance(review_sheet, dict):
                review_sheet = {}
            categories = app._group_latest_news_categories(review_sheet.get("new_category_counts"))
            impacts = app._group_latest_news_impacts(review_sheet.get("new_items"))
            source_count = max(0, int(review_sheet.get("new_source_count") or 0))
            slot_match = app.re.match(
                r"^(\d{4})-(\d{2})-(\d{2})@(\d{2}:\d{2})",
                slot,
            )
            slot_label = (
                f"{int(slot_match.group(2))}月{int(slot_match.group(3))}日 {slot_match.group(4)}"
                if slot_match
                else ""
            )
            return {
                "scope": str(run.get("scope") or ""),
                "label": slot_label,
                "completedAt": str(run.get("completed_at_hkt") or ""),
                "historyDuplicates": history_duplicates,
                "summary": {
                    "discovered": discovered,
                    "confirmed": ai_confirmed,
                    "newCount": new_count,
                    "sourceCount": source_count,
                },
                "categories": categories,
                "impacts": impacts,
                "stages": [
                    {
                        "key": "discovered",
                        "label": "检索发现",
                        "value": discovered,
                        "removed": 0,
                        "rate": 100,
                        "note": "候选池",
                        "detail": (
                            "固定页面、正式关键词、定时页面线索与 Agentic 补缺搜索合并后，"
                            f"在本轮时间窗内共得到 {discovered} 条候选。"
                        ),
                    },
                    {
                        "key": "confirmed",
                        "label": "AI确认",
                        "value": ai_confirmed,
                        "removed": max(0, discovered - ai_confirmed),
                        "rate": round(ai_confirmed / discovered * 100) if discovered else 0,
                        "note": (
                            f"保留 {round(ai_confirmed / discovered * 100)}%"
                            if discovered
                            else "等待审核"
                        ),
                        "detail": (
                            "AI逐条判断竞对或战略相关性、具体事件、发布时间及来源证据；"
                            f"确认 {ai_confirmed} 条，未确认 {max(0, discovered - ai_confirmed)} 条。"
                        ),
                    },
                    {
                        "key": "deduplicated",
                        "label": "历史去重",
                        "value": deduplicated,
                        "removed": history_duplicates,
                        "rate": round(deduplicated / ai_confirmed * 100) if ai_confirmed else 0,
                        "note": f"排除 {history_duplicates} 条",
                        "detail": (
                            "对全部飞书历史记录执行事件级语义去重；"
                            f"识别并排除 {history_duplicates} 条重复事件，剩余 {deduplicated} 条。"
                        ),
                    },
                    {
                        "key": "new",
                        "label": "本轮新增",
                        "value": new_count,
                        "removed": max(0, deduplicated - new_count),
                        "rate": round(new_count / deduplicated * 100) if deduplicated else 0,
                        "note": "已写入飞书",
                        "detail": (
                            f"最终 {new_count} 条完成飞书写入和逐格回读，"
                            "全部归档成功后才发送群通知。"
                        ),
                    },
                ],
            }
        return {
            "scope": "",
            "label": "",
            "completedAt": "",
            "historyDuplicates": 0,
            "summary": {},
            "categories": [],
            "impacts": [],
            "stages": [],
        }

    publish(app, build_latest_news_funnel)
