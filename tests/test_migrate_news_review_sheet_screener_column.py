from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import migrate_news_review_sheet_screener_column as migration


class NewsReviewScreenerMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.runtime_root = Path(self._temporary.name)
        self.state_path = (
            self.runtime_root / "strategy_briefing" / "news_review_sheet_state.json"
        )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_state(self, version: int = 9) -> None:
        self.state_path.write_text(
            json.dumps(
                {
                    "format_version": version,
                    "sheet_id": "active",
                    "sheet_title": "当前候选池",
                    "archive_parts": [
                        {"sheet_id": "archive", "sheet_title": "旧候选池"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _inspection(sheet_id: str, schema: str = "v9") -> dict:
        width = 14 if schema == "v9" else 15
        return {
            "sheetId": sheet_id,
            "sheetTitle": sheet_id,
            "role": "active" if sheet_id == "active" else "archive",
            "schema": schema,
            "rowCount": 100,
            "usedRows": 2,
            "values": [[""] * width, [""] * width],
            "structure": {"data": {}},
            "cellAudit": {"data": {}},
        }

    def test_dry_run_is_read_only_and_reports_both_parts(self) -> None:
        self._write_state()
        inspections = {
            "archive": self._inspection("archive"),
            "active": self._inspection("active"),
        }
        with (
            mock.patch.object(
                migration,
                "_grid_rows_by_sheet",
                return_value={"archive": 100, "active": 100},
            ),
            mock.patch.object(
                migration,
                "inspect_sheet",
                side_effect=lambda part, _rows, **_kwargs: inspections[
                    part["sheet_id"]
                ],
            ),
            mock.patch.object(migration, "_write_backup") as write_backup,
            mock.patch.object(migration, "_insert_screener_column") as insert,
        ):
            result = migration.migrate(self.runtime_root, apply=False)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            [item["sheetId"] for item in result["sheets"]],
            ["archive", "active"],
        )
        write_backup.assert_not_called()
        insert.assert_not_called()
        self.assertEqual(json.loads(self.state_path.read_text())["format_version"], 9)

    def test_apply_publishes_v10_only_after_every_sheet_verifies(self) -> None:
        self._write_state()
        inspections = {
            "archive": self._inspection("archive"),
            "active": self._inspection("active"),
        }
        backup_path = self.runtime_root / "backup.json"
        with (
            mock.patch.object(
                migration,
                "_grid_rows_by_sheet",
                return_value={"archive": 100, "active": 100},
            ),
            mock.patch.object(
                migration,
                "inspect_sheet",
                side_effect=lambda part, _rows, **_kwargs: inspections[
                    part["sheet_id"]
                ],
            ),
            mock.patch.object(
                migration,
                "_write_backup",
                return_value=backup_path,
            ),
            mock.patch.object(migration, "_insert_screener_column") as insert,
            mock.patch.object(migration, "_configure_new_column") as configure,
            mock.patch.object(
                migration,
                "verify_sheet",
                side_effect=lambda item, **_kwargs: {
                    "sheetId": item["sheetId"],
                    "schema": "v10",
                    "shiftedReadbackVerified": True,
                },
            ),
        ):
            result = migration.migrate(self.runtime_root, apply=True)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(insert.call_count, 2)
        self.assertEqual(configure.call_count, 2)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["format_version"], 10)
        self.assertEqual(
            state["screener_column_migration"]["verified_sheet_ids"],
            ["archive", "active"],
        )

    def test_partial_failure_keeps_runtime_on_v9_and_records_failure(self) -> None:
        self._write_state()
        inspections = {
            "archive": self._inspection("archive"),
            "active": self._inspection("active"),
        }
        with (
            mock.patch.object(
                migration,
                "_grid_rows_by_sheet",
                return_value={"archive": 100, "active": 100},
            ),
            mock.patch.object(
                migration,
                "inspect_sheet",
                side_effect=lambda part, _rows, **_kwargs: inspections[
                    part["sheet_id"]
                ],
            ),
            mock.patch.object(
                migration,
                "_write_backup",
                return_value=self.runtime_root / "backup.json",
            ),
            mock.patch.object(migration, "_insert_screener_column"),
            mock.patch.object(migration, "_configure_new_column"),
            mock.patch.object(
                migration,
                "verify_sheet",
                side_effect=[
                    {"sheetId": "archive", "schema": "v10"},
                    RuntimeError("active readback mismatch"),
                ],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "readback mismatch"):
                migration.migrate(self.runtime_root, apply=True)

        self.assertEqual(json.loads(self.state_path.read_text())["format_version"], 9)
        journal = json.loads(
            (
                self.runtime_root
                / "strategy_briefing"
                / "news_review_screener_migration_state.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(journal["status"], "failed")
        self.assertIn("active readback mismatch", journal["error"])

    def test_rerun_does_not_insert_a_second_column_when_sheet_is_already_v10(self) -> None:
        self._write_state(version=10)
        inspections = {
            "archive": self._inspection("archive", "v10"),
            "active": self._inspection("active", "v10"),
        }
        with (
            mock.patch.object(
                migration,
                "_grid_rows_by_sheet",
                return_value={"archive": 100, "active": 100},
            ),
            mock.patch.object(
                migration,
                "inspect_sheet",
                side_effect=lambda part, _rows, **_kwargs: inspections[
                    part["sheet_id"]
                ],
            ),
            mock.patch.object(
                migration,
                "_write_backup",
                return_value=self.runtime_root / "backup.json",
            ),
            mock.patch.object(migration, "_insert_screener_column") as insert,
            mock.patch.object(migration, "_configure_new_column"),
            mock.patch.object(
                migration,
                "verify_sheet",
                side_effect=lambda item, **_kwargs: {
                    "sheetId": item["sheetId"],
                    "schema": "v10",
                },
            ),
        ):
            result = migration.migrate(self.runtime_root, apply=True)

        insert.assert_not_called()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(json.loads(self.state_path.read_text())["format_version"], 10)

    def test_partial_v10_recovery_reuses_the_original_v9_backup(self) -> None:
        self._write_state(version=9)
        old_values = [migration.OLD_HEADERS, ["待审核", *([""] * 13)]]
        backup_path = self.runtime_root / "original-backup.json"
        backup_path.write_text(
            json.dumps(
                {
                    "sheets": [
                        {
                            "sheetId": "archive",
                            "schema": "v9",
                            "values": old_values,
                        },
                        {
                            "sheetId": "active",
                            "schema": "v9",
                            "values": old_values,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        journal_path = (
            self.runtime_root
            / "strategy_briefing"
            / "news_review_screener_migration_state.json"
        )
        journal_path.write_text(
            json.dumps(
                {
                    "migrationId": migration.MIGRATION_ID,
                    "status": "failed",
                    "backupPath": str(backup_path),
                }
            ),
            encoding="utf-8",
        )
        inspections = {
            "archive": self._inspection("archive", "v10"),
            "active": self._inspection("active", "v10"),
        }
        verified_baselines: list[list[list[str]]] = []

        def verify(item, **_kwargs):
            verified_baselines.append(item["expectedV9Values"])
            return {"sheetId": item["sheetId"], "schema": "v10"}

        with (
            mock.patch.object(
                migration,
                "_grid_rows_by_sheet",
                return_value={"archive": 100, "active": 100},
            ),
            mock.patch.object(
                migration,
                "inspect_sheet",
                side_effect=lambda part, _rows, **_kwargs: inspections[
                    part["sheet_id"]
                ],
            ),
            mock.patch.object(
                migration,
                "_write_backup",
                return_value=self.runtime_root / "recovery-backup.json",
            ),
            mock.patch.object(migration, "_insert_screener_column") as insert,
            mock.patch.object(migration, "_configure_new_column"),
            mock.patch.object(migration, "verify_sheet", side_effect=verify),
        ):
            result = migration.migrate(self.runtime_root, apply=True)

        insert.assert_not_called()
        self.assertEqual(verified_baselines, [old_values, old_values])
        self.assertEqual(result["status"], "completed")

    def test_apply_refuses_to_run_while_formal_review_lock_is_held(self) -> None:
        import fcntl

        lock_path = (
            self.runtime_root
            / "strategy_briefing"
            / "cmhk.intelligence.news_review_sheet.lock"
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "未取得运行态排他锁"):
                migration.migrate(self.runtime_root, apply=True)

    def test_exact_shift_readback_validates_values_dropdowns_and_layout(self) -> None:
        old_row = [
            "接受",
            "待审核",
            "已纳入",
            "2026-08-30",
            "香港本地",
            "竞对动态",
            "标题",
            "摘要",
            "媒体",
            "2026-08-30",
            "https://example.com/news",
            "5G",
            "理由",
            "流程",
        ]
        inspection = {
            "sheetId": "active",
            "schema": "v9",
            "rowCount": 100,
            "usedRows": 2,
            "values": [migration.OLD_HEADERS, old_row],
        }
        status_validation = {
            "data_validation": {
                "items": ["待审核", "接受", "暂缓", "不接受"]
            }
        }
        sync_validation = {
            "data_validation": {
                "items": ["未同步", "已纳入", "已移除", "同步失败"]
            }
        }
        with (
            mock.patch.object(
                migration,
                "_read_values",
                return_value=[migration.NEW_HEADERS, ["", *old_row]],
            ),
            mock.patch.object(
                migration,
                "_sheet_info",
                return_value={
                    "data": {
                        "frozen_rows": 1,
                        "frozen_columns": 9,
                        "column_widths": [{"cols": "A:A", "width": 150}],
                    }
                },
            ),
            mock.patch.object(
                migration,
                "_cell_audit",
                return_value={
                    "data": {
                        "ranges": [
                            {
                                "cells": [
                                    [{}, {}, {}, {}],
                                    [{}, status_validation, status_validation, sync_validation],
                                ]
                            }
                        ]
                    }
                },
            ),
        ):
            result = migration.verify_sheet(inspection)

        self.assertTrue(result["shiftedReadbackVerified"])
        self.assertTrue(result["dropdownReadbackVerified"])
        self.assertTrue(result["layoutReadbackVerified"])


if __name__ == "__main__":
    unittest.main()
