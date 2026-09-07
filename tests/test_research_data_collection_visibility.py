from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = (ROOT / "web" / "static" / "research-diagram.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")


class ResearchDataCollectionVisibilityTests(unittest.TestCase):
    def test_worker_cards_separate_research_completion_from_collected_data(self):
        self.assertIn('item?.status === "verified"', RESEARCH)
        self.assertIn('item?.status === "not_applicable"', RESEARCH)
        self.assertIn('"条数据已收集"', RESEARCH)
        self.assertIn('`公司研究完成 ${done}/${task.companies.length}', RESEARCH)
        self.assertIn('研究完成·有缺口', RESEARCH)
        self.assertIn('数据已齐', RESEARCH)

    def test_company_drilldown_shows_collection_coverage_at_a_glance(self):
        self.assertIn('已收集 ${companyCoverage.collected}/${companyCoverage.total} 条数据', RESEARCH)
        self.assertIn('${records.length} 份公司报告 · 已收集 ${coverage.collected}/${coverage.total} 条数据', RESEARCH)
        self.assertIn('分公司数据收集覆盖率', RESEARCH)
        self.assertIn('公司研究完成不等于数据已收齐', RESEARCH)
        self.assertIn('${companyCoverageOverview(node)}', RESEARCH)
        self.assertIn('<details class="research-company"><summary>', RESEARCH)

    def test_research_asset_cache_version_is_bumped(self):
        self.assertIn('/static/research-diagram.js?v=9', INDEX)


if __name__ == "__main__":
    unittest.main()
