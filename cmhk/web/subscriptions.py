from __future__ import annotations

# Annotation imports do not create application services or mutable state.
from cmhk.services.subscriptions import SubscriptionService

from ._binding import publish


def bind(app) -> None:
    """Bind this domain to the existing application and its shared state."""
    def subscription_service() -> SubscriptionService:
        return app.SubscriptionService(runtime_root=app.ROOT)

    publish(app, subscription_service)

    def weekly_report_preference_payload(
        service: SubscriptionService,
        *,
        status: dict | None = None,
    ) -> dict[str, object]:
        preference = service.weekly_report_preference()
        preferred_path = str(preference.get("path") or "")
        outputs = (status or app.build_status()).get("outputs") or []
        report = next(
            (
                item
                for item in outputs
                if isinstance(item, dict)
                and item.get("reportType") == "weekly"
                and item.get("path_str") == preferred_path
            ),
            None,
        )
        return {
            **preference,
            "path": preferred_path if report else "",
            "available": bool(report),
            "report": {
                "name": str(report.get("name") or ""),
                "path": str(report.get("path_str") or ""),
                "is_edited": bool(report.get("isEdited")),
                "mtime_text": str(report.get("mtimeText") or ""),
            } if report else None,
        }

    publish(app, weekly_report_preference_payload)

    def performance_report_preference_payload(
        service: SubscriptionService,
        *,
        status: dict | None = None,
    ) -> dict[str, object]:
        preference = service.performance_report_preference()
        preferred_path = str(preference.get("path") or "")
        outputs = (status or app.build_status()).get("outputs") or []
        report = next(
            (
                item
                for item in outputs
                if isinstance(item, dict)
                and item.get("reportType") == "carrier-performance"
                and item.get("path_str") == preferred_path
            ),
            None,
        )
        return {
            **preference,
            "path": preferred_path if report else "",
            "available": bool(report),
            "report": {
                "name": str(report.get("name") or ""),
                "path": str(report.get("path_str") or ""),
                "is_edited": bool(report.get("isEdited")),
                "mtime_text": str(report.get("mtimeText") or ""),
            } if report else None,
        }

    publish(app, performance_report_preference_payload)

    def update_weekly_report_preference(
        service: SubscriptionService,
        report_path: str,
    ) -> dict[str, object]:
        normalized = str(report_path or "").strip()
        status = app.build_status()
        if normalized and not any(
            isinstance(item, dict)
            and item.get("reportType") == "weekly"
            and item.get("path_str") == normalized
            for item in (status.get("outputs") or [])
        ):
            raise ValueError("选中的周报不在当前报告库中，请刷新后重新选择")
        if normalized:
            service.validate_selected_report(normalized)
        service.update_weekly_report_preference(normalized)
        return app.weekly_report_preference_payload(service, status=status)

    publish(app, update_weekly_report_preference)

    def update_performance_report_preference(
        service: SubscriptionService,
        report_path: str,
    ) -> dict[str, object]:
        normalized = str(report_path or "").strip()
        status = app.build_status()
        if normalized and not any(
            isinstance(item, dict)
            and item.get("reportType") == "carrier-performance"
            and item.get("path_str") == normalized
            for item in (status.get("outputs") or [])
        ):
            raise ValueError("选中的业绩摘要不在当前报告库中，请刷新后重新选择")
        if normalized:
            service.validate_selected_report(normalized)
        service.update_performance_report_preference(normalized)
        return app.performance_report_preference_payload(service, status=status)

    publish(app, update_performance_report_preference)

    def subscription_operation_audit_payload(
        action: str,
        payload: dict,
        result: dict | None = None,
    ) -> dict | None:
        """Build a sanitized footprint for mutations and sends on the subscription page."""
        audit_action = app.SUBSCRIPTION_OPERATION_ACTIONS.get(str(action or ""))
        if not audit_action:
            return None
        result = result if isinstance(result, dict) else {}
        details: dict[str, object] = {
            "source_label": "订阅管理页",
            "page": "subscriptions",
            "page_action": action,
        }
        target = "subscriptions"
        target_label = "订阅管理"

        if action == "update":
            target = str(payload.get("openId") or "subscriber")
            target_label = str(result.get("display_name") or "订阅者设置")[:240]
            details.update({
                "services": [str(item)[:40] for item in (payload.get("services") or [])[:10]],
                "news_categories": [str(item)[:40] for item in (payload.get("newsCategories") or [])[:20]],
                "news_frequency": str(payload.get("newsFrequency") or "")[:40],
                "news_item_limit": payload.get("newsItemLimit"),
                "news_region_preference": str(payload.get("newsRegionPreference") or "")[:40],
                "news_delivery_times": [str(item)[:20] for item in (payload.get("newsDeliveryTimes") or [])[:2]],
                "report_mode": str(payload.get("reportMode") or "")[:40],
                "status": str(payload.get("status") or "")[:40],
            })
        elif action == "updateNewsSchedule":
            target = "strategic-news-schedule"
            target_label = "战略新闻排期"
            details["enabled"] = payload.get("enabled") is True
        elif action == "updateReportSchedule":
            target = "weekly-report-schedule"
            target_label = "周报排期"
            details.update({
                "days": result.get("days") or payload.get("days"),
                "time": str(result.get("time") or payload.get("time") or "")[:20],
                "enabled": payload.get("enabled") is True,
            })
        elif action == "updatePerformanceSchedule":
            target = "performance-report-schedule"
            target_label = "业绩摘要排期"
            details.update({
                "days": result.get("days") or payload.get("days"),
                "time": str(result.get("time") or payload.get("time") or "")[:20],
                "enabled": payload.get("enabled") is True,
            })
        elif action == "setWeeklyReportPreference":
            target = str(result.get("path") or "automatic-weekly-report")
            target_label = str((result.get("report") or {}).get("name") or "自动选择最新正式版")[:240]
            details.update({
                "weekly_report_path": str(result.get("path") or "")[:240],
                "selection": "manual" if result.get("path") else "automatic",
            })
        elif action == "setPerformanceReportPreference":
            target = str(result.get("path") or "automatic-performance-report")
            target_label = str((result.get("report") or {}).get("name") or "自动选择最新正式版")[:240]
            details.update({
                "performance_report_path": str(result.get("path") or "")[:240],
                "selection": "manual" if result.get("path") else "automatic",
            })
        elif action == "refreshDirectory":
            target = "feishu-directory"
            target_label = "飞书通讯录"
            details.update({
                "people_count": int(result.get("people_count") or 0),
                "department_count": int(result.get("department_count") or 0),
            })
        elif action == "addCandidates":
            target = "subscription-invite-candidates"
            target_label = "待邀请名单"
            details["added_count"] = int(result.get("added_count") or len(payload.get("directoryOpenIds") or []))
        elif action == "invite":
            recipients = result.get("results") if isinstance(result.get("results"), list) else []
            names = [str(item.get("display_name") or "").strip() for item in recipients if isinstance(item, dict)]
            requested_count = int(result.get("requested_count") or len(payload.get("callbackOpenIds") or []))
            target = "subscription-invites"
            target_label = "、".join(name for name in names if name)[:240] or f"订阅邀请（{requested_count} 人）"
            details.update({
                "recipient_count": requested_count,
                "sent_count": int(result.get("sent_count") or 0),
                "failed_count": int(result.get("failed_count") or 0),
            })
        elif action == "inviteTarget":
            target = str(payload.get("targetId") or "subscription-invite-target")
            target_label = str(result.get("target_name") or "订阅邀请目标")[:240]
            details.update({
                "target_type": str(result.get("target_type") or payload.get("targetType") or "")[:20],
                "message_id": str(result.get("message_id") or "")[:120],
            })
        elif action == "publish":
            target = str(result.get("target_id") or payload.get("targetId") or "subscription-card-target")
            target_label = "订阅入口卡片接收人" if str(payload.get("targetType") or "") == "user" else "订阅入口卡片群聊"
            details.update({
                "target_type": str(result.get("target_type") or payload.get("targetType") or "")[:20],
                "message_id": str(result.get("message_id") or "")[:120],
                "readback_verified": bool(result.get("verified")),
            })
        else:
            target_open_id = str(payload.get("targetOpenId") or payload.get("testOpenId") or "")
            target = target_open_id or "all-active-subscribers"
            target_label = "指定订阅者" if target_open_id else "全部有效订阅者"
            details.update({
                "service": str(result.get("service") or payload.get("service") or "latest")[:40],
                "recipient_count": int(result.get("recipient_count") or 0),
                "verified_count": int(result.get("verified_count") or 0),
                "queued_count": int(result.get("queued_count") or 0),
                "failed_count": int(result.get("failed_count") or 0),
                "batch_id": str(result.get("batch_id") or "")[:120],
                "weekly_report_path": str(
                    result.get("weekly_report_path") or payload.get("weeklyReportPath") or ""
                )[:240],
                "weekly_report_selection": str(
                    result.get("weekly_report_selection") or "automatic"
                )[:20],
            })

        details["target_label"] = target_label
        return {
            "action": audit_action,
            "target": target[:240],
            "details": details,
        }

    publish(app, subscription_operation_audit_payload)

    def record_subscription_operation_footprint(
        *,
        actor: dict | None,
        action: str,
        payload: dict,
        operation_result: dict | None = None,
        audit_result: str = "success",
        error: str = "",
        origin: str = "",
    ) -> dict | None:
        """Write a subscription footprint without turning a completed send into a retry risk."""
        audit_payload = app.subscription_operation_audit_payload(action, payload, operation_result)
        if not audit_payload:
            return None
        if error:
            audit_payload = {
                **audit_payload,
                "details": {**audit_payload["details"], "error": str(error)[:240]},
            }
        try:
            return app.AUTH.record_operation(
                actor=actor,
                result=audit_result,
                origin=origin,
                **audit_payload,
            )
        except Exception:
            app.logging.exception("failed to record subscription operation footprint: %s", action)
            return None

    publish(app, record_subscription_operation_footprint)
