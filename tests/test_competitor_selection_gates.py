import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "web/static/competitor-workbench-data.json").read_text(encoding="utf-8"))
SCRIPT = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
WINDOWS = (3, 5, 10, 99)
ROWS = [*DATA["cells"], *DATA["gaps"]]
CELLS_BY_COMPANY_METRIC = {}
for _cell in DATA["cells"]:
    CELLS_BY_COMPANY_METRIC.setdefault((_cell["company"], _cell["metric"]), []).append(_cell)


def usable_metric(company_ids, metric_key, years):
    rows = [
        row for row in ROWS
        if row["company"] in company_ids and row["metric"] == metric_key
    ]
    if len({row["company"] for row in rows}) != len(company_ids):
        return False
    if len({row["unit"] for row in rows if row["unit"]}) != 1:
        return False
    all_years = sorted({row["year"] for row in rows})
    if years == 99:
        visible_years = range(all_years[0], all_years[-1] + 1)
    else:
        visible_years = range(all_years[-1] - years + 1, all_years[-1] + 1)
    return any(
        cell["company"] in company_ids
        and cell["metric"] == metric_key
        and cell["year"] in visible_years
        for cell in DATA["cells"]
    )


class CompetitorSelectionGateTests(unittest.TestCase):
    def test_company_metric_and_year_controls_filter_all_empty_inputs(self):
        self.assertIn("function competitorComparableWindow", SCRIPT)
        self.assertIn("competitorHasUsableMetric", SCRIPT)
        self.assertIn("selectedCompanies.includes(company.id) || competitorHasUsableMetric", SCRIPT)
        self.assertIn("...(data.gaps || [])", SCRIPT)
        self.assertIn('!validYears.has(years) ? "disabled"', SCRIPT)
        self.assertIn("至少有一个披露值", SCRIPT)
        self.assertIn("缺值仍展示审计理由", SCRIPT)
        self.assertIn('classList.add("is-disappearing")', SCRIPT)
        self.assertIn("transitionCompetitorOptions", SCRIPT)
        self.assertIn("visibleCompetitorIds(data, selection.companies, selection.years, selection.metric)", SCRIPT)
        self.assertIn("data.metrics.filter((metric) => competitorHasUsableMetric", SCRIPT)
        self.assertIn("const comparison = competitorComparableWindow(data, companies, metric, years);", SCRIPT)

    def test_all_gap_metric_from_reported_screenshot_is_filtered_out(self):
        companies = ["3HK", "HKT", "SmarTone"]
        self.assertFalse(usable_metric(companies, "residential_2gbps_plus_customers", 99))
        self.assertTrue(usable_metric(companies, "overview_01_revenue", 99))

    def test_year_window_requires_a_value_but_keeps_partial_gap_series(self):
        companies = ["3HK", "HKT", "SmarTone"]
        self.assertTrue(usable_metric(companies, "5g_penetration", 99))
        self.assertTrue(any(
            row["company"] == "SmarTone"
            and row["metric"] == "5g_penetration"
            and row["year"] == 2020
            for row in DATA["gaps"]
        ))
        self.assertFalse(usable_metric(["SmarTone"], "mobile_postpaid_churn", 3))
        self.assertTrue(usable_metric(["SmarTone"], "mobile_postpaid_churn", 5))

    def test_three_local_competitors_have_all_metric_year_audit_rows(self):
        rows = [*DATA["cells"], *DATA["gaps"]]
        local_metrics = {
            row["metric"] for row in rows
            if row["company"] in {"3HK", "HKT", "SmarTone"}
            and row["dataset"] == "local_hk_operator_operating_metrics_2016_2025"
        }
        self.assertEqual(len(local_metrics), 31)
        for company in ("3HK", "HKT", "SmarTone"):
            for metric in local_metrics:
                years = {
                    row["year"] for row in rows
                    if row["company"] == company
                    and row["metric"] == metric
                    and row["dataset"] == "local_hk_operator_operating_metrics_2016_2025"
                }
                self.assertEqual(years, set(range(2016, 2026)), f"{company}:{metric}")
        for gap in DATA["gaps"]:
            if gap["company"] not in {"3HK", "HKT", "SmarTone"}:
                continue
            self.assertTrue(gap["reason"])
            self.assertTrue(gap["reviewedSources"])

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
