from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")


class CompetitorInsightSurfaceTests(unittest.TestCase):
    def test_insight_content_floats_without_an_outer_card(self):
        rule = STYLE.split(".competitor-insight {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow: visible", rule)
        self.assertIn("border: 0", rule)
        self.assertIn("border-radius: 0", rule)
        self.assertIn("background: transparent", rule)
        self.assertIn("box-shadow: none", rule)
        self.assertIn("radial-gradient", STYLE)
        self.assertIn("@keyframes competitor-insight-aura", STYLE)

    def test_insight_body_scrolls_inside_its_grid_track(self):
        rule = STYLE.split(".competitor-insight-body {", 1)[1].split("}", 1)[0]

        self.assertIn("min-height: 0", rule)
        self.assertIn("overflow-y: auto", rule)
        self.assertNotIn("height: 100%", rule)

    def test_stream_reconciles_rows_without_rebuilding_completed_paragraphs(self):
        sync_rows = SCRIPT.split("function syncCompetitorInsightRows", 1)[1].split(
            "function parseCompetitorInsightItems", 1
        )[0]
        render_draft = SCRIPT.split("function renderCompetitorInsightDraft", 1)[1].split(
            "function scheduleCompetitorInsightRecovery", 1
        )[0]

        self.assertIn("let li = list.children[index]", sync_rows)
        self.assertIn("if (!li)", sync_rows)
        self.assertIn("copy.textContent !== nextCopy", sync_rows)
        self.assertIn("if (!streaming)", sync_rows)
        self.assertIn("nextCopy.startsWith(currentCopy)", sync_rows)
        self.assertIn("syncCompetitorInsightRows(card, drafts, { streaming: true })", render_draft)
        self.assertNotIn("replaceChildren", render_draft)

    def test_partial_labelled_stream_does_not_backfill_missing_rows(self):
        parser = SCRIPT.split("function parseCompetitorInsightItems", 1)[1].split(
            "function setCompetitorInsightStatus", 1
        )[0]

        self.assertIn("candidates.length < 3 && labelled.size === 0", parser)
        self.assertIn('const sentences = candidates.join(" ").split', parser)
        self.assertNotIn('candidates.join(" ") || text', parser)


if __name__ == "__main__":
    unittest.main()
