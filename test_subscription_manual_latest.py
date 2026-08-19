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
            news = {"items": [{"title": "正式新闻", "summary": "已审核"}]}
            with (
                mock.patch.object(web_app, "ROOT", root),
                mock.patch.object(web_app, "build_status", return_value=status),
                mock.patch("strategic_briefing.public_snapshot", return_value=news),
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
        self.assertEqual(result["service_count"], 3)
        self.assertEqual(result["verified_count"], 3)

    def test_bulk_icon_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, "二次确认"):
            web_app.push_latest_subscription_content(FakeSubscriptionService())


if __name__ == "__main__":
    unittest.main()
