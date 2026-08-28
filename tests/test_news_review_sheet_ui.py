from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cmhk.intelligence.news_review_sheet as news_review_sheet
from cmhk.auth.service import AuthService
import web_app


def sheet_row(*values: str) -> list[str]:
    return [*values, *([""] * (len(news_review_sheet.HEADERS) - len(values)))]


class NewsReviewSheetModelTests(unittest.TestCase):
    def test_snapshot_keeps_live_sheet_rows_and_edit_contract(self) -> None:
        rows = [
            sheet_row(
                "待审核",
                "接受",
                "未同步",
                "2026-08-03",
                "香港本地",
                "竞对动态",
                "香港电讯推出自主研发 AI 平台",
                "平台汇聚全球 AI 资源。",
                "香港01",
                "2026-08-03",
                "https://example.com/news",
            )
        ]
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_read_rows", return_value=rows),
        ):
            payload = news_review_sheet.review_sheet_snapshot()

        self.assertEqual(payload["sheetId"], "sheet-1")
        self.assertEqual(payload["headers"], news_review_sheet.HEADERS)
        self.assertNotIn(2, payload["editableColumns"])
        self.assertEqual(payload["rows"][0]["rowNumber"], 2)
        self.assertEqual(payload["rows"][0]["values"][6], "香港电讯推出自主研发 AI 平台")

    def test_snapshot_fails_fast_when_background_sync_holds_lock(self) -> None:
        lock = mock.Mock()
        lock.acquire.return_value = False
        with mock.patch.object(news_review_sheet, "_LOCK", lock):
            with self.assertRaisesRegex(RuntimeError, "后台战略新闻任务正在更新"):
                news_review_sheet.review_sheet_snapshot()

        lock.acquire.assert_called_once_with(timeout=1.0)
        lock.release.assert_not_called()

    def test_update_coalesces_adjacent_cells_and_requires_readback(self) -> None:
        before = sheet_row("待审核", "待审核", "未同步", "2026-08-03")
        after = sheet_row("接受", "接受", "已纳入", "2026-08-03")
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_review_process_lock", return_value=nullcontext(True)),
            mock.patch.object(news_review_sheet, "_read_rows", side_effect=[[before], [after]]),
            mock.patch.object(news_review_sheet, "_write") as write,
            mock.patch.object(news_review_sheet, "apply_reviews", return_value={"accepted_count": 1}),
        ):
            payload = news_review_sheet.update_review_sheet_cells(
                [
                    {"rowNumber": 2, "columnIndex": 0, "before": "待审核", "value": "接受"},
                    {"rowNumber": 2, "columnIndex": 1, "before": "待审核", "value": "接受"},
                ]
            )

            write.assert_called_once_with(
                "sheet-1",
                "A2:B2",
                [["接受", "接受"]],
                identity="",
                profile="",
            )
        self.assertTrue(payload["readbackVerified"])
        self.assertEqual(payload["changedCount"], 2)
        self.assertEqual(payload["rows"][0]["values"][2], "已纳入")

    def test_update_stops_on_stale_cell_instead_of_overwriting(self) -> None:
        rows = [sheet_row("接受", "待审核", "已纳入")]
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_review_process_lock", return_value=nullcontext(True)),
            mock.patch.object(news_review_sheet, "_read_rows", return_value=rows),
            mock.patch.object(news_review_sheet, "_write") as write,
        ):
            with self.assertRaisesRegex(RuntimeError, "其他用户修改"):
                news_review_sheet.update_review_sheet_cells(
                    [{"rowNumber": 2, "columnIndex": 0, "before": "待审核", "value": "不接受"}]
                )
        write.assert_not_called()

    def test_sync_status_column_is_not_user_editable(self) -> None:
        rows = [sheet_row("待审核", "待审核", "未同步")]
        with (
            mock.patch.object(news_review_sheet, "_resolved_review_sheet_id", return_value="sheet-1"),
            mock.patch.object(news_review_sheet, "_review_process_lock", return_value=nullcontext(True)),
            mock.patch.object(news_review_sheet, "_read_rows", return_value=rows),
        ):
            with self.assertRaisesRegex(ValueError, "不能手工修改"):
                news_review_sheet.update_review_sheet_cells(
                    [{"rowNumber": 2, "columnIndex": 2, "before": "未同步", "value": "已纳入"}]
                )


class NewsReviewSheetStaticUiTests(unittest.TestCase):
    def test_report_library_contains_real_sheet_workspace(self) -> None:
        html = (web_app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (web_app.STATIC_DIR / "news-review-sheet.js").read_text(encoding="utf-8")
        css = (web_app.STATIC_DIR / "news-review-sheet.css").read_text(encoding="utf-8")
        organization_script = (web_app.STATIC_DIR / "organization-admin.js").read_text(encoding="utf-8")
        organization_css = (web_app.STATIC_DIR / "organization-admin.css").read_text(encoding="utf-8")

        self.assertIn('id="openNewsReviewSheetButton"', html)
        self.assertIn('id="newsReviewWorkspace"', html)
        self.assertNotIn('id="newsReviewRefreshButton"', html)
        self.assertNotIn('id="newsReviewCopyButton"', html)
        self.assertNotIn('id="newsReviewExportButton"', html)
        self.assertIn('fetch("/api/news-review-sheet"', script)
        self.assertIn('fetch("/api/news-review-sheet/update"', script)
        self.assertIn("SHEET_READ_TIMEOUT_MS = 30000", script)
        self.assertIn("SHEET_AUTO_REFRESH_MS = 15000", script)
        self.assertIn("window.setInterval", script)
        self.assertIn("document.visibilityState", script)
        self.assertIn("系统每 15 秒自动重试", script)
        self.assertIn('controller.abort()', script)
        self.assertIn("显示缓存 · 实时刷新暂不可用", script)
        self.assertIn('event.clipboardData.setData("text/plain", payload.text)', script)
        self.assertIn('event.clipboardData.setData("text/html", payload.html)', script)
        self.assertIn('value === "暂缓"', script)
        self.assertIn('value === "同步失败"', script)
        self.assertIn("model.saving", script)
        self.assertNotIn("copySelection", script)
        self.assertNotIn("exportExcel", script)
        self.assertIn("position: sticky", css)
        self.assertIn(".news-review-status-select.status-accepted", css)
        self.assertIn("reviewerAvatar(row.reviewer)", script)
        self.assertIn("news-review-reviewer", css)
        self.assertIn('<th>来源</th>', organization_script)
        self.assertIn('label: "飞书表格"', organization_script)
        self.assertIn('label: "本地 APP"', organization_script)
        self.assertIn("CMHKNewsReviewSheetSyncPromise", organization_script)
        self.assertIn("window.CMHKSyncNewsReviewSheet", organization_script)
        self.assertIn("organization-audit-source.is-feishu", organization_css)


class NewsReviewActorTests(unittest.TestCase):
    def test_latest_successful_decision_actor_is_attached_to_review_row(self) -> None:
        snapshot = {"rows": [{"rowNumber": 2, "values": ["接受"]}, {"rowNumber": 3, "values": ["待审核"]}]}
        events = [
            {
                "at": "2026-08-20T09:00:00+08:00",
                "actor_id": "user-2",
                "actor_name": "最新复核人",
                "actor_avatar_url": "https://example.com/new.png",
                "action": "news_review.update",
                "result": "success",
                "details": {"decision_rows": [2]},
            },
            {
                "at": "2026-08-20T08:00:00+08:00",
                "actor_id": "user-1",
                "actor_name": "旧复核人",
                "action": "news_review.update",
                "result": "success",
                "details": {"decision_rows": [2, 3]},
            },
        ]
        with mock.patch.object(web_app.AUTH, "operation_audit", return_value=events):
            result = web_app.attach_news_review_actors(snapshot)

        self.assertEqual(result["rows"][0]["reviewer"]["name"], "最新复核人")
        self.assertEqual(result["rows"][0]["reviewer"]["avatarUrl"], "https://example.com/new.png")
        self.assertEqual(result["rows"][1]["reviewer"]["name"], "旧复核人")

    def test_legacy_generic_actor_is_backfilled_from_official_audit_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AuthService(Path(temp_dir))
            event = service.record_operation(
                actor={"id": "feishu-review-sheet-collaborator", "name": "飞书表格协作者"},
                action="news_review.update",
                source="feishu_sheet",
                details={"decision_rows": [39]},
            )
            override_path = service.state_dir / "news-review-actor-overrides.json"
            with (
                mock.patch.object(web_app, "AUTH", service),
                mock.patch.object(web_app, "NEWS_REVIEW_ACTOR_OVERRIDES_PATH", override_path),
                mock.patch.object(service, "feishu_sheet_edit_audit_events", return_value=[{
                    "event_time": int(datetime.fromisoformat(event["at"]).timestamp()) - 20,
                    "operator_value": "ou_alice",
                }]),
                mock.patch.object(service, "feishu_profile_by_open_id", return_value={
                    "id": "fs-alice",
                    "name": "Alice Chen",
                    "avatar_url": "https://example.com/alice.png",
                }),
            ):
                overrides = web_app.refresh_news_review_actor_overrides(force=True)

            self.assertEqual(overrides[event["id"]]["name"], "Alice Chen")

    def test_direct_feishu_decision_is_mirrored_with_real_event_actor_once(self) -> None:
        def snapshot(status: str) -> dict:
            return {
                "sheetId": "sheet-1",
                "updatedAt": "2026-08-25T10:00:00+08:00",
                "headers": news_review_sheet.HEADERS,
                "rows": [{"rowNumber": 2, "values": sheet_row(status, "待审核", "未同步", "", "", "", "测试新闻")}],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            service = AuthService(Path(temp_dir))
            state_path = service.state_dir / "news-review-sheet-audit-state.json"
            with (
                mock.patch.object(web_app, "AUTH", service),
                mock.patch.object(web_app, "NEWS_REVIEW_AUDIT_STATE_PATH", state_path),
                mock.patch.object(web_app, "sheet_edit_events", return_value=[{
                    "event_id": "evt-1",
                    "create_time_ms": 1787638413000,
                    "operators": [{"open_id": "ou_alice"}],
                }]),
                mock.patch.object(service, "feishu_profile_by_open_id", return_value={
                    "id": "fs-alice",
                    "name": "Alice Chen",
                    "avatar_url": "https://example.com/alice.png",
                }),
            ):
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot("待审核")), [])
                events = web_app.sync_news_review_sheet_audit(snapshot("接受"))
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["source"], "feishu_sheet")
                self.assertEqual(events[0]["actor_name"], "Alice Chen")
                self.assertEqual(events[0]["details"]["feishu_event_id"], "evt-1")
                self.assertEqual(events[0]["details"]["before"], "待审核")
                self.assertEqual(events[0]["details"]["after"], "接受")
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot("接受")), [])
                ignored = [{"rowNumber": 2, "columnIndex": 0, "before": "接受", "value": "不接受"}]
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot("不接受"), ignored_changes=ignored), [])

    def test_direct_feishu_decision_waits_until_event_actor_is_available(self) -> None:
        def snapshot(status: str) -> dict:
            return {
                "sheetId": "sheet-1",
                "headers": news_review_sheet.HEADERS,
                "rows": [{"rowNumber": 2, "values": sheet_row(status, "待审核", "未同步", "", "", "", "测试新闻")}],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            service = AuthService(Path(temp_dir))
            state_path = service.state_dir / "news-review-sheet-audit-state.json"
            with (
                mock.patch.object(web_app, "AUTH", service),
                mock.patch.object(web_app, "NEWS_REVIEW_AUDIT_STATE_PATH", state_path),
                mock.patch.object(web_app, "sheet_edit_events", return_value=[]),
            ):
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot("待审核")), [])
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot("接受")), [])
                saved = service._read(state_path, {})
                self.assertEqual(saved["rows"]["2"]["decisions"][0], "待审核")

    def test_verified_agent_write_uses_robot_instead_of_latest_human_editor(self) -> None:
        def snapshot(status: str) -> dict:
            return {
                "sheetId": "sheet-1",
                "headers": news_review_sheet.HEADERS,
                "rows": [{"rowNumber": 8, "values": sheet_row(status, "待审核", "未同步", "", "", "", "机器人新闻")}],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = AuthService(root)
            decisions_path = root / "decisions.jsonl"
            decisions_path.write_text(json.dumps({
                "event": "decision",
                "recorded_at": datetime.now().astimezone().isoformat(),
                "agent_run_id": "agent-run-1",
                "row_number": 8,
                "title": "机器人新闻",
                "automated_fields": ["app"],
                "app_before": "待审核",
                "app_status": "不接受",
                "write_verified": True,
                "writer_identity": "bot",
                "writer_profile": "bot-profile-1",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            with (
                mock.patch.object(web_app, "AUTH", service),
                mock.patch.object(web_app, "NEWS_REVIEW_AUDIT_STATE_PATH", service.state_dir / "news-review-sheet-audit-state.json"),
                mock.patch.object(web_app, "NEWS_SELECTION_DECISIONS_PATH", decisions_path),
                mock.patch.object(web_app, "sheet_edit_events", return_value=[{
                    "event_id": "unrelated-human-event",
                    "create_time_ms": 1787638413000,
                    "operators": [{"open_id": "ou_alice"}],
                }]),
                mock.patch.object(service, "feishu_profile_by_open_id", return_value={
                    "id": "fs-alice", "name": "Alice Chen", "avatar_url": "https://example.com/alice.png",
                }),
            ):
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot("待审核")), [])
                events = web_app.sync_news_review_sheet_audit(snapshot("不接受"))

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["actor_id"], "news-auto-screening-bot")
            self.assertEqual(events[0]["actor_name"], "新闻自动初筛机器人")
            self.assertEqual(events[0]["actor_role"], "SYSTEM")
            self.assertEqual(events[0]["details"]["agent_run_id"], "agent-run-1")
            self.assertNotIn("feishu_event_id", events[0]["details"])

    def test_legacy_robot_footprint_is_corrected_without_touching_earlier_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = AuthService(root)
            decisions_path = root / "decisions.jsonl"
            decisions_path.write_text(json.dumps({
                "event": "decision",
                "recorded_at": "2026-08-28T12:07:01+08:00",
                "agent_run_id": "agent-run-1",
                "row_number": 8,
                "title": "机器人新闻",
                "automated_fields": ["app"],
                "app_before": "待审核",
                "app_status": "不接受",
                "write_verified": True,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            manual = service.record_operation(
                actor={"id": "human-1", "name": "人工审核人"},
                action="news_review.update",
                source="feishu_sheet",
                details={"sheet_row": 8, "target_label": "机器人新闻", "decision_rows": [8], "field": "是否纳入滚动", "before": "待审核", "after": "接受"},
            )
            robot = service.record_operation(
                actor={"id": "human-1", "name": "被误用的人工审核人"},
                action="news_review.update",
                source="feishu_sheet",
                details={"sheet_row": 8, "target_label": "机器人新闻", "decision_rows": [8], "field": "是否纳入滚动", "before": "待审核", "after": "不接受"},
            )
            lines = service.operation_audit_path.read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in lines]
            records[0]["at"] = "2026-08-28T03:42:09+00:00"
            records[1]["at"] = "2026-08-28T04:10:37+00:00"
            service.operation_audit_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")
            with (
                mock.patch.object(web_app, "AUTH", service),
                mock.patch.object(web_app, "NEWS_SELECTION_DECISIONS_PATH", decisions_path),
            ):
                corrected = web_app.repair_news_auto_screening_audit()

            by_id = {item["id"]: item for item in service.operation_audit(limit=10)}
            self.assertEqual(corrected, 1)
            self.assertEqual(by_id[manual["id"]]["actor_id"], "human-1")
            self.assertEqual(by_id[robot["id"]]["actor_id"], "news-auto-screening-bot")
            self.assertTrue(by_id[robot["id"]]["details"]["identity_corrected"])

    def test_new_sheet_rows_establish_a_baseline_without_false_footprints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AuthService(Path(temp_dir))
            snapshot = {
                "sheetId": "sheet-2",
                "headers": news_review_sheet.HEADERS,
                "rows": [{"rowNumber": 9, "values": sheet_row("接受", "待审核", "已纳入", "", "", "", "新增候选")}],
            }
            with (
                mock.patch.object(web_app, "AUTH", service),
                mock.patch.object(web_app, "NEWS_REVIEW_AUDIT_STATE_PATH", service.state_dir / "news-review-sheet-audit-state.json"),
            ):
                self.assertEqual(web_app.sync_news_review_sheet_audit(snapshot), [])
                self.assertEqual(service.operation_audit(), [])

    def test_editor_tracking_status_reports_waiting_then_active(self) -> None:
        with mock.patch.object(web_app, "sheet_edit_events", return_value=[]):
            waiting = web_app.news_review_editor_tracking_status()
        self.assertEqual(waiting["status"], "waiting_for_first_edit")
        self.assertEqual(waiting["receivedEvents"], 0)

        with mock.patch.object(web_app, "sheet_edit_events", return_value=[{
            "event_id": "evt-1",
            "create_time_ms": 1787638413000,
            "operators": [{"open_id": "ou_sheet", "union_id": "on_alice"}],
        }]), mock.patch.object(web_app.AUTH, "feishu_profile_by_open_id", return_value={
            "id": "fs-alice",
            "name": "Alice Chen",
            "avatar_url": "https://example.com/alice.png",
        }) as resolve_profile:
            active = web_app.news_review_editor_tracking_status()
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["lastEventId"], "evt-1")
        self.assertEqual(active["lastEditors"][0]["name"], "Alice Chen")
        self.assertIn("Alice Chen", active["message"])
        resolve_profile.assert_called_once_with("ou_sheet", "on_alice")


if __name__ == "__main__":
    unittest.main()
