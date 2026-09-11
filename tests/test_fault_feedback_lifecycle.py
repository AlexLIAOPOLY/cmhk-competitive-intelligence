from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "workspace-tabs.css").read_text(encoding="utf-8")


class FaultFeedbackLifecycleTests(unittest.TestCase):
    def test_terminal_feedback_can_be_closed_and_auto_dismisses(self):
        self.assertIn("data-dismiss-fault-feedback", SCRIPT)
        self.assertIn('current.tone === "error" ? 8000 : 5000', SCRIPT)
        self.assertIn('current.tone !== "progress"', SCRIPT)
        self.assertIn("state.faultFeedback !== shownFeedback", SCRIPT)
        self.assertIn(".fault-action-feedback > button", STYLE)


if __name__ == "__main__":
    unittest.main()
