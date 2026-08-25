import itertools
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "web/static/competitor-workbench-data.json").read_text(encoding="utf-8"))
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
WINDOWS = (3, 5, 10, 99)
CELLS_BY_COMPANY_METRIC = {}
for _cell in DATA["cells"]:
    CELLS_BY_COMPANY_METRIC.setdefault((_cell["company"], _cell["metric"]), []).append(_cell)


def comparable_window(company_ids, metric_key, years):
    cells = [
        cell
        for company in company_ids
        for cell in CELLS_BY_COMPANY_METRIC.get((company, metric_key), [])
    ]
    if len({cell["company"] for cell in cells}) != len(company_ids):
        return False
    if len({cell["unit"] for cell in cells if cell["unit"]}) != 1:
        return False
    company_years = [
        {cell["year"] for cell in cells if cell["company"] == company}
        for company in company_ids
    ]
    all_years = sorted({cell["year"] for cell in cells})
    common_years = [year for year in all_years if all(year in values for values in company_years)]
    if not common_years:
        return False
    if years == 99:
        visible_years = range(all_years[0], all_years[-1] + 1)
    else:
        visible_years = range(common_years[-1] - years + 1, common_years[-1] + 1)
    shared_years = [year for year in visible_years if all(year in values for values in company_years)]
    return len(shared_years) >= 2 and all(
        sum(year in values for year in visible_years) >= 2 for values in company_years
    )


class CompetitorSelectionGateTests(unittest.TestCase):
    def test_reported_hk_broadband_combination_is_blocked_before_render(self):
        companies = ("HKBN", "HKT", "i-CABLE")
        for years in WINDOWS:
            with self.subTest(years=years):
                self.assertFalse(comparable_window(companies, "consumer_broadband_customers", years))

    def test_every_selectable_combination_meets_result_gate(self):
        metrics = [metric["key"] for metric in DATA["metrics"]]
        selectable = 0
        for metric in metrics:
            companies = sorted({cell["company"] for cell in DATA["cells"] if cell["metric"] == metric})
            for count in range(2, min(6, len(companies)) + 1):
                for selection in itertools.combinations(companies, count):
                    for years in WINDOWS:
                        if comparable_window(selection, metric, years):
                            selectable += 1
                            self.assertTrue(comparable_window(selection, metric, years))
        self.assertGreater(selectable, 0)

    def test_company_metric_and_year_controls_share_the_same_gate(self):
        self.assertIn("function competitorComparableWindow", SCRIPT)
        self.assertIn("sharedVisibleYears.length >= 2", SCRIPT)
        self.assertIn("competitorHasCommonMetric(data, [...selectedCompanies, company.id], years, metricKey)", SCRIPT)
        self.assertIn("competitorHasCommonMetric(data, selection.companies, selection.years, metric.key)", SCRIPT)
        self.assertIn("const windows = years ? [years] : [3, 5, 10, 99];", SCRIPT)
        self.assertIn('!validYears.has(years) ? "disabled"', SCRIPT)
        self.assertIn("const comparison = competitorComparableWindow(data, companies, metric, years);", SCRIPT)


if __name__ == "__main__":
    unittest.main()
