import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web_app


class FaultIncidentApiTests(unittest.TestCase):
    def test_real_incident_ledger_keeps_p1_p2_p3_and_handler(self) -> None:
        state = {
            "incidents": {
                f"incident-{severity.lower()}": {
                    "incident_id": f"incident-{severity.lower()}",
                    "condition_key": f"condition-{severity.lower()}",
                    "status": "open" if severity == "P1" else "resolved",
                    "severity": severity,
                    "task_name": f"{severity} fault",
                    "occurred_at_hkt": f"2026-08-19T0{4-index}:00:00+08:00",
                }
                for index, severity in enumerate(("P1", "P2", "P3"), start=1)
            }
        }
        actions = {
            "handled_messages": {
                "message-1": {
                    "incident_id": "incident-p1",
                    "operator_name": "Alex Liao",
                    "handled_at_hkt": "2026-08-19T09:30:00+08:00",
                }
            }
        }
        web_action = {
            "incident_id": "incident-p2",
            "operator_id": "ou_web_operator",
            "operator_name": "Web Handler",
            "handled_at_hkt": "2026-08-19T10:00:00+08:00",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            actions_path = root / "actions.json"
            web_actions_path = root / "web-actions.jsonl"
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            actions_path.write_text(json.dumps(actions, ensure_ascii=False), encoding="utf-8")
            web_actions_path.write_text(json.dumps(web_action, ensure_ascii=False) + "\n", encoding="utf-8")
            with (
                mock.patch.object(web_app, "PROJECT_MONITOR_STATE_PATH", state_path),
                mock.patch.object(web_app, "PROJECT_MONITOR_ACTIONS_PATH", actions_path),
                mock.patch.object(web_app, "PROJECT_MONITOR_WEB_ACTIONS_PATH", web_actions_path),
                mock.patch.object(web_app.AUTH, "public_user_by_feishu_open_id", return_value={"id": "user-2", "name": "Web Handler", "avatarUrl": "https://example.com/avatar.png"}),
            ):
                records = web_app.load_project_incident_index(limit=100)
                total = web_app.count_project_incidents()

        self.assertEqual({record["severity"] for record in records}, {"P1", "P2", "P3"})
        self.assertTrue(all(record["severity_label"] for record in records))
        self.assertEqual(next(record for record in records if record["severity"] == "P1")["handler_name"], "Alex Liao")
        web_record = next(record for record in records if record["severity"] == "P2")
        self.assertEqual(web_record["handler_name"], "Web Handler")
        self.assertEqual(web_record["handler_avatar_url"], "https://example.com/avatar.png")
        self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
