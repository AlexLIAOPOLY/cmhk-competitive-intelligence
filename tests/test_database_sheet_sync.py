from __future__ import annotations

import csv
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmhk.integrations.database_sheet_sync import (
    HEADERS,
    LarkSheetGateway,
    _read_sources,
    _stamp_records,
    sync_producer_database_sheet,
)


class _FakeGateway:
    def __init__(self) -> None:
        self.remote: dict[str, dict[str, str]] = {}
        self.last_rows: list[dict[str, str]] = []
        self.created = False

    def read_rows(self) -> tuple[bool, dict[str, dict[str, str]], int]:
        last = max([1, *[int(row["__row_number"]) for row in self.remote.values()]])
        return self.created, {key: dict(value) for key, value in self.remote.items()}, last

    def upsert_rows(
        self,
        rows: list[dict[str, str]],
        *,
        existed: bool,
        remote_rows: dict[str, dict[str, str]],
        last_row: int,
    ) -> dict[str, object]:
        del remote_rows, last_row
        self.created = True
        self.last_rows = [dict(row) for row in rows]
        self.remote = {
            row["同步鍵"]: {
                **{header: str(row.get(header) or "") for header in HEADERS},
                "__row_number": str(index),
            }
            for index, row in enumerate(rows, start=2)
        }
        return {
            "ok": True,
            "created": not existed,
            "written": len(rows),
            "row_count": len(rows),
            "sheet_title": "競對資料庫",
            "sheet_url": "https://example.test/sheet",
            "last_row": len(rows) + 1,
            "readback_verified": True,
        }

    def clear_core_rows(self, rows: list[dict[str, str]]) -> int:
        cleared = {int(row["__row_number"]) for row in rows}
        self.remote = {
            key: row
            for key, row in self.remote.items()
            if int(row["__row_number"]) not in cleared
        }
        return len(rows)


class DatabaseSheetSyncTests(unittest.TestCase):
    def test_retry_safe_gateway_call_recovers_from_transient_timeout(self) -> None:
        gateway = object.__new__(LarkSheetGateway)
        gateway.cli = "lark-cli"
        gateway.identity = "bot"
        gateway.profile = "server-bot"
        outcomes = [
            subprocess.CompletedProcess([], 1, stdout="", stderr='{"type":"network","message":"timeout"}'),
            subprocess.CompletedProcess([], 0, stdout='{"ok":true,"data":{}}', stderr=""),
        ]

        with patch(
            "cmhk.integrations.database_sheet_sync.subprocess.run", side_effect=outcomes
        ) as run, patch("cmhk.integrations.database_sheet_sync.time.sleep"):
            payload = gateway._run(["sheets", "+workbook-info"], retry_safe=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(run.call_count, 2)

    def test_retry_safe_gateway_call_recovers_from_timeout_exception(self) -> None:
        gateway = object.__new__(LarkSheetGateway)
        gateway.cli = "lark-cli"
        gateway.identity = "bot"
        gateway.profile = "server-bot"
        outcomes = [
            subprocess.TimeoutExpired(["lark-cli"], 240),
            subprocess.CompletedProcess([], 0, stdout='{"ok":true,"data":{}}', stderr=""),
        ]

        with patch(
            "cmhk.integrations.database_sheet_sync.subprocess.run", side_effect=outcomes
        ) as run, patch("cmhk.integrations.database_sheet_sync.time.sleep"):
            payload = gateway._run(["sheets", "+workbook-info"], retry_safe=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(run.call_count, 2)

    def test_retry_safe_gateway_call_recovers_from_sheet_revision_conflict(self) -> None:
        gateway = object.__new__(LarkSheetGateway)
        gateway.cli = "lark-cli"
        gateway.identity = "user"
        gateway.profile = ""
        outcomes = [
            subprocess.CompletedProcess(
                [],
                1,
                stdout="",
                stderr='{"code":900015205,"message":"cs recommited, rev is 43469"}',
            ),
            subprocess.CompletedProcess([], 0, stdout='{"ok":true,"data":{}}', stderr=""),
        ]

        with patch(
            "cmhk.integrations.database_sheet_sync.subprocess.run", side_effect=outcomes
        ) as run, patch("cmhk.integrations.database_sheet_sync.time.sleep"):
            payload = gateway._run(["sheets", "+cells-set"], retry_safe=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(run.call_count, 2)

    def _dataset(self, root: Path) -> tuple[Path, Path]:
        dataset = root / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
        dataset.mkdir(parents=True)
        source = dataset / "quarterly_metrics.csv"
        fields = [
            "subject",
            "period",
            "grain",
            "metric_key",
            "metric_zh",
            "value",
            "official_value",
            "unit",
            "verification_status",
            "verification_note",
            "official_source_url",
        ]
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "subject": "CMHK",
                    "period": "FY2025",
                    "grain": "annual",
                    "metric_key": "revenue",
                    "metric_zh": "收入",
                    "value": "100",
                    "official_value": "100",
                    "unit": "HKD million",
                    "verification_status": "official_match",
                    "verification_note": "官方年報",
                    "official_source_url": "https://example.test/report.pdf",
                }
            )
        (dataset / "manifest.json").write_text(
            json.dumps({"id": "quarterly-test", "row_count": 1}), encoding="utf-8"
        )
        return dataset, source

    def _tariff_dataset(self, root: Path, *, captured_at: str) -> tuple[Path, Path]:
        dataset, _ = self._dataset(root)
        tariff_dir = root / "agent_knowledge" / "competitor_product_tariffs"
        tariff_dir.mkdir(parents=True)
        source = tariff_dir / "product_tariffs_formal_agent_records.csv"
        fields = [
            "记录键",
            "品牌",
            "套餐名称",
            "期间",
            "抓取/生效时间",
            "来源URL",
            "月费_HKD",
            "计价单位",
            "核验状态",
            "证据摘录",
        ]
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "记录键": "stable-plan-1",
                    "品牌": "HKBN",
                    "套餐名称": "1000M 家居寬頻",
                    "期间": "current",
                    "抓取/生效时间": captured_at,
                    "来源URL": "https://example.test/plan",
                    "月费_HKD": "198",
                    "计价单位": "HKD／月",
                    "核验状态": "official_public_source_structured",
                    "证据摘录": "官方月費",
                }
            )
        (tariff_dir / "manifest.json").write_text(
            json.dumps({"id": "tariff-test", "row_count": 1}), encoding="utf-8"
        )
        return dataset, source

    @staticmethod
    def _row(source: Path) -> dict[str, str]:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            return next(csv.DictReader(handle))

    @staticmethod
    def _replace_local_value(source: Path, value: str) -> None:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["value"] = value
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_bidirectional_override_preserves_official_value_and_restores_new_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset, source = self._dataset(root)
            state = root / "state.json"
            gateway = _FakeGateway()

            initial = sync_producer_database_sheet(
                dataset, gateway=gateway, state_path=state
            )
            self.assertEqual(initial["row_count"], 1)
            key = gateway.last_rows[0]["同步鍵"]
            self.assertEqual(gateway.last_rows[0]["本地值"], "100")

            gateway.remote[key]["人工修訂值"] = "200"
            gateway.remote[key]["人工備註"] = "管理層已核准的人工口徑"
            reverse = sync_producer_database_sheet(
                dataset, gateway=gateway, state_path=state
            )
            updated = self._row(source)
            self.assertEqual(reverse["changed_source_files"], 1)
            self.assertEqual(updated["value"], "200")
            self.assertEqual(updated["official_value"], "100")
            self.assertEqual(updated["feishu_original_value"], "100")
            self.assertEqual(updated["feishu_override_value"], "200")
            self.assertEqual(gateway.last_rows[0]["人工備註"], "管理層已核准的人工口徑")

            self._replace_local_value(source, "120")
            sync_producer_database_sheet(dataset, gateway=gateway, state_path=state)
            reapplied = self._row(source)
            self.assertEqual(reapplied["value"], "200")
            self.assertEqual(reapplied["feishu_original_value"], "120")

            gateway.remote[key]["人工修訂值"] = ""
            cleared = sync_producer_database_sheet(
                dataset, gateway=gateway, state_path=state
            )
            restored = self._row(source)
            self.assertEqual(cleared["changed_source_files"], 1)
            self.assertEqual(restored["value"], "120")
            self.assertEqual(restored["official_value"], "100")
            self.assertEqual(restored["feishu_override_value"], "")

    def test_local_sidecar_note_change_is_pushed_when_remote_did_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset, _ = self._dataset(root)
            state = root / "state.json"
            gateway = _FakeGateway()
            sync_producer_database_sheet(dataset, gateway=gateway, state_path=state)
            key = gateway.last_rows[0]["同步鍵"]
            payload = json.loads(state.read_text(encoding="utf-8"))
            payload["rows"][key]["note"] = "本地維護備註"
            state.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            sync_producer_database_sheet(dataset, gateway=gateway, state_path=state)

            self.assertEqual(gateway.last_rows[0]["人工備註"], "本地維護備註")

    def test_stamp_records_adopts_matching_remote_timestamp_across_roots(self) -> None:
        record = {header: f"value:{header}" for header in HEADERS}
        record["同步鍵"] = "shared-key"
        record["同步時間"] = ""
        remote = dict(record)
        remote["同步時間"] = "2026-08-31T08:09:04+08:00"
        state = {
            "rows": {
                "shared-key": {
                    "data_hash": "stale-root-hash",
                    "data_synced_at": "2026-08-31T03:32:33+08:00",
                }
            }
        }

        _stamp_records([record], state, {"shared-key": remote})

        self.assertEqual(record["同步時間"], remote["同步時間"])
        self.assertEqual(
            state["rows"]["shared-key"]["data_synced_at"],
            remote["同步時間"],
        )

    def test_pre_publish_preserves_remote_bundle_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset, _ = self._dataset(root)
            state = root / "state.json"
            gateway = _FakeGateway()

            sync_producer_database_sheet(
                dataset,
                release_id="qcm_old",
                gateway=gateway,
                state_path=state,
            )
            key = gateway.last_rows[0]["同步鍵"]
            gateway.remote[key]["版本／快照"] = "bundle:qcm_remote · local-test"

            result = sync_producer_database_sheet(
                dataset,
                preserve_remote_release_marker=True,
                gateway=gateway,
                state_path=state,
            )

            self.assertEqual(result["release_id"], "")
            self.assertEqual(
                gateway.last_rows[0]["版本／快照"],
                "bundle:qcm_remote · local-test",
            )

    def test_tariff_sync_key_ignores_capture_time_and_compacts_legacy_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset, tariff = self._tariff_dataset(
                root, captured_at="2026-08-30T03:00:00+08:00"
            )
            state = root / "state.json"
            gateway = _FakeGateway()

            initial = sync_producer_database_sheet(
                dataset, gateway=gateway, state_path=state
            )
            tariff_row = next(
                row for row in gateway.last_rows if row["資料集"] == "競對產品資費"
            )
            stable_key = tariff_row["同步鍵"]

            source_records, _ = _read_sources(dataset)
            legacy_key = next(
                row["__legacy_sync_key"]
                for row in source_records
                if row["資料集"] == "競對產品資費"
            )
            active = gateway.remote.pop(stable_key)
            active["同步鍵"] = legacy_key
            active["人工備註"] = "保留人工備註"
            gateway.remote[legacy_key] = active
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            state_payload["rows"][legacy_key] = state_payload["rows"].pop(stable_key)
            state.write_text(json.dumps(state_payload, ensure_ascii=False), encoding="utf-8")

            tombstone = dict(active)
            tombstone["同步鍵"] = "legacy-volatile-key"
            tombstone["資料狀態"] = "本地已下線"
            tombstone["人工備註"] = ""
            tombstone["__row_number"] = "99"
            gateway.remote["legacy-volatile-key"] = tombstone

            migrated = sync_producer_database_sheet(
                dataset, gateway=gateway, state_path=state
            )
            tariff_row = next(
                row for row in gateway.last_rows if row["資料集"] == "競對產品資費"
            )
            self.assertEqual(migrated["migrated_sync_key_count"], 1)
            self.assertEqual(migrated["compacted_tombstone_count"], 1)
            self.assertEqual(tariff_row["同步鍵"], stable_key)
            self.assertEqual(tariff_row["人工備註"], "保留人工備註")
            self.assertNotIn("legacy-volatile-key", gateway.remote)

            with tariff.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = list(reader.fieldnames or [])
                rows = list(reader)
            rows[0]["抓取/生效时间"] = "2026-08-31T03:00:00+08:00"
            with tariff.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            refreshed = sync_producer_database_sheet(
                dataset, gateway=gateway, state_path=state
            )
            tariff_row = next(
                row for row in gateway.last_rows if row["資料集"] == "競對產品資費"
            )

            self.assertEqual(tariff_row["同步鍵"], stable_key)
            self.assertEqual(refreshed["migrated_sync_key_count"], 0)
            self.assertEqual(refreshed["compacted_tombstone_count"], 0)
            self.assertEqual(initial["compacted_tombstone_count"], 0)

    def test_sheet_reader_tolerates_extra_reordered_columns_and_manual_rows(
        self,
    ) -> None:
        layout = (HEADERS[0], "使用者新增欄", *HEADERS[1:])
        values = {header: f"v:{header}" for header in HEADERS}
        values["同步鍵"] = "stable-key-1"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([f"[row=1] {layout[0]}", *layout[1:]])
        writer.writerow(
            [f"[row=2] {values[layout[0]]}", "保留內容", *[values[item] for item in layout[2:]]]
        )
        writer.writerow(["[row=3] 手動列", "使用者內容", *([""] * (len(layout) - 2))])

        gateway = object.__new__(LarkSheetGateway)
        gateway.token = "token"
        gateway.title = "競對資料庫"
        gateway.sheet_headers = HEADERS
        gateway.sheet_col_count = len(layout)
        gateway.ignored_manual_rows = 0
        gateway.ignored_duplicate_rows = 0
        gateway._sheet = lambda: {"column_count": len(layout)}  # type: ignore[method-assign]
        gateway._run = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
            "ok": True,
            "data": {
                "annotated_csv": buffer.getvalue(),
                "current_region": "A1:P3",
            },
        }

        existed, rows, last_row = gateway.read_rows()

        self.assertTrue(existed)
        self.assertEqual(last_row, 3)
        self.assertEqual(rows["stable-key-1"]["使用者新增欄"], "保留內容")
        self.assertEqual(gateway.ignored_manual_rows, 1)
        writes = gateway._row_writes(
            {header: values[header] for header in HEADERS},
            row_number=5,
            remote=None,
        )
        self.assertEqual([item["range"] for item in writes], ["A5:A5", "C5:P5"])

    def test_sheet_reader_fails_closed_on_duplicate_sync_keys(self) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([f"[row=1] {HEADERS[0]}", *HEADERS[1:]])
        values = {header: f"v:{header}" for header in HEADERS}
        values["同步鍵"] = "duplicate-key"
        writer.writerow([f"[row=2] {values[HEADERS[0]]}", *[values[item] for item in HEADERS[1:]]])
        writer.writerow([f"[row=3] {values[HEADERS[0]]}", *[values[item] for item in HEADERS[1:]]])
        gateway = object.__new__(LarkSheetGateway)
        gateway.token = "token"
        gateway.title = "競對資料庫"
        gateway.sheet_headers = HEADERS
        gateway.sheet_col_count = len(HEADERS)
        gateway.ignored_manual_rows = 0
        gateway.ignored_duplicate_rows = 0
        gateway._sheet = lambda: {"column_count": len(HEADERS)}  # type: ignore[method-assign]
        gateway._run = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
            "ok": True,
            "data": {"annotated_csv": buffer.getvalue(), "current_region": "A1:O3"},
        }

        with self.assertRaisesRegex(RuntimeError, "重複同步鍵"):
            gateway.read_rows()

    def test_full_readback_catches_non_sample_field_mismatch(self) -> None:
        rows = [
            {header: f"{header}-{index}" for header in HEADERS}
            for index in range(5)
        ]
        for index, row in enumerate(rows):
            row["同步鍵"] = f"key-{index}"
        readback = {
            row["同步鍵"]: {**row, "__row_number": str(index + 2)}
            for index, row in enumerate(rows)
        }
        readback["key-1"]["來源"] = "漏寫的非抽樣欄位"
        gateway = object.__new__(LarkSheetGateway)
        gateway.title = "競對資料庫"
        gateway.token = "token"
        gateway.identity = "bot"
        gateway.sheet_headers = HEADERS
        gateway.sheet_col_count = len(HEADERS)
        gateway.ignored_manual_rows = 0
        gateway.ignored_duplicate_rows = 0
        gateway._write_batches = lambda _writes: None  # type: ignore[method-assign]
        gateway._styles = lambda _rows, _last: None  # type: ignore[method-assign]
        gateway.read_rows = lambda: (True, readback, 6)  # type: ignore[method-assign]

        with patch("cmhk.integrations.database_sheet_sync.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "完整回讀"):
                gateway.upsert_rows(
                    rows,
                    existed=True,
                    remote_rows=readback,
                    last_row=6,
                )

        self.assertGreaterEqual(sleep.call_count, 1)

    def test_full_readback_retries_until_sheet_is_consistent(self) -> None:
        row = {header: f"value:{header}" for header in HEADERS}
        row["同步鍵"] = "eventual-key"
        stale = {**row, "來源": "stale", "__row_number": "2"}
        current = {**row, "__row_number": "2"}
        readbacks = iter(
            [
                (True, {"eventual-key": stale}, 2),
                (True, {"eventual-key": current}, 2),
            ]
        )
        gateway = object.__new__(LarkSheetGateway)
        gateway.title = "競對資料庫"
        gateway.token = "token"
        gateway.identity = "bot"
        gateway.sheet_headers = HEADERS
        gateway.sheet_col_count = len(HEADERS)
        gateway.ignored_manual_rows = 0
        gateway.ignored_duplicate_rows = 0
        gateway._write_batches = lambda _writes: None  # type: ignore[method-assign]
        gateway._styles = lambda _rows, _last: None  # type: ignore[method-assign]
        gateway.read_rows = lambda: next(readbacks)  # type: ignore[method-assign]

        with patch("cmhk.integrations.database_sheet_sync.time.sleep") as sleep:
            result = gateway.upsert_rows(
                [row],
                existed=True,
                remote_rows={"eventual-key": stale},
                last_row=2,
            )

        self.assertTrue(result["readback_verified"])
        self.assertEqual(sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
