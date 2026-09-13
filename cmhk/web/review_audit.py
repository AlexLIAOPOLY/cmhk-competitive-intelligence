from __future__ import annotations

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def _iso_timestamp(value: object) -> float | None:
        try:
            return app.datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return None

    publish(app, _iso_timestamp)

    def _news_auto_screening_decisions() -> list[dict]:
        """Load verified per-cell decisions written by the automatic screening Agent."""
        try:
            lines = app.NEWS_SELECTION_DECISIONS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        decisions: list[dict] = []
        for line in lines:
            try:
                record = app.json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                not isinstance(record, dict)
                or record.get("event") != "decision"
                or record.get("write_verified") is not True
                or not record.get("agent_run_id")
            ):
                continue
            try:
                row_number = int(record.get("row_number") or 0)
            except (TypeError, ValueError):
                continue
            recorded_at = app._iso_timestamp(record.get("recorded_at"))
            if row_number < 2 or recorded_at is None:
                continue
            automated_fields = {str(value) for value in record.get("automated_fields") or []}
            for field_key, field_label, before_key, after_key in (
                ("app", "纳入滚动栏", "app_before", "app_status"),
                ("weekly", "纳入周报", "weekly_before", "weekly_status"),
            ):
                if field_key not in automated_fields:
                    continue
                idempotency_key = str(record.get("idempotency_key") or "").strip()
                news_id = str(record.get("news_id") or "").strip()
                if idempotency_key and news_id:
                    automation_event_key = "|".join((
                        idempotency_key,
                        news_id,
                        field_label,
                        str(record.get(after_key) or ""),
                    ))
                else:
                    # Legacy decision records predate the crawl-slot/news-id key.
                    automation_event_key = "|".join((
                        str(record.get("agent_run_id") or ""),
                        str(row_number),
                        field_label,
                        str(record.get(after_key) or ""),
                    ))
                decisions.append({
                    "news_id": news_id,
                    "row_number": row_number,
                    "title": str(record.get("title") or "").strip(),
                    "field": field_label,
                    "before": str(record.get(before_key) or ""),
                    "after": str(record.get(after_key) or ""),
                    "recorded_at": recorded_at,
                    "recorded_at_iso": str(record.get("recorded_at") or ""),
                    "agent_run_id": str(record.get("agent_run_id") or ""),
                    "model": str(record.get("model") or ""),
                    "writer_profile": str(record.get("writer_profile") or ""),
                    "writer_identity": str(record.get("writer_identity") or ""),
                    "remediation": str(record.get("remediation") or ""),
                    "automation_event_key": automation_event_key,
                })
        return decisions

    publish(app, _news_auto_screening_decisions)

    def _news_auto_screening_match(
        *,
        row_number: int,
        title: str,
        field: str,
        before: str,
        after: str,
        event_at: object,
        decisions: list[dict] | None = None,
    ) -> dict | None:
        """Match one sheet change to a verified Agent write without borrowing a human editor."""
        event_timestamp = app._iso_timestamp(event_at)
        if event_timestamp is None:
            return None
        normalized_title = str(title or "").strip()
        matches: list[tuple[int, float, dict]] = []
        for decision in decisions if decisions is not None else app._news_auto_screening_decisions():
            if (
                int(decision.get("row_number") or 0) != row_number
                or app._news_review_field_label(decision.get("field")) != app._news_review_field_label(field)
                or str(decision.get("after") or "") != after
            ):
                continue
            decision_title = str(decision.get("title") or "").strip()
            if normalized_title and decision_title and not (
                normalized_title.startswith(decision_title[:200])
                or decision_title.startswith(normalized_title[:200])
            ):
                continue
            recorded_at = float(decision.get("recorded_at") or 0)
            delay_seconds = event_timestamp - recorded_at
            if delay_seconds < 0 or delay_seconds > 1800:
                continue
            exact_before = int(str(decision.get("before") or "") == before)
            # Remediation writes may replace a legacy Agent value (for example 暂缓)
            # rather than the stale original "before" captured in the decision row.
            if not exact_before and str(decision.get("writer_identity") or "") != "bot":
                continue
            matches.append((exact_before, recorded_at, decision))
        if not matches:
            return None
        return max(matches, key=lambda item: (item[0], item[1]))[2]

    publish(app, _news_auto_screening_match)

    def repair_news_auto_screening_audit() -> int:
        """Correct legacy footprints that assigned verified robot writes to a human."""
        path = app.AUTH.operation_audit_path
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        decisions = app._news_auto_screening_decisions()
        if not decisions:
            return 0
        corrected = 0
        output_lines: list[str] = []
        for raw_line in raw_lines:
            try:
                event = app.json.loads(raw_line)
            except (TypeError, ValueError):
                output_lines.append(raw_line)
                continue
            details = event.get("details") if isinstance(event, dict) and isinstance(event.get("details"), dict) else {}
            try:
                row_number = int(details.get("sheet_row") or 0)
            except (TypeError, ValueError):
                row_number = 0
            match = None
            if (
                isinstance(event, dict)
                and event.get("action") == "news_review.update"
                and event.get("result") == "success"
                and str(event.get("actor_id") or "") != app.NEWS_AUTO_SCREENING_ACTOR["id"]
            ):
                match = app._news_auto_screening_match(
                    row_number=row_number,
                    title=str(details.get("target_label") or event.get("target_label") or ""),
                    field=str(details.get("field") or ""),
                    before=str(details.get("before") or ""),
                    after=str(details.get("after") or ""),
                    event_at=event.get("at"),
                    decisions=decisions,
                )
            if match:
                event["actor_id"] = app.NEWS_AUTO_SCREENING_ACTOR["id"]
                event["actor_open_id"] = ""
                event["actor_name"] = app.NEWS_AUTO_SCREENING_ACTOR["name"]
                event["actor_avatar_url"] = ""
                event["actor_role"] = app.NEWS_AUTO_SCREENING_ACTOR["role"]
                details.update({
                    "source_label": "新闻自动初筛",
                    "identity_note": "由新闻自动初筛机器人写入；已按行号、标题、字段、状态和时间窗口与 Agent 决策审计核验",
                    "agent_run_id": str(match.get("agent_run_id") or ""),
                    "agent_recorded_at": str(match.get("recorded_at_iso") or ""),
                    "model": str(match.get("model") or ""),
                    "writer_profile": str(match.get("writer_profile") or ""),
                    "identity_corrected": True,
                })
                event["details"] = details
                corrected += 1
            output_lines.append(app.json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        if not corrected:
            return 0
        backup_path = path.with_name(f"{path.name}.before-news-auto-screening-identity-repair")
        if not backup_path.exists():
            backup_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
            app.os.chmod(backup_path, 0o600)
        temp_path = path.with_name(f".{path.name}.news-auto-screening.tmp")
        temp_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        app.os.chmod(temp_path, 0o600)
        temp_path.replace(path)
        return corrected

    publish(app, repair_news_auto_screening_audit)

    def backfill_news_auto_screening_audit() -> int:
        """Backfill verified historical robot writes that predate direct audit capture."""
        decisions = app._news_auto_screening_decisions()
        if not decisions:
            return 0
        existing_keys: set[str] = set()
        for event in app.AUTH.operation_audit(limit=None):
            if not isinstance(event, dict) or event.get("action") != "news_review.update":
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            explicit_key = str(details.get("automation_event_key") or "")
            if explicit_key:
                existing_keys.add(explicit_key)
            if str(event.get("actor_id") or "") == app.NEWS_AUTO_SCREENING_ACTOR["id"]:
                try:
                    row_number = int(details.get("sheet_row") or 0)
                except (TypeError, ValueError):
                    row_number = 0
                if details.get("agent_run_id") and row_number >= 2:
                    existing_keys.add("|".join((
                        str(details.get("agent_run_id") or ""),
                        str(row_number),
                        app._news_review_field_label(details.get("field")),
                        str(details.get("after") or ""),
                    )))
        audit_state = app.AUTH._read(app.NEWS_REVIEW_AUDIT_STATE_PATH, {})
        sheet_id = str(
            audit_state.get("sheet_id") if isinstance(audit_state, dict) else ""
        ) or "news-review-sheet"
        written = 0
        for decision in decisions:
            event_key = str(decision.get("automation_event_key") or "")
            if not event_key or event_key in existing_keys:
                continue
            row_number = int(decision.get("row_number") or 0)
            app.AUTH.record_operation(
                actor=app.NEWS_AUTO_SCREENING_ACTOR,
                action="news_review.update",
                target=sheet_id,
                source="feishu_sheet",
                details={
                    "source_label": "新闻自动初筛",
                    "target_label": str(decision.get("title") or "")[:500],
                    "news_id": str(decision.get("news_id") or "")[:120],
                    "sheet_row": row_number,
                    "decision_rows": [row_number],
                    "field": str(decision.get("field") or ""),
                    "before": str(decision.get("before") or ""),
                    "after": str(decision.get("after") or ""),
                    "identity_note": "历史机器人写入已有逐格回读证据；启动时补入统一操作审计",
                    "agent_run_id": str(decision.get("agent_run_id") or ""),
                    "agent_recorded_at": str(decision.get("recorded_at_iso") or ""),
                    "model": str(decision.get("model") or ""),
                    "writer_profile": str(decision.get("writer_profile") or ""),
                    "automation_event_key": event_key,
                    "historical_backfill": True,
                },
            )
            existing_keys.add(event_key)
            written += 1
        return written

    publish(app, backfill_news_auto_screening_audit)

    def _news_review_changeset_cell_evidence(
        *,
        sheet_id: str,
        previous_revision: int,
        current_revision: int,
        pending_cells: set[tuple[int, int]],
    ) -> dict[tuple[int, int], dict]:
        """Resolve the latest exact Feishu changeset touching each changed B/C cell."""
        if (
            not pending_cells
            or previous_revision <= 0
            or current_revision <= previous_revision
        ):
            return {}
        from cmhk.intelligence.news_review_sheet import review_sheet_changesets

        evidence: dict[tuple[int, int], dict] = {}
        lower_revision = max(
            previous_revision + 1,
            current_revision - app.NEWS_REVIEW_CHANGESET_MAX_REVISIONS + 1,
        )
        end_revision = current_revision
        while end_revision >= lower_revision and len(evidence) < len(pending_cells):
            start_revision = max(lower_revision, end_revision - 19)
            try:
                changesets = review_sheet_changesets(start_revision, end_revision)
            except Exception as exc:
                app.logging.warning(
                    "飞书审核表 changeset 归因暂时不可用（%s-%s）：%s",
                    start_revision,
                    end_revision,
                    exc,
                )
                return {}
            for changeset in sorted(
                changesets,
                key=lambda item: int(item.get("revision") or 0),
                reverse=True,
            ):
                try:
                    revision = int(changeset.get("revision") or 0)
                except (TypeError, ValueError):
                    revision = 0
                for action in changeset.get("actions") or []:
                    if not isinstance(action, dict) or str(action.get("sheet_id") or "") != sheet_id:
                        continue
                    if str(action.get("action") or "") not in {"setCell", "setRangeValues"}:
                        continue
                    target = action.get("target") if isinstance(action.get("target"), dict) else {}
                    try:
                        first_row = int(target.get("row")) + 1
                        first_column = int(target.get("col"))
                        row_count = max(1, int(target.get("row_count") or 1))
                        column_count = max(1, int(target.get("col_count") or 1))
                    except (TypeError, ValueError):
                        continue
                    for row_number in range(first_row, first_row + row_count):
                        for column_index in range(first_column, first_column + column_count):
                            cell = (row_number, column_index)
                            if cell not in pending_cells:
                                continue
                            evidence.setdefault(cell, {
                                "is_ai_edit": changeset.get("is_ai_edit"),
                                "is_self_edit": changeset.get("is_self_edit") is True,
                                "revision": revision,
                                "create_time": str(changeset.get("create_time") or ""),
                                "action": str(action.get("action") or ""),
                            })
            end_revision = start_revision - 1
        return evidence

    publish(app, _news_review_changeset_cell_evidence)

    def sync_news_review_sheet_audit(
        snapshot: dict,
        *,
        ignored_changes: list[dict] | None = None,
    ) -> list[dict]:
        """Mirror direct Feishu review decisions into the administrator footprint."""
        headers = snapshot.get("headers") if isinstance(snapshot.get("headers"), list) else []
        sheet_id = str(snapshot.get("sheetId") or "news-review-sheet")
        ignored: set[tuple[int, int, str, str]] = set()
        for item in ignored_changes or []:
            if not isinstance(item, dict):
                continue
            try:
                column_index = int(item.get("columnIndex", -1))
                row_number = int(item.get("rowNumber") or 0)
            except (TypeError, ValueError):
                continue
            if column_index in app.NEWS_REVIEW_DECISION_COLUMNS and row_number >= 2:
                ignored.add((
                    row_number,
                    column_index,
                    str(item.get("before") or ""),
                    str(item.get("value") or ""),
                ))

        current_rows: dict[str, dict] = {}
        for row in snapshot.get("rows") or []:
            if not isinstance(row, dict):
                continue
            storage_source = str(row.get("storageSource") or "")
            if row.get("readOnly") is True or (
                storage_source and storage_source != "feishu"
            ):
                continue
            try:
                row_number = int(row.get("rowNumber") or 0)
            except (TypeError, ValueError):
                continue
            values = row.get("values") if isinstance(row.get("values"), list) else []
            if row_number < 2 or len(values) <= app.NEWS_REVIEW_WEEKLY_STATUS_COLUMN:
                continue
            current_rows[str(row_number)] = {
                "title": str(
                    values[app.NEWS_REVIEW_TITLE_COLUMN]
                    if len(values) > app.NEWS_REVIEW_TITLE_COLUMN
                    else ""
                )[:500],
                "record_id": str(row.get("recordId") or "")[:120],
                "decisions": [
                    str(values[app.NEWS_REVIEW_APP_STATUS_COLUMN] or ""),
                    str(values[app.NEWS_REVIEW_WEEKLY_STATUS_COLUMN] or ""),
                ],
            }

        events: list[dict] = []
        with app.NEWS_REVIEW_AUDIT_LOCK:
            previous = app.AUTH._read(app.NEWS_REVIEW_AUDIT_STATE_PATH, {})
            previous_rows = previous.get("rows") if isinstance(previous, dict) else {}
            same_sheet = str(previous.get("sheet_id") or "") == sheet_id if isinstance(previous, dict) else False
            try:
                previous_revision = int(previous.get("spreadsheet_revision") or 0)
            except (AttributeError, TypeError, ValueError):
                previous_revision = 0
            try:
                current_revision = int(snapshot.get("spreadsheetRevision") or 0)
            except (AttributeError, TypeError, ValueError):
                current_revision = 0
            try:
                previous_event_ms = int(previous.get("last_feishu_event_ms") or 0)
            except (AttributeError, TypeError, ValueError):
                previous_event_ms = 0
            editor_events = app.sheet_edit_events(
                path=app.NEWS_REVIEW_SHEET_EDIT_EVENT_PATH,
                after_ms=previous_event_ms,
            )
            cursor_event = editor_events[-1] if editor_events else {}
            from cmhk.intelligence.news_review_provenance import EditorEvidence, timestamp

            editor_evidence = EditorEvidence(editor_events)
            agent_decisions = app._news_auto_screening_decisions()
            recorded_agent_keys = {
                str(details.get("automation_event_key") or "")
                for event in app.AUTH.operation_audit(limit=None)
                if isinstance(event, dict)
                and event.get("action") == "news_review.update"
                and isinstance((details := event.get("details")), dict)
                and details.get("automation_event_key")
            }
            audit_at = app.datetime.now().astimezone().isoformat()
            pending_cells: set[tuple[int, int]] = set()
            if same_sheet and isinstance(previous_rows, dict):
                for row_key, current in current_rows.items():
                    before_row = previous_rows.get(row_key)
                    if not isinstance(before_row, dict) or before_row.get("title") != current.get("title"):
                        continue
                    before_decisions = before_row.get("decisions") if isinstance(before_row.get("decisions"), list) else []
                    after_decisions = current.get("decisions") or []
                    if len(before_decisions) < 2 or len(after_decisions) < 2:
                        continue
                    for decision_offset, column_index in enumerate(app.NEWS_REVIEW_DECISION_COLUMNS):
                        before = str(before_decisions[decision_offset] or "")
                        after = str(after_decisions[decision_offset] or "")
                        if before != after and (int(row_key), column_index, before, after) not in ignored:
                            pending_cells.add((int(row_key), column_index))
            revision_evidence_expected = bool(
                previous_revision > 0 and current_revision > previous_revision
            )
            changeset_evidence = app._news_review_changeset_cell_evidence(
                sheet_id=sheet_id,
                previous_revision=previous_revision,
                current_revision=current_revision,
                pending_cells=pending_cells,
            )
            observed_decision_change = False
            unresolved_editor_change = False
            if same_sheet and isinstance(previous_rows, dict):
                for row_key, current in current_rows.items():
                    before_row = previous_rows.get(row_key)
                    if not isinstance(before_row, dict) or before_row.get("title") != current.get("title"):
                        continue
                    before_decisions = before_row.get("decisions") if isinstance(before_row.get("decisions"), list) else []
                    after_decisions = current.get("decisions") or []
                    if len(before_decisions) < 2 or len(after_decisions) < 2:
                        continue
                    row_number = int(row_key)
                    for decision_offset, column_index in enumerate(
                        app.NEWS_REVIEW_DECISION_COLUMNS
                    ):
                        before = str(before_decisions[decision_offset] or "")
                        after = str(after_decisions[decision_offset] or "")
                        if before == after or (row_number, column_index, before, after) in ignored:
                            continue
                        observed_decision_change = True
                        field_label = str(headers[column_index] if len(headers) > column_index else f"审批列{column_index + 1}")
                        title = str(current.get("title") or f"飞书审核表第 {row_number} 行")
                        agent_match = app._news_auto_screening_match(
                            row_number=row_number,
                            title=title,
                            field=field_label,
                            before=before,
                            after=after,
                            event_at=audit_at,
                            decisions=agent_decisions,
                        )
                        cell_evidence = changeset_evidence.get((row_number, column_index))
                        changeset_ai_write = bool(
                            isinstance(cell_evidence, dict)
                            and cell_evidence.get("is_ai_edit") is True
                        )
                        changeset_human_write = bool(
                            isinstance(cell_evidence, dict)
                            and cell_evidence.get("is_ai_edit") is False
                        )
                        editor_event = editor_evidence.matching_event(cell_evidence)
                        profile = {}
                        if editor_event:
                            operator = editor_event["operators"][0]
                            profile = app.AUTH.feishu_profile_by_open_id(
                                str(operator.get("open_id") or ""),
                                str(operator.get("union_id") or ""),
                            )
                        verified_human = changeset_human_write and bool(profile.get("name"))
                        # A later manual changeset must not inherit an old matching
                        # machine decision merely because its before/after agree.
                        if cell_evidence and agent_match and not changeset_ai_write:
                            cell_at = timestamp(cell_evidence.get("create_time"))
                            machine_at = timestamp(agent_match.get("recorded_at_iso"))
                            if cell_at > machine_at:
                                agent_match = None
                            else:
                                # A verified machine receipt also wins when a user
                                # credential was used for the automated write.
                                verified_human = False
                        if changeset_ai_write or agent_match:
                            cell_actor = app.NEWS_AUTO_SCREENING_ACTOR
                        elif verified_human:
                            cell_actor = {
                                "id": str(profile.get("id") or ""),
                                "name": str(profile["name"]),
                                "avatarUrl": str(profile.get("avatar_url") or ""),
                                "role": "EXTERNAL",
                                "feishuOpenId": str(editor_event["operators"][0].get("open_id") or ""),
                            }
                        elif cell_evidence:
                            cell_actor = {
                                "id": "news-screening-unverified",
                                "name": "来源待核实", "role": "UNKNOWN",
                            }
                        else:
                            cell_actor = None
                        if cell_actor is None:
                            # Keep the previous value as the comparison baseline until
                            # either a verified Agent write or a Feishu editor resolves it.
                            current["decisions"][decision_offset] = before
                            if not agent_match:
                                unresolved_editor_change = True
                            continue
                        robot_write = bool(changeset_ai_write or agent_match)
                        details = {
                            "source_label": "新闻自动初筛" if robot_write else "飞书表格",
                            "target_label": title,
                            "news_id": str(current.get("record_id") or "")[:120],
                            "sheet_row": row_number,
                            "decision_rows": [row_number],
                            "field": field_label,
                            "before": before,
                            "after": after,
                        }
                        automation_event_key = ""
                        if robot_write:
                            if agent_match:
                                automation_event_key = str(
                                    agent_match.get("automation_event_key")
                                    or "|".join((
                                        str(agent_match.get("agent_run_id") or ""),
                                        str(row_number),
                                        app._news_review_field_label(field_label),
                                        after,
                                    ))
                                )
                            else:
                                automation_event_key = "|".join((
                                    "changeset",
                                    str(cell_evidence.get("revision") or ""),
                                    sheet_id,
                                    str(row_number),
                                    str(column_index),
                                    after,
                                ))
                            details.update({
                                "identity_note": (
                                    "由新闻自动初筛机器人写入；飞书 changeset 已逐格标记为 AI 编辑"
                                    if changeset_ai_write
                                    else "由新闻自动初筛机器人写入；已按行号、标题、字段、状态和时间窗口与 Agent 决策审计核验"
                                ),
                                "agent_run_id": str(agent_match.get("agent_run_id") or "") if agent_match else "",
                                "agent_recorded_at": str(agent_match.get("recorded_at_iso") or "") if agent_match else "",
                                "model": str(agent_match.get("model") or "") if agent_match else "",
                                "writer_profile": str(agent_match.get("writer_profile") or "") if agent_match else "",
                                "automation_event_key": automation_event_key,
                            })
                            if cell_evidence:
                                details.update({
                                    "feishu_changeset_revision": int(cell_evidence.get("revision") or 0),
                                    "feishu_changeset_at": str(cell_evidence.get("create_time") or ""),
                                    "feishu_changeset_action": str(cell_evidence.get("action") or ""),
                                    "feishu_changeset_ai_edit": changeset_ai_write,
                                })
                        else:
                            details.update({
                                "identity_note": (
                                    "逐格 changeset 与两秒内唯一操作者事件匹配，并经通讯录解析"
                                    if cell_actor.get("role") == "EXTERNAL"
                                    else "存在单元格变更证据，但不能核实人工或机器来源"
                                ),
                                "feishu_event_id": str((editor_event or {}).get("event_id") or ""),
                            })
                            if cell_evidence:
                                details.update({
                                    "feishu_changeset_revision": int(cell_evidence.get("revision") or 0),
                                    "feishu_changeset_at": str(cell_evidence.get("create_time") or ""),
                                    "feishu_changeset_action": str(cell_evidence.get("action") or ""),
                                    "feishu_changeset_ai_edit": cell_evidence.get("is_ai_edit"),
                                })
                        if not robot_write or automation_event_key not in recorded_agent_keys:
                            events.append(app.AUTH.record_operation(
                                actor=cell_actor,
                                action="news_review.update",
                                target=sheet_id,
                                source="feishu_sheet",
                                details=details,
                            ))
                            if robot_write:
                                recorded_agent_keys.add(automation_event_key)
            try:
                cursor_event_ms = int(cursor_event.get("create_time_ms") or 0)
            except (AttributeError, TypeError, ValueError):
                cursor_event_ms = 0
            event_window_settled = bool(
                cursor_event_ms
                and cursor_event_ms
                <= int(app.time.time() * 1000) - (app.NEWS_REVIEW_EVENT_SETTLE_SECONDS * 1000)
            )
            consume_event_cursor = bool(
                cursor_event_ms
                and not unresolved_editor_change
                and (observed_decision_change or event_window_settled)
            )
            next_state = {
                "sheet_id": sheet_id,
                "rows": current_rows,
                "spreadsheet_revision": int(
                    previous_revision
                    if unresolved_editor_change and revision_evidence_expected
                    else current_revision
                ),
                "last_feishu_event_ms": int(
                    cursor_event_ms
                    if consume_event_cursor
                    else previous_event_ms
                ),
            }
            if previous != next_state:
                app.AUTH._write(app.NEWS_REVIEW_AUDIT_STATE_PATH, next_state)
        return events

    publish(app, sync_news_review_sheet_audit)

    def reconcile_news_review_screener_column(snapshot: dict) -> dict:
        """Mirror the latest verified reviewer into Feishu column A."""

        from cmhk.intelligence.news_review_sheet import update_review_sheet_screeners

        app.attach_news_review_actors(snapshot, include_screener_actor=True)
        assignments: list[dict] = []
        unresolved_human_mentions: list[dict[str, object]] = []
        for row in snapshot.get("rows") or []:
            if not isinstance(row, dict):
                continue
            actor = row.pop("_screenerActor", None)
            values = row.get("values") if isinstance(row.get("values"), list) else []
            record_id = str(row.get("recordId") or "").strip()
            title = str(
                values[app.NEWS_REVIEW_TITLE_COLUMN]
                if len(values) > app.NEWS_REVIEW_TITLE_COLUMN
                else ""
            ).strip()
            if (
                row.get("readOnly") is True
                or str(row.get("storageSource") or "feishu") != "feishu"
                or not record_id
                or not title
                or not isinstance(actor, dict)
                or not str(actor.get("name") or "").strip()
            ):
                continue
            if (
                actor.get("isSystem") is not True
                and (
                    actor.get("resolved") is not True
                    or not str(actor.get("mentionToken") or "").strip()
                )
            ):
                unresolved_human_mentions.append(
                    {
                        "rowNumber": int(row.get("rowNumber") or 0),
                        "name": str(actor.get("name") or "")[:120],
                    }
                )
                # Never downgrade a human to plain text and pretend that it is an
                # @ mention. A later monitor cycle retries the contact resolution.
                continue
            assignments.append(
                {
                    key: actor.get(key)
                    for key in ("name", "mentionToken", "notify")
                    if key in actor
                }
                | {
                    "rowNumber": int(row.get("rowNumber") or 0),
                    "recordId": record_id,
                }
            )
        if not assignments:
            return {
                "status": "partial" if unresolved_human_mentions else "ok",
                "requestedCount": 0,
                "changedCount": 0,
                "verifiedCount": 0,
                "readbackVerified": True,
                "fullyReconciled": not unresolved_human_mentions,
                "unresolvedHumanMentionCount": len(unresolved_human_mentions),
                "unresolvedHumanMentions": unresolved_human_mentions[:20],
            }
        result = update_review_sheet_screeners(
            assignments,
            sheet_id=str(snapshot.get("sheetId") or "") or None,
        )
        if unresolved_human_mentions and result.get("status") == "ok":
            result["status"] = "partial"
        return {
            **result,
            "fullyReconciled": not unresolved_human_mentions
            and result.get("status") == "ok"
            and result.get("readbackVerified") is True,
            "unresolvedHumanMentionCount": len(unresolved_human_mentions),
            "unresolvedHumanMentions": unresolved_human_mentions[:20],
        }

    publish(app, reconcile_news_review_screener_column)

    def run_news_review_screener_monitor_cycle() -> dict:
        """Poll Feishu edits, resolve the person, and reconcile the first column."""

        from cmhk.intelligence.news_review_sheet import review_sheet_snapshot

        checked_at = app.datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            snapshot = review_sheet_snapshot(lock_timeout_seconds=0.25)
        except RuntimeError as exc:
            if str(exc) != "后台战略新闻任务正在更新飞书审核表，请稍后刷新":
                raise
            # The producer owns the same process lock while replacing/sorting the
            # active sheet. This is normal coordination, not a background error;
            # retain the last verified names and retry on the next interval.
            return {
                "status": "busy",
                "reason": "review_sheet_update_in_progress",
                "requestedCount": 0,
                "changedCount": 0,
                "verifiedCount": 0,
                "nativeMentionVerifiedCount": 0,
                "readbackVerified": False,
                "fullyReconciled": False,
                "unresolvedHumanMentionCount": 0,
                "unresolvedHumanMentions": [],
                "auditEventCount": 0,
                "checkedAt": checked_at,
            }
        events = app.sync_news_review_sheet_audit(snapshot)
        result = app.reconcile_news_review_screener_column(snapshot)
        return {
            **result,
            "auditEventCount": len(events),
            "checkedAt": checked_at,
        }

    publish(app, run_news_review_screener_monitor_cycle)

    def build_news_review_sheet_payload() -> dict:
        """Read the review sheet without letting optional reconciliation hide it."""
        from cmhk.intelligence.news_review_sheet import (
            review_sheet_history_snapshot,
            review_sheet_snapshot,
        )

        warnings: list[dict[str, str]] = []
        try:
            snapshot = review_sheet_snapshot()
        except Exception as exc:
            snapshot = review_sheet_history_snapshot(live_error=str(exc))
            warnings.append({"stage": "live_read", "error": str(exc)[:240]})
        payload = {
            "ok": True,
            **app.attach_news_review_actors(snapshot),
            "editorTracking": app.news_review_editor_tracking_status(),
        }
        audit_events: list[dict] = []
        if snapshot.get("snapshotMode") == "local_history":
            screener_sync = {
                "status": "unavailable",
                "readbackVerified": False,
                "fullyReconciled": False,
            }
        else:
            try:
                audit_events = app.sync_news_review_sheet_audit(snapshot)
            except Exception as exc:
                warnings.append({"stage": "audit_sync", "error": str(exc)[:240]})

            try:
                screener_sync = app.reconcile_news_review_screener_column(snapshot)
            except Exception as exc:
                screener_sync = {
                    "status": "unavailable",
                    "readbackVerified": False,
                    "fullyReconciled": False,
                }
                warnings.append({"stage": "screener_reconcile", "error": str(exc)[:240]})

        payload["screenerSync"] = {
            **screener_sync,
            "auditEventCount": len(audit_events),
        }
        if warnings:
            payload["warnings"] = warnings
        return payload

    publish(app, build_news_review_sheet_payload)

    def start_news_review_screener_monitor() -> None:
        """Start one daemon that keeps direct Feishu edits attributed without an open page."""

        # Mutable state remains on the application context.
        with app.NEWS_REVIEW_SCREENER_MONITOR_LOCK:
            if app.NEWS_REVIEW_SCREENER_MONITOR_STARTED:
                return
            app.NEWS_REVIEW_SCREENER_MONITOR_STARTED = True

        interval_seconds = max(
            60,
            int(app.os.environ.get("CMHK_NEWS_REVIEW_SCREENER_POLL_SECONDS", "60")),
        )

        def worker() -> None:
            while True:
                try:
                    app.run_news_review_screener_monitor_cycle()
                except Exception:
                    app.logging.exception("战略新闻筛选人定期同步失败")
                app.time.sleep(interval_seconds)

        app.threading.Thread(
            target=worker,
            name="news-review-screener-monitor",
            daemon=True,
        ).start()

    publish(app, start_news_review_screener_monitor)

    def news_review_editor_tracking_status() -> dict[str, object]:
        """Describe whether the formal runtime has received editor identities."""
        editor_events = app.sheet_edit_events(
            path=app.NEWS_REVIEW_SHEET_EDIT_EVENT_PATH,
            after_ms=0,
        )
        if not editor_events:
            return {
                "status": "waiting_for_first_edit",
                "receivedEvents": 0,
                "lastEventAtMs": 0,
                "message": "等待首条飞书表格编辑者事件",
            }
        latest = editor_events[-1]
        editors: list[dict[str, str]] = []
        for operator in latest.get("operators") or []:
            if not isinstance(operator, dict):
                continue
            profile = app.AUTH.feishu_profile_by_open_id(
                str(operator.get("open_id") or ""),
                str(operator.get("union_id") or ""),
            )
            if profile.get("name"):
                editors.append({
                    "id": str(profile.get("id") or ""),
                    "name": str(profile.get("name") or ""),
                    "avatarUrl": str(profile.get("avatar_url") or ""),
                    "openId": str(operator.get("open_id") or ""),
                })
        editor_names = "、".join(editor["name"] for editor in editors)
        return {
            "status": "active",
            "receivedEvents": len(editor_events),
            "lastEventAtMs": int(latest.get("create_time_ms") or 0),
            "lastEventId": str(latest.get("event_id") or ""),
            "lastEditors": editors,
            "message": (
                f"已接收飞书表格编辑者事件：{editor_names}"
                if editor_names
                else "已接收飞书表格编辑者事件"
            ),
        }

    publish(app, news_review_editor_tracking_status)

