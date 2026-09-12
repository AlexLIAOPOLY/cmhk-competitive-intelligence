import unittest
from data_curation.research_tables import quarterly_cells, extract_configured_table
from data_curation.six_agent_research import validate_fact

URL = "https://www.chinaunicom.com.hk/en/ir/highlights.php"
TEXT = ("China Unicom (Hong Kong) Limited Financial Highlights Quarterly "
        "1Q2026 2Q2026 Operating Revenue (RMB Millions) 102,824 98,540 "
        "EBITDA (RMB Millions) 24,331 23,085 "
        "Profit Attributable to Equity Shareholders of the Company (RMB Millions) 4,885 4,583 Basic EPS")


class ResearchTableTests(unittest.TestCase):
    def baseline(self, metric, period="Q1 2026"):
        return {metric: [{"period": period, "value": 1, "unit": "millions CNY"}]}

    def test_target_period_and_value_are_selected_from_same_column(self):
        for metric, value in [("EBITDA", "23,085"), ("净利润", "4,583")]:
            item = extract_configured_table("中国联通", metric,
                {URL: {"opened": True, "official": True, "text": TEXT}}, self.baseline(metric))
            self.assertEqual((item["period"], item["value"], item["status"]), ("2Q2026", value, "verified"))

    def test_missing_cell_or_duplicate_period_makes_table_ambiguous(self):
        for text in [TEXT.replace("24,331 ", ""), TEXT.replace("1Q2026", "2Q2026")]:
            self.assertEqual(quarterly_cells("中国联通", "EBITDA", URL, text), [])

    def test_wrong_issuer_or_unopened_page_cannot_supply_proof(self):
        for page in [{"opened": False, "official": True, "text": TEXT},
                     {"opened": True, "official": False, "text": TEXT},
                     {"opened": True, "official": True, "text": TEXT.replace("China Unicom", "Other Company")}]:
            self.assertIsNone(extract_configured_table("中国联通", "EBITDA", {URL: page}, self.baseline("EBITDA")))

    def test_annual_or_already_stored_quarter_is_not_added(self):
        for period in ["FY2025", "Q2 2026"]:
            self.assertIsNone(extract_configured_table("中国联通", "EBITDA",
                {URL: {"opened": True, "official": True, "text": TEXT}}, self.baseline("EBITDA", period)))

    def test_wrong_column_value_fails_even_when_metric_label_is_present(self):
        item = quarterly_cells("中国联通", "EBITDA", URL, TEXT)[-1]
        item["value"] = "24,331"
        result = validate_fact(item, "中国联通", ["EBITDA"],
            {URL: {"opened": True, "official": True, "text": TEXT}})
        self.assertEqual(result["status"], "conflict")

    def test_long_numeric_row_uses_explicit_columns_instead_of_proximity(self):
        periods = " ".join(f"{q}Q{y}" for y in range(2020, 2026) for q in range(1, 5))
        values = " ".join(str(10000 + n) for n in range(24))
        text = f"China Unicom (Hong Kong) Limited Quarterly {periods} Operating Revenue (RMB Millions) {values} Profit Attributable to Equity Shareholders of the Company (RMB Millions) {values} Basic EPS"
        item = quarterly_cells("中国联通", "净利润", URL, text)[-1]
        self.assertEqual(validate_fact(item, "中国联通", ["净利润"],
            {URL: {"opened": True, "official": True, "text": text}})["status"], "verified")
