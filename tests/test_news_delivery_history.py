import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cmhk.services.news_delivery_history import news_delivery_history
from cmhk.services.subscriptions import SubscriptionService, encode_strategic_news_digest


class NewsDeliveryHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = SubscriptionService(runtime_root=Path(self.temp.name))
        self.path = self.service.db_path
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO subscribers(open_id,display_name,created_at,updated_at) VALUES('ou_alice','甲','2026-09-10','2026-09-10')")

    def add(self, key=1, status="verified", service="news", open_id="ou_alice"):
        self.db.execute("INSERT INTO deliveries(id,batch_id,open_id,service,mode,status,message_ids,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (key, f"batch-{key}", open_id, service, "card", status, '["om_message"]' if status == "verified" else '[]', "2026-09-11T01:00:00+08:00"))
        self.db.commit()

    def receipt(self, status="verified", message_id="om_message"):
        self.db.execute("INSERT INTO news_delivery_receipts VALUES(?,?,?,?,?,?,?,?,?,?)",
                        ("ou_alice", "batch-1", "2026-09-10", "2026-09-11", json.dumps([{"title": "实际新闻", "url": "https://example.org"}]),
                         json.dumps({"body": {"elements": [{"tag": "markdown", "content": "实际卡片文字"}]}, "config": {"secret": "not-for-display"}}),
                         '{"selected_count":1,"prepared_at":"2026-09-10T23:00:00+08:00"}', status, message_id, "2026-09-11T01:01:00+08:00"))
        self.db.commit()

    def test_cross_day_delivery_belongs_to_original_task_day(self):
        self.add()
        self.receipt()
        payload = news_delivery_history(self.path, selected_date="2026-09-10")
        self.assertEqual(payload["summary"], {"total": 1, "recipients": 1, "verified": 1, "pending": 0, "issue": 0})
        self.assertEqual(news_delivery_history(self.path, selected_date="2026-09-11")["summary"]["total"], 0)
        self.assertEqual(payload["deliveries"][0]["recipient_name"], "甲")
        self.assertNotIn("card_text", payload["deliveries"][0])

    def test_receipt_text_is_persisted_content_and_does_not_expose_configuration(self):
        self.add(status="sending")
        self.receipt()
        item = news_delivery_history(self.path, delivery_id=1)["delivery"]
        self.assertEqual(item["status"], "verified")
        self.assertEqual(item["card_text"], "实际卡片文字")
        self.assertEqual(item["news_items"][0]["title"], "实际新闻")
        self.assertEqual(item["delivered_at"], "")  # Creation is not a send timestamp.
        self.assertNotIn("not-for-display", json.dumps(item))
        self.assertEqual(item["content_source"], "receipt")

    def test_prepared_and_sent_unverified_are_pending(self):
        self.add(status="sending")
        self.receipt(status="prepared", message_id="")
        self.assertEqual(news_delivery_history(self.path, selected_date="all")["summary"]["pending"], 1)
        self.db.execute("UPDATE news_delivery_receipts SET status='sent',message_id='om_sent'")
        self.db.commit()
        item = news_delivery_history(self.path, delivery_id=1)["delivery"]
        self.assertEqual(item["status"], "sent")
        self.assertEqual(item["status_group"], "pending")

    def test_history_is_complete_news_only_and_read_only(self):
        for i in range(1, 186):
            self.add(i, status="retrying" if i == 1 else "verified")
        self.add(186, service="weekly")
        before = self.db.total_changes
        payload = news_delivery_history(self.path, selected_date="all")
        self.assertEqual(payload["summary"]["total"], 185)
        self.assertEqual(payload["summary"]["pending"], 1)
        self.assertEqual(payload["summary"]["recipients"], 1)
        self.assertEqual(self.db.total_changes, before)
        with self.assertRaises(LookupError):
            news_delivery_history(self.path, delivery_id=186)

    def test_legacy_candidates_are_never_called_a_sent_card(self):
        self.add()
        self.db.execute("INSERT INTO pending_subscription_deliveries(delivery_id,open_id,service,mode,frequency,due_at,body,created_at) VALUES(1,'ou_alice','news','card','once_daily','2026-09-11',?,'2026-09-11')",
                        (encode_strategic_news_digest([{"title": "候选条目"}]),))
        self.db.commit()
        item = news_delivery_history(self.path, delivery_id=1)["delivery"]
        self.assertEqual(item["content_source"], "candidate_archive")
        self.assertEqual(item["card_text"], "")
        self.assertEqual(item["news_items"][0]["title"], "候选条目")

    def test_invalid_date_and_missing_record(self):
        with self.assertRaises(ValueError):
            news_delivery_history(self.path, selected_date="2026-02-31")
        with self.assertRaises(LookupError):
            news_delivery_history(self.path, delivery_id=999)


if __name__ == "__main__":
    unittest.main()
