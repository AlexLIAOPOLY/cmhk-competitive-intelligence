from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "subscription-admin.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web" / "static" / "subscription-admin.css").read_text(encoding="utf-8")


class SubscriptionAdminTests(unittest.TestCase):
    def test_workspace_has_real_subscription_admin_tab(self):
        self.assertIn('id="workspace-tab-subscriptions"', INDEX)
        self.assertIn('/static/subscription-admin.html?v=1', INDEX)
        self.assertIn('fetch("/api/subscriptions"', SCRIPT)
        self.assertNotIn("订阅服务 UI DEMO", SCRIPT)

    def test_admin_supports_controlled_delivery_and_mobile_layout(self):
        self.assertIn('action: "publish"', SCRIPT)
        self.assertIn('action: "push"', SCRIPT)
        self.assertIn("confirmBulk", SCRIPT)
        self.assertIn("推送台账", SCRIPT)
        self.assertIn("@media (max-width: 560px)", STYLE)

    def test_report_delivery_is_pdf_only(self):
        self.assertIn('value="pdf"', SCRIPT)
        self.assertIn("PDF 文件", SCRIPT)
        self.assertIn('value="pdf_audio"', SCRIPT)
        self.assertIn("PDF + 单独语音", SCRIPT)


if __name__ == "__main__":
    unittest.main()
