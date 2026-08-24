import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web_app


class UiRuntimeIncidentTests(unittest.TestCase):
    def test_incident_state_persists_failure_and_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui_runtime_incidents.json"
            with mock.patch.object(web_app, "UI_RUNTIME_INCIDENTS_PATH", path):
                opened = web_app.record_ui_runtime_incident(
                    "competitor-ai-insight",
                    status="open",
                    error="TimeoutError: timed out",
                    context={"metric": "5g_penetration"},
                )
                resolved = web_app.record_ui_runtime_incident(
                    "competitor-ai-insight",
                    status="resolved",
                )

        self.assertEqual(opened["status"], "open")
        self.assertEqual(opened["failure_count"], 1)
        self.assertEqual(opened["context"]["metric"], "5g_penetration")
        self.assertEqual(resolved["status"], "resolved")
        self.assertTrue(resolved["resolved_at_hkt"])

    def test_fault_resolution_failure_is_monitorable_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui_runtime_incidents.json"
            with mock.patch.object(web_app, "UI_RUNTIME_INCIDENTS_PATH", path):
                opened = web_app.record_ui_runtime_incident(
                    "fault-resolution",
                    status="open",
                    error="RuntimeError: sheet readback failed",
                    context={"incident_id": "abc", "http_status": 409},
                )
                resolved = web_app.record_ui_runtime_incident(
                    "fault-resolution",
                    status="resolved",
                    context={"incident_id": "abc"},
                )

        self.assertEqual(opened["component"], "project-monitor")
        self.assertEqual(opened["severity"], "P2")
        self.assertEqual(opened["status"], "open")
        self.assertEqual(resolved["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
