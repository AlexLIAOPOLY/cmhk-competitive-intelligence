from __future__ import annotations

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def _handler_public_fields(handled: dict) -> dict[str, str]:
        open_id = str(handled.get("operator_id") or "")
        user = app.AUTH.public_user_by_feishu_open_id(open_id) or {}
        return {
            "handler_id": str(user.get("id") or ""),
            "handler_open_id": open_id,
            "handler_name": str(handled.get("operator_name") or user.get("name") or ""),
            "handler_source": str(handled.get("source") or ""),
            "handler_avatar_url": str(user.get("avatarUrl") or ""),
            "handled_at_hkt": str(handled.get("handled_at_hkt") or handled.get("completed_at_hkt") or ""),
            "manual_repaired_at_hkt": str(handled.get("handled_at_hkt") or handled.get("completed_at_hkt") or ""),
        }

    publish(app, _handler_public_fields)

    def _news_review_field_label(value: object) -> str:
        """Return the current display label while accepting historical audit names."""
        return {
            "是否纳入滚动": "纳入滚动栏",
            "纳入滚动": "纳入滚动栏",
            "是否纳入周报": "纳入周报",
        }.get(str(value or "").strip(), str(value or "").strip())

    publish(app, _news_review_field_label)

    def _news_review_event_effective_at(event: dict) -> str:
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if details.get("agent_recorded_at") and (
            details.get("agent_run_id")
            or str(event.get("actor_role") or "").upper() == "SYSTEM"
            or str(event.get("actor_id") or "") == "news-auto-screening-bot"
        ):
            return str(details.get("agent_recorded_at") or "")
        return str(details.get("feishu_changeset_at") or event.get("at") or "")

    publish(app, _news_review_event_effective_at)

    def _news_review_event_rank(event: dict, original_index: int) -> tuple[float, int, int]:
        try:
            effective_timestamp = app.datetime.fromisoformat(
                app._news_review_event_effective_at(event).replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            effective_timestamp = 0.0
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        actor_id = str(event.get("actor_id") or "")
        actor_role = str(event.get("actor_role") or "").upper()
        if actor_id == "news-auto-screening-bot" or actor_role == "SYSTEM" or details.get("agent_run_id"):
            actor_priority = 2
        elif not actor_id or actor_id == "feishu-review-sheet-collaborator":
            actor_priority = 1
        else:
            actor_priority = 0
        # operation_audit is newest-first, so a lower original index wins the
        # final tie after effective time and fail-closed actor priority.
        return effective_timestamp, actor_priority, -original_index

    publish(app, _news_review_event_rank)

    def _normalized_news_review_identity_text(value: object) -> str:
        return "".join(str(value or "").casefold().split())

    publish(app, _normalized_news_review_identity_text)

    def _news_review_contact_hints(actor: dict) -> tuple[str, str]:
        """Return the verified local display name and enterprise email, when known."""

        name = str(actor.get("name") or actor.get("account") or "").strip()
        email = str(actor.get("email") or "").strip().casefold()
        if email:
            return name, email

        actor_id = str(actor.get("id") or "").strip()
        source_open_id = str(
            actor.get("sourceOpenId") or actor.get("feishuOpenId") or ""
        ).strip()
        users = app.AUTH._read(app.AUTH.users_path, [])
        users = [item for item in users if isinstance(item, dict)] if isinstance(users, list) else []
        matched = next(
            (
                user
                for user in users
                if actor_id and str(user.get("id") or "") == actor_id
            ),
            None,
        )
        if matched is None and source_open_id:
            matched = next(
                (
                    user
                    for user in users
                    if source_open_id
                    in {
                        str(user.get("feishu_open_id") or ""),
                        str(user.get("feishu_union_id") or ""),
                    }
                ),
                None,
            )
        if matched is None and name:
            named = [
                user
                for user in users
                if app._normalized_news_review_identity_text(user.get("name"))
                == app._normalized_news_review_identity_text(name)
            ]
            matched = named[0] if len(named) == 1 else None
        if matched is not None:
            name = name or str(matched.get("name") or "").strip()
            email = str(matched.get("email") or "").strip().casefold()
        return name, email

    publish(app, _news_review_contact_hints)

    def _news_review_contact_search(query: str) -> dict:
        """Search the same user identity domain used by lark-cli sheet writes."""

        command = [
            app.resolve_lark_cli(),
            "contact",
            "+search-user",
            "--query",
            query,
            "--exclude-external-users",
            "--page-size",
            "30",
            "--as",
            "user",
            "--format",
            "json",
        ]
        profile = str(
            app.os.environ.get("CMHK_NEWS_REVIEW_FEISHU_PROFILE")
            or app.os.environ.get("CMHK_FEISHU_SHEETS_PROFILE")
            or ""
        ).strip()
        if profile:
            command.extend(["--profile", profile])
        process = app.subprocess.run(
            command,
            cwd=str(app.ROOT),
            env=app.lark_cli_env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            payload = app.json.loads(process.stdout) if process.stdout.strip() else {}
        except app.json.JSONDecodeError as exc:
            raise RuntimeError("飞书通讯录未返回有效 JSON") from exc
        if process.returncode or payload.get("ok") is False:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            raise RuntimeError(
                str(error.get("message") or process.stderr.strip() or "飞书通讯录查询失败")
            )
        return payload

    publish(app, _news_review_contact_search)

    def resolve_news_review_mention_identity(actor: dict | None) -> dict[str, object]:
        """Resolve an APP/event actor to the sheet writer's native mention token.

    Feishu Open IDs are application-scoped.  An OAuth Open ID captured by the
    APP cannot be copied into a rich-text cell written by another lark-cli app;
    resolve the same person by enterprise email (or an exact unique name) in
    the writer's own identity domain and cache only that derived mapping.
    """

        actor = actor if isinstance(actor, dict) else {}
        actor_id = str(actor.get("id") or "").strip()
        role = str(actor.get("role") or "").strip().upper()
        name, email = app._news_review_contact_hints(actor)
        is_system = actor_id == app.NEWS_AUTO_SCREENING_ACTOR["id"] or role == "SYSTEM"
        if is_system:
            return {
                "name": name or app.NEWS_AUTO_SCREENING_ACTOR["name"],
                "mentionToken": "",
                "resolved": True,
                "isSystem": True,
                "resolutionSource": "system_actor",
            }
        if not name:
            return {
                "name": "",
                "mentionToken": "",
                "resolved": False,
                "isSystem": False,
                "resolutionSource": "missing_name",
            }

        cache_key = (
            f"email:{email}"
            if email
            else f"name:{app._normalized_news_review_identity_text(name)}"
        )
        try:
            cache_seconds = max(
                300,
                int(app.os.environ.get("CMHK_NEWS_REVIEW_MENTION_CACHE_SECONDS", "604800")),
            )
        except ValueError:
            cache_seconds = 604800
        now = app.time.time()
        with app.NEWS_REVIEW_MENTION_IDENTITY_LOCK:
            cache = app.AUTH._read(app.NEWS_REVIEW_MENTION_IDENTITIES_PATH, {})
            cache = cache if isinstance(cache, dict) else {}
            identities = (
                cache.get("identities")
                if isinstance(cache.get("identities"), dict)
                else {}
            )
            cached = identities.get(cache_key)
            if isinstance(cached, dict):
                try:
                    cache_age = now - float(cached.get("resolvedAtEpoch") or 0)
                except (TypeError, ValueError):
                    cache_age = cache_seconds + 1
                cached_token = str(cached.get("openId") or "").strip()
                if cached_token and 0 <= cache_age <= cache_seconds:
                    return {
                        "name": name,
                        "mentionToken": cached_token,
                        "resolved": True,
                        "isSystem": False,
                        "resolutionSource": "cache",
                    }

        queries = [email] if email else []
        if name and name not in queries:
            queries.append(name)
        resolved_user: dict | None = None
        resolution_source = ""
        last_error = ""
        for query in queries:
            try:
                payload = app._news_review_contact_search(query)
            except (RuntimeError, app.subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
                continue
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            users = data.get("users") if isinstance(data.get("users"), list) else []
            exact: dict[str, dict] = {}
            for item in users:
                if not isinstance(item, dict):
                    continue
                if item.get("is_cross_tenant") is True or item.get("is_activated") is False:
                    continue
                open_id = str(item.get("open_id") or "").strip()
                if not open_id:
                    continue
                candidate_emails = {
                    str(item.get("email") or "").strip().casefold(),
                    str(item.get("enterprise_email") or "").strip().casefold(),
                }
                exact_match = (
                    email in candidate_emails
                    if email
                    else app._normalized_news_review_identity_text(item.get("localized_name"))
                    == app._normalized_news_review_identity_text(name)
                )
                if exact_match:
                    exact[open_id] = item
            # A truncated name search cannot prove uniqueness. Enterprise email is
            # tenant-unique, so one exact email match remains safe even if broader
            # fuzzy results exist beyond the first page.
            if len(exact) == 1 and (email or data.get("has_more") is not True):
                resolved_user = next(iter(exact.values()))
                resolution_source = "enterprise_email" if email else "exact_name"
                break
            last_error = "通讯录没有唯一精确匹配"

        mention_token = str((resolved_user or {}).get("open_id") or "").strip()
        if not mention_token:
            app.logging.warning(
                "战略新闻筛选人无法解析原生 @ 身份：%s（%s）",
                name,
                last_error or "未找到联系人",
            )
            return {
                "name": name,
                "mentionToken": "",
                "resolved": False,
                "isSystem": False,
                "resolutionSource": "unresolved",
            }

        entry = {
            "actorId": actor_id,
            "name": name,
            "email": email,
            "openId": mention_token,
            "localizedName": str((resolved_user or {}).get("localized_name") or ""),
            "source": resolution_source,
            "resolvedAt": app.datetime.now().astimezone().isoformat(timespec="seconds"),
            "resolvedAtEpoch": now,
        }
        with app.NEWS_REVIEW_MENTION_IDENTITY_LOCK:
            latest_cache = app.AUTH._read(app.NEWS_REVIEW_MENTION_IDENTITIES_PATH, {})
            latest_cache = latest_cache if isinstance(latest_cache, dict) else {}
            latest_identities = (
                dict(latest_cache.get("identities"))
                if isinstance(latest_cache.get("identities"), dict)
                else {}
            )
            latest_identities[cache_key] = entry
            app.AUTH._write(
                app.NEWS_REVIEW_MENTION_IDENTITIES_PATH,
                {
                    "version": 1,
                    "updatedAt": entry["resolvedAt"],
                    "identities": latest_identities,
                },
            )
        return {
            "name": name,
            "mentionToken": mention_token,
            "resolved": True,
            "isSystem": False,
            "resolutionSource": resolution_source,
        }

    publish(app, resolve_news_review_mention_identity)

    def attach_news_review_actors(
        snapshot: dict,
        *,
        include_screener_actor: bool = False,
    ) -> dict:
        """Attach the latest verified human or robot reviewer to each reviewed row."""
        app.refresh_news_review_actor_overrides()
        overrides = app.AUTH._read(app.NEWS_REVIEW_ACTOR_OVERRIDES_PATH, {})
        overrides = overrides if isinstance(overrides, dict) else {}
        reviewers_by_row_title: dict[tuple[int, str], dict[str, str]] = {}
        reviewers_by_title: dict[str, dict[str, str]] = {}
        reviewers_by_record: dict[str, dict[str, str]] = {}
        reviewers_by_row_title_field: dict[tuple[int, str, str], dict[str, str]] = {}
        reviewers_by_title_field: dict[tuple[str, str], dict[str, str]] = {}
        reviewers_by_record_field: dict[tuple[str, str], dict[str, str]] = {}
        audit_events = app.AUTH.operation_audit(limit=None)
        ranked_events = [
            event
            for original_index, event in sorted(
                enumerate(audit_events),
                key=lambda item: app._news_review_event_rank(item[1], item[0]),
                reverse=True,
            )
        ]
        for event in ranked_events:
            if event.get("action") != "news_review.update" or event.get("result") != "success":
                continue
            override = overrides.get(str(event.get("id") or ""))
            if str(event.get("actor_id") or "") == "feishu-review-sheet-collaborator":
                if not isinstance(override, dict) or not override.get("name"):
                    continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            decision_rows = details.get("decision_rows") if isinstance(details.get("decision_rows"), list) else []
            reviewed_title = str(details.get("target_label") or event.get("target_label") or "").strip()
            reviewed_record_id = str(details.get("news_id") or details.get("record_id") or "").strip()
            reviewed_field = app._news_review_field_label(details.get("field"))
            reviewer = {
                "id": str((override or {}).get("id") or event.get("actor_id") or ""),
                "name": str((override or {}).get("name") or event.get("actor_name") or "未知用户"),
                "avatarUrl": str((override or {}).get("avatar_url") or event.get("actor_avatar_url") or ""),
                "role": str(event.get("actor_role") or ""),
                "reviewedAt": app._news_review_event_effective_at(event),
                # This source Open ID belongs to the APP/event application domain.
                # It is only an identity hint and must never be written directly
                # into a sheet rich-text mention from another application.
                "sourceOpenId": str(
                    (override or {}).get("open_id")
                    or event.get("actor_open_id")
                    or ""
                ),
            }
            if reviewed_record_id:
                reviewers_by_record.setdefault(reviewed_record_id, reviewer)
                if reviewed_field:
                    reviewers_by_record_field.setdefault(
                        (reviewed_record_id, reviewed_field), reviewer
                    )
            for cell in details.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                cell_record_id = str(
                    cell.get("news_id") or cell.get("record_id") or ""
                ).strip()
                cell_title = str(cell.get("title") or reviewed_title).strip()
                cell_field = app._news_review_field_label(cell.get("field"))
                if not cell_field:
                    try:
                        cell_column = int(cell.get("column", cell.get("columnIndex", -1)))
                    except (TypeError, ValueError):
                        cell_column = -1
                    cell_field = {
                        # Column 0 is retained only for pre-v10 footprints that did
                        # not persist the field label.
                        0: "纳入滚动栏",
                        app.NEWS_REVIEW_APP_STATUS_COLUMN: "纳入滚动栏",
                        app.NEWS_REVIEW_WEEKLY_STATUS_COLUMN: "纳入周报",
                    }.get(cell_column, "")
                try:
                    cell_row_number = int(
                        cell.get("row", cell.get("rowNumber", 0)) or 0
                    )
                except (TypeError, ValueError):
                    cell_row_number = 0
                if cell_record_id:
                    reviewers_by_record.setdefault(cell_record_id, reviewer)
                    if cell_field:
                        reviewers_by_record_field.setdefault(
                            (cell_record_id, cell_field), reviewer
                        )
                if cell_title:
                    reviewers_by_title.setdefault(cell_title, reviewer)
                    if cell_row_number:
                        reviewers_by_row_title.setdefault(
                            (cell_row_number, cell_title), reviewer
                        )
                    if cell_field:
                        reviewers_by_title_field.setdefault(
                            (cell_title, cell_field), reviewer
                        )
                        if cell_row_number:
                            reviewers_by_row_title_field.setdefault(
                                (cell_row_number, cell_title, cell_field), reviewer
                            )
            for raw_row_number in decision_rows:
                try:
                    row_number = int(raw_row_number)
                except (TypeError, ValueError):
                    continue
                if reviewed_title:
                    reviewers_by_row_title.setdefault((row_number, reviewed_title), reviewer)
                    reviewers_by_title.setdefault(reviewed_title, reviewer)
                    if reviewed_field:
                        reviewers_by_row_title_field.setdefault(
                            (row_number, reviewed_title, reviewed_field), reviewer
                        )
                        reviewers_by_title_field.setdefault(
                            (reviewed_title, reviewed_field), reviewer
                        )
                # Legacy events without a stable news ID or title are deliberately
                # not bound by row number. Row coordinates drift whenever a newer
                # batch is inserted at the top of the Feishu sheet.
        mention_identities: dict[tuple[str, str, str], dict[str, object]] = {}
        for row in snapshot.get("rows") or []:
            if not isinstance(row, dict):
                continue
            try:
                row_number = int(row.get("rowNumber") or 0)
            except (TypeError, ValueError):
                row_number = 0
            values = row.get("values") if isinstance(row.get("values"), list) else []
            title = str(
                values[app.NEWS_REVIEW_TITLE_COLUMN]
                if len(values) > app.NEWS_REVIEW_TITLE_COLUMN
                else ""
            ).strip()
            record_id = str(row.get("recordId") or "").strip()
            reviewer = (
                reviewers_by_record.get(record_id)
                or reviewers_by_row_title.get((row_number, title))
                or reviewers_by_title.get(title)
            )
            row.pop("_screenerActor", None)
            if reviewer:
                row["reviewer"] = {
                    key: reviewer.get(key, "")
                    for key in ("id", "name", "avatarUrl", "role", "reviewedAt")
                }
                if include_screener_actor and reviewer.get("role") != "UNKNOWN":
                    identity_key = (
                        str(reviewer.get("id") or ""),
                        str(reviewer.get("name") or ""),
                        str(reviewer.get("sourceOpenId") or ""),
                    )
                    mention_identity = mention_identities.get(identity_key)
                    if mention_identity is None:
                        mention_identity = app.resolve_news_review_mention_identity(reviewer)
                        mention_identities[identity_key] = mention_identity
                    row["_screenerActor"] = {
                        "name": str(mention_identity.get("name") or ""),
                        "mentionToken": str(
                            mention_identity.get("mentionToken") or ""
                        ),
                        "notify": False,
                        "isSystem": bool(mention_identity.get("isSystem")),
                        "resolved": bool(mention_identity.get("resolved")),
                        "resolutionSource": str(
                            mention_identity.get("resolutionSource") or ""
                        ),
                    }
            field_reviewers: dict[str, dict[str, str]] = {}
            for field_name in ("纳入滚动栏", "纳入周报"):
                field_reviewer = (
                    reviewers_by_record_field.get((record_id, field_name))
                    or reviewers_by_row_title_field.get((row_number, title, field_name))
                    or reviewers_by_title_field.get((title, field_name))
                )
                if field_reviewer:
                    field_reviewers[field_name] = {
                        key: field_reviewer.get(key, "")
                        for key in ("id", "name", "avatarUrl", "role", "reviewedAt")
                    }
            if field_reviewers:
                row["reviewers"] = field_reviewers
        from cmhk.intelligence.news_review_provenance import attach_screening_methods

        return attach_screening_methods(
            snapshot, ranked_events, app.sheet_edit_events(path=app.NEWS_REVIEW_SHEET_EDIT_EVENT_PATH)
        )

    publish(app, attach_news_review_actors)

    def refresh_news_review_actor_overrides(*, force: bool = False) -> dict[str, dict[str, str]]:
        """Backfill legacy generic actors through Feishu's official audit API."""
        # Mutable state remains on the application context.
        now = app.time.time()
        with app.NEWS_REVIEW_ACTOR_BACKFILL_LOCK:
            if not force and now - app.NEWS_REVIEW_ACTOR_BACKFILL_LAST_ATTEMPT < 300:
                cached = app.AUTH._read(app.NEWS_REVIEW_ACTOR_OVERRIDES_PATH, {})
                return cached if isinstance(cached, dict) else {}
            app.NEWS_REVIEW_ACTOR_BACKFILL_LAST_ATTEMPT = now

        existing = app.AUTH._read(app.NEWS_REVIEW_ACTOR_OVERRIDES_PATH, {})
        overrides = existing if isinstance(existing, dict) else {}
        generic_events = [
            event
            for event in app.AUTH.operation_audit(limit=1000)
            if event.get("action") == "news_review.update"
            and event.get("result") == "success"
            and str(event.get("actor_id") or "") == "feishu-review-sheet-collaborator"
            and str(event.get("id") or "") not in overrides
        ]
        timestamps: list[tuple[dict, int]] = []
        for event in generic_events:
            try:
                parsed = app.datetime.fromisoformat(str(event.get("at") or "").replace("Z", "+00:00"))
                timestamps.append((event, int(parsed.timestamp())))
            except ValueError:
                continue
        if not timestamps:
            return overrides
        try:
            audit_events = app.AUTH.feishu_sheet_edit_audit_events(
                spreadsheet_token=app.TARGET_SPREADSHEET_TOKEN,
                oldest=max(0, min(timestamp for _, timestamp in timestamps) - 900),
                latest=max(timestamp for _, timestamp in timestamps) + 900,
            )
        except Exception:
            return overrides

        candidates: list[tuple[int, dict[str, str]]] = []
        for item in audit_events:
            try:
                event_time = int(item.get("event_time") or 0)
            except (TypeError, ValueError):
                continue
            profile = app.AUTH.feishu_profile_by_open_id(str(item.get("operator_value") or ""))
            if event_time and profile.get("name"):
                candidates.append((event_time, profile))
        for event, recorded_at in timestamps:
            nearby = [candidate for candidate in candidates if abs(candidate[0] - recorded_at) <= 900]
            if not nearby:
                continue
            _, profile = min(nearby, key=lambda candidate: abs(candidate[0] - recorded_at))
            overrides[str(event["id"])] = profile
        if overrides != existing:
            app.AUTH._write(app.NEWS_REVIEW_ACTOR_OVERRIDES_PATH, overrides)
        return overrides

    publish(app, refresh_news_review_actor_overrides)

