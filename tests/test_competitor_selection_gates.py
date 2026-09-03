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


def complete_metric(company_ids, metric_key, years):
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
    disclosed = {
        (cell["company"], cell["year"])
        for cell in DATA["cells"]
        if cell["company"] in company_ids
        and cell["metric"] == metric_key
        and cell["year"] in visible_years
    }
    return all((company, year) in disclosed for company in company_ids for year in visible_years)


class CompetitorSelectionGateTests(unittest.TestCase):
    def test_company_metric_and_year_controls_require_complete_windows(self):
        self.assertIn("function competitorComparableWindow", SCRIPT)
        self.assertIn("competitorHasCompleteMetric", SCRIPT)
        self.assertIn("function competitorHasComparablePeer", SCRIPT)
        self.assertIn("company.id !== companyId", SCRIPT)
        self.assertIn(".filter((company) => competitorHasComparablePeer(data, company.id, years, metricKey))", SCRIPT)
        self.assertIn("selectedCompanies.includes(company.id) || competitorHasCompleteMetric", SCRIPT)
        self.assertIn("...(data.gaps || [])", SCRIPT)
        self.assertIn('!validYears.has(years) ? "disabled"', SCRIPT)
        self.assertIn("整个年份窗口均有披露值", SCRIPT)
        self.assertIn("逐年数据完整", SCRIPT)
        self.assertIn('classList.toggle("is-disappearing", leaving)', SCRIPT)
        self.assertIn("transitionCompetitorOptions", SCRIPT)
        self.assertIn("visibleCompetitorIds(data, selection.companies, selection.years, selection.metric)", SCRIPT)
        self.assertIn("data.metrics.filter((metric) => competitorHasCompleteMetric", SCRIPT)
        self.assertIn("const comparison = competitorComparableWindow(data, companies, metric, years);", SCRIPT)
        self.assertIn("if (companyIds.length === 1)", SCRIPT)
        self.assertIn("const audited = new Set(metricRows.map", SCRIPT)

    def test_all_gap_metric_from_reported_screenshot_is_filtered_out(self):
        companies = ["3HK", "HKT", "SmarTone"]
        self.assertFalse(complete_metric(companies, "residential_2gbps_plus_customers", 99))
        self.assertTrue(complete_metric(companies, "overview_01_revenue", 99))

    def test_year_window_rejects_every_partial_gap(self):
        companies = ["3HK", "HKT", "SmarTone"]
        self.assertTrue(complete_metric(companies, "5g_penetration", 3))
        self.assertFalse(complete_metric(companies, "5g_penetration", 10))
        self.assertFalse(complete_metric(companies, "5g_penetration", 99))
        self.assertTrue(any(
            row["company"] == "SmarTone"
            and row["metric"] == "5g_penetration"
            and row["year"] == 2020
            for row in DATA["gaps"]
        ))
        self.assertFalse(complete_metric(["SmarTone"], "mobile_postpaid_churn", 3))
        self.assertFalse(complete_metric(["SmarTone"], "mobile_postpaid_churn", 5))
        self.assertFalse(complete_metric(["SmarTone"], "mobile_postpaid_churn", 10))
        self.assertFalse(complete_metric(["SmarTone"], "mobile_postpaid_churn", 99))

    def test_single_company_audited_gap_metric_remains_available(self):
        rows = [
            row
            for row in ROWS
            if row["company"] == "HKBN" and row["metric"] == "residential_arpu"
        ]
        self.assertEqual({row["year"] for row in rows}, set(range(2016, 2026)))
        self.assertFalse(complete_metric(["HKBN"], "residential_arpu", 10))
        gap = next(row for row in DATA["gaps"] if row in rows and row["year"] == 2023)
        self.assertEqual(gap["relatedPublicValue"], "177")

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
                self.assertEqual(years, set(range(2016, 2026)), f"{company}:{metric}")
        expected_5g_years = {
            "3HK": set(range(2020, 2026)),
            "HKT": set(range(2020, 2026)),
            "SmarTone": set(range(2021, 2026)),
        }
        for company, expected in expected_5g_years.items():
            years = {
                cell["year"] for cell in DATA["cells"]
                if cell["company"] == company and cell["metric"] == "5g_penetration"
            }
            self.assertEqual(years, expected, company)
            pre_launch_years = set(range(2016, min(expected)))
            audited_gaps = {
                gap["year"] for gap in DATA["gaps"]
                if gap["company"] == company and gap["metric"] == "5g_penetration"
            }
            self.assertTrue(pre_launch_years.issubset(audited_gaps), company)
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
