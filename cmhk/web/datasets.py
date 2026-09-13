from __future__ import annotations

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def settings_rows() -> list[dict]:
        rows = []
        for source_row in app.crawl.parse_latest_sheet():
            row_no = str(source_row["row"])
            available_entities = list(dict.fromkeys(source_row.get("entities") or []))
            available_fields = list(dict.fromkeys(app.row_fields(int(row_no))))
            rows.append(
                {
                    "row": row_no,
                    "block": source_row.get("block", ""),
                    "object": source_row.get("object", ""),
                    "package": source_row.get("package", ""),
                    "need": source_row.get("need", ""),
                    "sources": source_row.get("sources", ""),
                    "entities": available_entities,
                    "fields": available_fields,
                    "enabled": True,
                    "selectedEntities": available_entities,
                    "selectedFields": available_fields,
                }
            )
        return rows

    publish(app, settings_rows)

    def build_settings_payload() -> dict:
        rows = app.settings_rows()
        enabled = [row for row in rows if row["enabled"]]
        return {
            "source": "飞书主表",
            "rows": rows,
            "summary": {
                "totalRows": len(rows),
                "enabledRows": len(enabled),
                "selectedEntities": sum(len(row["selectedEntities"]) for row in enabled),
                "selectedFields": sum(len(row["selectedFields"]) for row in enabled),
            },
        }

    publish(app, build_settings_payload)

    def load_curation_status() -> dict:
        if not app.CURATION_LATEST_PATH.exists():
            return {}
        try:
            payload = app.json.loads(app.CURATION_LATEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    publish(app, load_curation_status)

    def build_curation_rejection_visuals() -> dict:
        status = app.load_curation_status()
        accepted = int(status.get("accepted") or 0)
        reported_rejected = int(status.get("rejected") or 0)
        quality_rejected = 0
        evidence_gaps = 0
        review = int(status.get("review") or 0)
        reasons: dict[str, int] = {}
        if app.CURATION_CANDIDATE_FACTS_PATH.exists():
            try:
                for line in app.CURATION_CANDIDATE_FACTS_PATH.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    item = app.json.loads(line)
                    if item.get("decision") != "rejected":
                        continue
                    if item.get("status") != "ok":
                        evidence_gaps += 1
                        continue
                    quality_rejected += 1
                    for reason in item.get("reasons") or []:
                        reason_text = str(reason or "").strip()
                        if reason_text:
                            reasons[reason_text] = reasons.get(reason_text, 0) + 1
            except Exception:
                reasons = {}
        if quality_rejected + evidence_gaps == 0 and reported_rejected:
            quality_rejected = reported_rejected
        quality_total = accepted + quality_rejected + review
        total = accepted + reported_rejected + review
        top_reasons = sorted(
            [{"label": key, "value": value} for key, value in reasons.items()],
            key=lambda item: item["value"],
            reverse=True,
        )[:6]
        return {
            "accepted": accepted,
            "rejected": quality_rejected,
            "qualityRejected": quality_rejected,
            "evidenceGaps": evidence_gaps,
            "reportedRejected": reported_rejected,
            "review": review,
            "total": total,
            "qualityTotal": quality_total,
            "rejectRate": round((quality_rejected / quality_total) * 100) if quality_total else 0,
            "passRate": round((accepted / quality_total) * 100) if quality_total else 0,
            "reasons": top_reasons,
            "runId": status.get("run_id", ""),
            "completedAt": status.get("completed_at", ""),
        }

    publish(app, build_curation_rejection_visuals)

    def build_crawl_result_visuals() -> dict:
        run_log_path = app.ROOT / "run_log.json"
        if not run_log_path.exists():
            return {
                "success": 0,
                "failed": 0,
                "fallback": 0,
                "total": 0,
                "successRate": 0,
                "completedAt": "",
            }
        try:
            rows = app.json.loads(run_log_path.read_text(encoding="utf-8"))
        except Exception:
            rows = []
        if not isinstance(rows, list):
            rows = []

        success = 0
        failed = 0
        fallback = 0
        for item in rows:
            if not isinstance(item, dict):
                continue
            status = int(item.get("http_status") or 0)
            used_fallback = str(item.get("evidence_fallback_used") or "").lower() in {
                "1",
                "true",
                "yes",
            }
            if used_fallback:
                fallback += 1
                failed += 1
            elif 200 <= status < 400:
                success += 1
            else:
                failed += 1
        total = success + failed
        return {
            "success": success,
            "failed": failed,
            "fallback": fallback,
            "total": total,
            "successRate": round((success / total) * 100) if total else 0,
            "completedAt": app.time.strftime(
                "%Y-%m-%d %H:%M:%S",
                app.time.localtime(run_log_path.stat().st_mtime),
            ),
        }

    publish(app, build_crawl_result_visuals)

    def load_agent_trace(limit: int = 300) -> list[dict]:
        if not app.CURATION_AGENT_TRACE_PATH.exists():
            return []
        rows: list[dict] = []
        try:
            lines = app.CURATION_AGENT_TRACE_PATH.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                item = app.json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    publish(app, load_agent_trace)

    def load_agent_research_for_run(run_id: str) -> tuple[list[dict], list[dict]]:
        """Load the real per-company worker trace and reports for one curation run."""
        safe_run_id = app.re.sub(r"[^A-Za-z0-9_.-]", "", str(run_id or ""))
        if not safe_run_id:
            return [], []
        run_dir = app.ROOT / "curation_data" / "runs"
        trace_path = run_dir / f"{safe_run_id}_agent_trace.jsonl"
        report_path = run_dir / f"{safe_run_id}_company_agent_results.json"
        traces: list[dict] = []
        if trace_path.exists():
            try:
                for line in trace_path.read_text(encoding="utf-8").splitlines():
                    item = app.json.loads(line)
                    if isinstance(item, dict) and item.get("role") in {"lead_research", "company_research"}:
                        traces.append(item)
            except Exception:
                traces = []
        reports: list[dict] = []
        if report_path.exists():
            try:
                payload = app.json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    reports = [item for item in payload if isinstance(item, dict)]
            except Exception:
                reports = []
        if not reports:
            progress = app.load_company_agent_progress_for_run(safe_run_id)
            reports = progress.get("reports", []) if progress.get("ok") else []
        return traces, reports

    publish(app, load_agent_research_for_run)

    def load_company_agent_progress_for_run(run_id: str) -> dict:
        """Expose the latest durable company-Agent checkpoint before final publication."""
        safe_run_id = app.re.sub(r"[^A-Za-z0-9_.-]", "", str(run_id or ""))
        if not safe_run_id:
            return {"ok": False, "reports": []}
        progress_path = app.ROOT / "curation_data" / "runs" / f"{safe_run_id}_company_agent_progress.json"
        if not progress_path.exists():
            return {"ok": False, "reports": []}
        try:
            payload = app.json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            return {"ok": False, "reports": []}
        companies = payload.get("companies") if isinstance(payload, dict) else {}
        if not isinstance(companies, dict):
            companies = {}
        reports = sorted(
            (item for item in companies.values() if isinstance(item, dict)),
            key=lambda item: (int(item.get("row_number") or 10_000), str(item.get("company") or "")),
        )
        terminal_statuses = {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted"}
        metric_rows = [
            metric
            for report in reports
            for metric in (report.get("metric_results") or [])
            if isinstance(metric, dict)
        ]
        return {
            "ok": True,
            "source": "checkpoint",
            "version": int(payload.get("version") or 0),
            "updatedAt": str(payload.get("updated_at") or ""),
            "expectedCompanies": 41,
            "recordedCompanies": len(reports),
            "terminalCompanies": sum(1 for report in reports if report.get("status") in terminal_statuses),
            "unresolvedCompanies": sum(1 for report in reports if report.get("status") not in terminal_statuses),
            "recordedMetrics": len(metric_rows),
            "terminalMetrics": sum(1 for metric in metric_rows if metric.get("status") in terminal_statuses),
            "conflictMetrics": sum(1 for metric in metric_rows if metric.get("status") == "conflict"),
            "agentErrorMetrics": sum(1 for metric in metric_rows if metric.get("status") == "agent_error"),
            "reports": reports,
        }

    publish(app, load_company_agent_progress_for_run)

    def safe_dataset_slug(value: str) -> str:
        stem = app.Path(value or "upload").stem or "upload"
        slug = app.re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "-", stem).strip("-._")
        return slug[:48] or "upload"

    publish(app, safe_dataset_slug)

    def clean_upload_text(value: object, limit: int = 500) -> str:
        return app.re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    publish(app, clean_upload_text)

    def split_upload_tags(value: object, limit: int = 12) -> list[str]:
        tags: list[str] = []
        for part in app.re.split(r"[,，;；\n]+", str(value or "")):
            tag = app.clean_upload_text(part, 32)
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= limit:
                break
        return tags

    publish(app, split_upload_tags)

    def write_uploaded_knowledge_dataset(payload: dict) -> dict:
        filename = str(payload.get("filename") or "").strip()
        encoded = str(payload.get("contentBase64") or "").strip()
        title = app.clean_upload_text(payload.get("title"), 80)
        summary = app.clean_upload_text(payload.get("summary"), 600)
        scope = app.clean_upload_text(payload.get("scope"), 600)
        source_type = app.clean_upload_text(payload.get("sourceType") or payload.get("source_type"), 40) or "user_uploaded_file"
        quality_note = app.clean_upload_text(payload.get("quality"), 600)
        user_tags = app.split_upload_tags(payload.get("tags"))
        if not filename:
            raise ValueError("缺少文件名")
        if not title:
            raise ValueError("请填写知识库名称")
        if not summary:
            raise ValueError("请填写知识库说明")
        suffix = app.Path(filename).suffix.lower()
        if suffix not in app.UPLOAD_ALLOWED_SUFFIXES:
            raise ValueError("暂不支持该文件类型；请上传 txt、md、csv、tsv、json、docx 或 pdf。")
        if not encoded:
            raise ValueError("上传文件内容为空")
        try:
            raw = app.base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError(f"文件内容解码失败：{exc}") from exc
        if not raw:
            raise ValueError("上传文件内容为空")
        if len(raw) > app.UPLOAD_MAX_BYTES:
            raise ValueError("文件过大，当前单文件上限为 8MB。")

        now = app.datetime.now().astimezone()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        slug = app.safe_dataset_slug(title or filename)
        dataset_id = f"{app.UPLOAD_DATASET_PREFIX}-{timestamp}-{slug}"
        folder = app.ROOT / "agent_knowledge" / dataset_id
        folder.mkdir(parents=True, exist_ok=False)

        original_name = f"original{suffix}"
        original_path = folder / original_name
        original_path.write_bytes(raw)

        extracted_text = app.read_display_text(original_path).strip()
        if not extracted_text:
            extracted_text = app.decode_text_bytes(raw).strip()
        if not extracted_text:
            raise ValueError("文件已保存但未能提取可检索文本，请换用文本、CSV、JSON、Word 或可复制文字的 PDF。")

        knowledge_path = folder / "uploaded_knowledge.md"
        knowledge_path.write_text(
            "\n".join(
                [
                    f"# {title}",
                    "",
                    f"- 上传时间：{now.isoformat(timespec='seconds')}",
                    f"- 原始文件：{original_name}",
                    f"- 文件大小：{len(raw)} bytes",
                    f"- 知识库说明：{summary}",
                    f"- 范围/口径：{scope or '用户未填写'}",
                    f"- 来源类型：{source_type}",
                    f"- 标签：{', '.join(user_tags) if user_tags else '用户未填写'}",
                    f"- 质量备注：{quality_note or '用户未填写'}",
                    "",
                    "## 可检索正文",
                    "",
                    extracted_text[:300000],
                ]
            ),
            encoding="utf-8",
        )
        readme_path = folder / "README.md"
        readme_path.write_text(
            "\n".join(
                [
                    f"# {title}",
                    "",
                    "该数据集由前端上传文件生成。只有用户在数据库按钮中选中本数据集时，后端才会把它发送给小竞AI检索。",
                    "",
                    f"- 数据集 id：`{dataset_id}`",
                    f"- 说明：{summary}",
                    f"- 范围/口径：{scope or '用户未填写'}",
                    f"- 来源类型：{source_type}",
                    f"- 标签：{', '.join(user_tags) if user_tags else '用户未填写'}",
                    f"- 质量备注：{quality_note or '用户未填写'}",
                    f"- 原始文件：`{original_name}`",
                    "- 检索入口：`uploaded_knowledge.md`",
                ]
            ),
            encoding="utf-8",
        )
        manifest = {
            "id": dataset_id,
            "title": title,
            "summary": summary,
            "source_type": source_type,
            "scope": scope or "用户手动上传给小竞AI的知识库文件",
            "tags": ["user-upload", "knowledge-base", *user_tags],
            "keywords": [title, app.Path(filename).stem, filename, summary, *user_tags, "用户上传", "知识库"],
            "entrypoints": ["README.md", "uploaded_knowledge.md"],
            "updated_at": now.isoformat(timespec="seconds"),
            "quality": quality_note or "user_uploaded_unverified; visible to AI only when selected in the database picker",
            "original_file": original_name,
        }
        (folder / "manifest.json").write_text(app.json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        dataset = next((item for item in app.list_knowledge_datasets() if item.get("id") == dataset_id), manifest)
        return {"dataset": dataset, "folder": folder.relative_to(app.ROOT).as_posix()}

    publish(app, write_uploaded_knowledge_dataset)

    def _curation_quality_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return app.json.dumps(value, ensure_ascii=False)
        return str(value)

    publish(app, _curation_quality_text)

    def load_curation_quality_records(run_id: str) -> dict:
        run_id = str(run_id or "").strip()
        if not 8 <= len(run_id) <= 80 or any(
            not (character.isalnum() or character in "_-") for character in run_id
        ):
            return {"ok": False, "error": "无效的审核运行编号。", "runId": run_id}

        snapshot_path = app.ROOT / "curation_data" / "runs" / f"{run_id}_candidate_facts.jsonl"
        source_path = snapshot_path
        source_kind = "run-snapshot"

        if not source_path.exists():
            latest_run_id = ""
            try:
                latest_payload = app.json.loads(app.CURATION_LATEST_PATH.read_text(encoding="utf-8"))
                latest_run_id = str(latest_payload.get("run_id") or "")
            except (OSError, ValueError, TypeError):
                latest_run_id = ""
            if latest_run_id == run_id and app.CURATION_CANDIDATE_FACTS_PATH.exists():
                source_path = app.CURATION_CANDIDATE_FACTS_PATH
                source_kind = "current-run"
            else:
                return {
                    "ok": False,
                    "pending": True,
                    "error": "本轮逐条质量明细尚未生成；质量审计完成后会自动出现。",
                    "runId": run_id,
                    "records": [],
                }

        records: list[dict] = []
        try:
            with source_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    item = app.json.loads(raw_line)
                    if not isinstance(item, dict):
                        continue

                    raw_sources = item.get("sources")
                    sources: list[dict] = []
                    if isinstance(raw_sources, list):
                        for source in raw_sources:
                            if isinstance(source, dict):
                                url = app._curation_quality_text(
                                    source.get("url")
                                    or source.get("source_url")
                                    or source.get("href")
                                    or source.get("link")
                                )
                                title = app._curation_quality_text(
                                    source.get("title")
                                    or source.get("name")
                                    or source.get("source")
                                )
                                source_type = app._curation_quality_text(
                                    source.get("type")
                                    or source.get("source_type")
                                    or source.get("tier")
                                )
                                sources.append({"url": url, "title": title, "type": source_type})
                            else:
                                sources.append({"url": app._curation_quality_text(source), "title": "", "type": ""})

                    verification = item.get("search_verification")
                    if not isinstance(verification, dict):
                        verification = {}
                    online_search = verification.get("online_search")
                    if not isinstance(online_search, dict):
                        online_search = {}

                    raw_votes = verification.get("votes")
                    raw_conflicts = verification.get("conflicts")
                    verification_summary = {
                        "status": app._curation_quality_text(verification.get("status")),
                        "decision": app._curation_quality_text(verification.get("decision")),
                        "vote_count": int(verification.get("vote_count") or (len(raw_votes) if isinstance(raw_votes, list) else 0)),
                        "majority_count": int(verification.get("majority_count") or 0),
                        "majority_source_types": verification.get("majority_source_types") or [],
                        "conflict_count": int(verification.get("conflict_count") or (len(raw_conflicts) if isinstance(raw_conflicts, list) else 0)),
                        "online_search": {
                            "enabled": bool(online_search.get("enabled")),
                            "provider": app._curation_quality_text(online_search.get("provider")),
                            "result_count": int(online_search.get("result_count") or 0),
                            "duration_ms": int(online_search.get("duration_ms") or 0),
                            "query": app._curation_quality_text(online_search.get("query")),
                        },
                    }

                    reasons = item.get("reasons")
                    if not isinstance(reasons, list):
                        reasons = [reasons] if reasons else []

                    records.append(
                        {
                            "id": app._curation_quality_text(item.get("id")),
                            "company": app._curation_quality_text(item.get("company")),
                            "metric": app._curation_quality_text(item.get("metric")),
                            "value": app._curation_quality_text(item.get("value")),
                            "basis": app._curation_quality_text(item.get("basis")),
                            "note": app._curation_quality_text(item.get("note")),
                            "status": app._curation_quality_text(item.get("status")),
                            "entity_supported": bool(item.get("entity_supported")),
                            "metric_supported": bool(item.get("metric_supported")),
                            "value_supported": bool(item.get("value_supported")),
                            "confidence": item.get("confidence"),
                            "source_score": item.get("source_score"),
                            "source_tier": app._curation_quality_text(item.get("source_tier")),
                            "row_ref": item.get("row_ref"),
                            "sources": sources,
                            "quality_score": item.get("quality_score"),
                            "decision": app._curation_quality_text(item.get("decision")),
                            "reasons": [app._curation_quality_text(reason) for reason in reasons if reason is not None],
                            "search_verification": verification_summary,
                        }
                    )
        except (OSError, ValueError, TypeError) as exc:
            return {"ok": False, "error": f"逐条质量明细读取失败：{exc}", "runId": run_id}

        decisions: dict[str, int] = {}
        source_tiers: dict[str, int] = {}
        quality_values: list[float] = []
        for record in records:
            decision = record.get("decision") or "unknown"
            decisions[decision] = decisions.get(decision, 0) + 1
            source_tier = record.get("source_tier") or "unknown"
            source_tiers[source_tier] = source_tiers.get(source_tier, 0) + 1
            try:
                quality_values.append(float(record.get("quality_score")))
            except (TypeError, ValueError):
                pass

        return {
            "ok": True,
            "runId": run_id,
            "source": source_kind,
            "records": records,
            "summary": {
                "total": len(records),
                "decisions": decisions,
                "sourceTiers": source_tiers,
                "averageQuality": round(sum(quality_values) / len(quality_values), 4) if quality_values else None,
            },
        }

    publish(app, load_curation_quality_records)

