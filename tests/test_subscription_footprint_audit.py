import unittest
from unittest import mock

import web_app


class SubscriptionFootprintAuditTests(unittest.TestCase):
    def test_read_only_directory_search_does_not_create_a_footprint(self):
        self.assertIsNone(
            web_app.subscription_operation_audit_payload(
                "searchDirectory",
                {"query": "Alex"},
                {"people": []},
            )
        )

    def test_subscriber_update_keeps_a_readable_target_and_changed_settings(self):
        event = web_app.subscription_operation_audit_payload(
            "update",
            {
                "openId": "ou_subscriber",
                "services": ["news", "weekly"],
                "newsCategories": ["company", "policy"],
                "newsFrequency": "twice_daily",
                "newsItemLimit": 10,
                "reportMode": "pdf_audio",
                "status": "active",
            },
            {"display_name": "Alex LIAO Wang"},
        )

        self.assertEqual(event["action"], "subscription.settings_update")
        self.assertEqual(event["target"], "ou_subscriber")
        self.assertEqual(event["details"]["target_label"], "Alex LIAO Wang")
        self.assertEqual(event["details"]["services"], ["news", "weekly"])

    def test_invite_and_content_sends_include_recipient_evidence(self):
        invite = web_app.subscription_operation_audit_payload(
            "invite",
            {"callbackOpenIds": ["ou_1", "ou_2"]},
            {
                "requested_count": 2,
                "sent_count": 1,
                "failed_count": 1,
                "results": [
                    {"display_name": "Alex LIAO Wang"},
                    {"display_name": "Alan XU Liang"},
                ],
            },
        )
        push = web_app.subscription_operation_audit_payload(
            "pushLatest",
            {"targetOpenId": "ou_1"},
            {"recipient_count": 1, "verified_count": 1, "batch_id": "batch-1"},
        )

        self.assertEqual(invite["action"], "subscription.invite_send")
        self.assertEqual(invite["details"]["target_label"], "Alex LIAO Wang、Alan XU Liang")
        self.assertEqual(invite["details"]["failed_count"], 1)
        self.assertEqual(push["action"], "subscription.content_send")
        self.assertEqual(push["details"]["verified_count"], 1)

    def test_footprint_writer_uses_the_server_bound_actor_and_records_failures(self):
        actor = {"id": "local-admin", "name": "Alex LIAO Wang"}
        with mock.patch.object(web_app.AUTH, "record_operation", return_value={"id": "event-1"}) as record:
            event = web_app.record_subscription_operation_footprint(
                actor=actor,
                action="updateNewsSchedule",
                payload={"enabled": False},
                audit_result="failure",
                error="write failed",
            )

        self.assertEqual(event["id"], "event-1")
        self.assertIs(record.call_args.kwargs["actor"], actor)
        self.assertEqual(record.call_args.kwargs["action"], "subscription.news_schedule_update")
        self.assertEqual(record.call_args.kwargs["result"], "failure")
        self.assertEqual(record.call_args.kwargs["details"]["error"], "write failed")


if __name__ == "__main__":
    unittest.main()
