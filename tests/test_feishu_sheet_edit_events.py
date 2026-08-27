from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cmhk.integrations.feishu_sheet_edit_events import (
    DEFAULT_EVENT_PATH,
    TARGET_SPREADSHEET_TOKEN,
    capture_drive_file_edit_event,
    sheet_edit_events,
)


class FeishuSheetEditEventTests(unittest.TestCase):
    def test_default_event_path_is_project_auth_directory(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            DEFAULT_EVENT_PATH,
            project_root / "var" / "auth" / "feishu-sheet-edit-events.jsonl",
        )

    def test_target_sheet_operator_ids_are_persisted_and_read(self) -> None:
        data = SimpleNamespace(
            header=SimpleNamespace(
                event_id="evt-1",
                event_type="drive.file.edit_v1",
                create_time="1787638413000",
            ),
            event=SimpleNamespace(
                file_token=TARGET_SPREADSHEET_TOKEN,
                file_type="sheet",
                operator_id_list=[SimpleNamespace(
                    open_id="ou_alice",
                    union_id="on_alice",
                    user_id="alice",
                )],
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            record = capture_drive_file_edit_event(data, path=path)
            self.assertEqual(record["operators"][0]["open_id"], "ou_alice")
            events = sheet_edit_events(path=path, after_ms=1787638412000)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["create_time_ms"], 1787638413000)

    def test_unrelated_sheet_event_is_ignored(self) -> None:
        data = {
            "header": {"event_id": "evt-other", "create_time": "1787638413000"},
            "event": {
                "file_token": "another-sheet",
                "file_type": "sheet",
                "operator_id_list": [{"open_id": "ou_other"}],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            self.assertIsNone(capture_drive_file_edit_event(data, path=path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
