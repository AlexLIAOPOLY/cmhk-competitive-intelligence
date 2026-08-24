import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web_app


class FakeSubscriptionService:
    def __init__(self):
        self.calls = []

    def list_summary(self):
        return {
            "subscribers": [
                {
                    "open_id": "ou_target123",
                    "status": "active",
                    "services": ["weekly", "performance", "news"],
                    "news_item_limit": 5,
                    "news_categories": ["竞对动态", "政策监管"],
                },
                {
                    "open_id": "ou_paused123",
                    "status": "paused",
                    "services": ["weekly"],
                },
            ]
        }

    def push(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "recipient_count": 1,
            "verified_count": 1,
            "failed_count": 0,
        }


class LatestSubscriptionPushTests(unittest.TestCase):
    def test_person_icon_uses_latest_content_and_current_subscription_preferences(self):
        service = FakeSubscriptionService()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            weekly = root / "weekly.docx"
            performance = root / "performance.docx"
            weekly.write_bytes(b"weekly")
            performance.write_bytes(b"performance")
            status = {
                "outputs": [
                    {"reportType": "weekly", "path_str": weekly.name},
                    {"reportType": "carrier-performance", "path_str": performance.name},
                ]
            }
            news = [
                {"title": f"正式新闻{index}", "summary": "已审核", "category": "竞对动态" if index % 2 else "行业动态", "published_at": f"2026-08-19T{index:02d}:00:00+08:00"}
                for index in range(12)
            ]
            with (
                mock.patch.object(web_app, "ROOT", root),
                mock.patch.object(web_app, "build_status", return_value=status),
                mock.patch("strategic_briefing.latest_reviewed_news", return_value=news) as latest,
            ):
                result = web_app.push_latest_subscription_content(
                    service,
                    target_open_id="ou_target123",
                )

        self.assertEqual([item["service"] for item in service.calls], ["weekly", "performance", "news"])
        self.assertTrue(all(item["target_open_id"] == "ou_target123" for item in service.calls))
        self.assertEqual(service.calls[0]["mode"], "pdf_audio")
        self.assertEqual(service.calls[1]["mode"], "pdf_audio")
        self.assertEqual(service.calls[2]["mode"], "text")
        self.assertEqual(service.calls[2]["title"], "CMHK战略新闻｜最新5条｜竞对动态、政策监管")
        self.assertEqual(service.calls[2]["body"].count('"title"'), 5)
        self.assertNotIn('"category":"行业动态"', service.calls[2]["body"])
        latest.assert_called_once_with()
        self.assertEqual(result["service_count"], 3)
        self.assertEqual(result["verified_count"], 3)

    def test_bulk_icon_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, "二次确认"):
            web_app.push_latest_subscription_content(FakeSubscriptionService())


if __name__ == "__main__":
    unittest.main()
