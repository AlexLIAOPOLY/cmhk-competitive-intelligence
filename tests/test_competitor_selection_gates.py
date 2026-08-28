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
    return len(shared_years) >= 1 and all(
        sum(year in values for year in visible_years) >= 1 for values in company_years
    )


class CompetitorSelectionGateTests(unittest.TestCase):
    def test_company_metric_and_year_controls_do_not_hide_choices_for_history_gaps(self):
        self.assertIn("function competitorComparableWindow", SCRIPT)
        self.assertIn("return new Set(data.companies.map((company) => company.id));", SCRIPT)
        self.assertIn("const comparableMetrics = data.metrics;", SCRIPT)
        self.assertNotIn('!validYears.has(years) ? "disabled"', SCRIPT)
        self.assertIn("年份选择不因历史缺值受限", SCRIPT)
        self.assertIn("const comparison = competitorComparableWindow(data, companies, metric, years);", SCRIPT)

    def test_three_local_competitors_have_ten_years_where_a_numeric_series_exists(self):
        complete = {
            "5g_penetration",
            "overview_01_ebitda",
            "overview_01_net_profit",
            "overview_01_revenue",
        }
        for company in ("3HK", "HKT", "SmarTone"):
            for metric in complete:
                years = {
                    cell["year"] for cell in DATA["cells"]
                    if cell["company"] == company and cell["metric"] == metric
                }
                expected = set(range(2016, 2026))
                if company == "SmarTone" and metric == "5g_penetration":
                    expected.remove(2020)
                self.assertEqual(years, expected, f"{company}:{metric}")
        for company in ("3HK", "HKT"):
            years = {
                cell["year"] for cell in DATA["cells"]
                if cell["company"] == company and cell["metric"] == "mobile_postpaid_churn"
            }
            self.assertEqual(years, set(range(2016, 2026)), company)
        smartone_years = {
            cell["year"] for cell in DATA["cells"]
            if cell["company"] == "SmarTone" and cell["metric"] == "mobile_postpaid_churn"
        }
        self.assertEqual(smartone_years, set(range(2016, 2023)))


if __name__ == "__main__":
    unittest.main()
