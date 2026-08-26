import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "web" / "static" / "workspace-tabs.js").read_text(encoding="utf-8")


class CompetitorInsightRecoveryUiTests(unittest.TestCase):
    def test_recovery_preserves_visible_insight_rows(self):
        self.assertIn(
            "function beginCompetitorInsightStream(card, { preserveVisible = false } = {})",
            SCRIPT,
        )
        self.assertIn(
            "const keepVisible = preserveVisible && list.children.length > 0;",
            SCRIPT,
        )
        self.assertIn(
            'card.classList.add(keepVisible ? "is-streaming" : "is-loading");',
            SCRIPT,
        )
        self.assertIn(
            "beginCompetitorInsightStream(card, { preserveVisible: recovery });",
            SCRIPT,
        )

    def test_only_an_empty_or_fresh_stream_clears_rows_and_summary(self):
        start = SCRIPT.index(
            "function beginCompetitorInsightStream(card, { preserveVisible = false } = {})"
        )
        end = SCRIPT.index("function renderCompetitorInsightDraft", start)
        implementation = SCRIPT[start:end]
        self.assertIn("if (!keepVisible) {", implementation)
        self.assertIn("list.replaceChildren();", implementation)
        self.assertIn("beginCompetitorStrategicIndicator();", implementation)


if __name__ == "__main__":
    unittest.main()
