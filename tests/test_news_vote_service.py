import importlib
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class NewsVoteServiceTests(unittest.TestCase):
    def test_sheet_edit_sidecar_uses_runtime_binary(self):
        module = importlib.import_module("news_vote_service")
        self.assertEqual(
            module.SHEET_EDIT_SIDECAR,
            module.ROOT / "var" / "bin" / "lark-cli-drive",
        )

    def test_sheet_edit_listener_uses_dedicated_event_app_profile(self):
        module = importlib.import_module("news_vote_service")
        self.assertEqual(module.SHEET_EDIT_APP_ID, "cli_a9575e70ae799cb2")

    def test_event_secret_prefers_server_environment(self):
        with patch.dict(os.environ, {"CMHK_FEISHU_EVENT_APP_SECRET": "server-secret"}, clear=False):
            module = importlib.import_module("news_vote_service")
            self.assertEqual(module._load_app_secret(), "server-secret")

    def test_default_state_directory_is_project_relative(self):
        module = importlib.import_module("news_vote_service")
        if "CMHK_STRATEGY_STATE_DIR" not in os.environ:
            self.assertEqual(module.STATE_DIR, module.ROOT / "var" / "strategy_briefing")

    def test_drive_edit_handler_uses_canonical_event_path(self):
        module = importlib.import_module("news_vote_service")
        event = object()
        with patch(
            "cmhk.integrations.feishu_sheet_edit_events.capture_drive_file_edit_event"
        ) as capture:
            module._handle_drive_file_edit(event)
        capture.assert_called_once_with(event)

    def test_non_news_card_action_is_forwarded_to_project_handler(self):
        module = importlib.import_module("news_vote_service")
        data = SimpleNamespace(
            header=SimpleNamespace(event_id="evt_project", create_time="1787800000000"),
            event=SimpleNamespace(
                operator=SimpleNamespace(open_id="ou_operator"),
                token="token",
                host="im_message",
                action=SimpleNamespace(
                    value={"action": "cmhk_subscription_save_v1"},
                    tag="button",
                    name="saveSubscriptions",
                    form_value={"services": ["news"]},
                    input_value="",
                    option="",
                    options=[],
                    checked=False,
                    timezone="Asia/Hong_Kong",
                ),
                context=SimpleNamespace(
                    open_message_id="om_project",
                    open_chat_id="oc_project",
                ),
            ),
        )
        with patch.object(
            module,
            "_handle_project_card_action",
            return_value={"status": "subscription_saved"},
        ) as routed:
            response = module._handle_card_action(data)
        routed.assert_called_once_with(data)
        self.assertEqual(response.toast.type, "success")

    def test_flatten_card_action_preserves_callback_identity_and_form(self):
        module = importlib.import_module("news_vote_service")
        data = SimpleNamespace(
            header=SimpleNamespace(event_id="evt_1", create_time="1787800000000"),
            event=SimpleNamespace(
                operator=SimpleNamespace(open_id="ou_operator"),
                token="token_1",
                host="im_message",
                action=SimpleNamespace(
                    value={"action": "cmhk_subscription_save_v1"},
                    tag="button",
                    name="saveSubscriptions",
                    form_value={"services": ["news", "weekly"]},
                    input_value="",
                    option="",
                    options=["news", "weekly"],
                    checked=True,
                    timezone="Asia/Hong_Kong",
                ),
                context=SimpleNamespace(
                    open_message_id="om_1",
                    open_chat_id="oc_1",
                ),
            ),
        )
        with patch.object(module, "_fetch_card_content", return_value='{"schema":"2.0"}'):
            event = module._flatten_card_action(data)
        self.assertEqual(event["event_id"], "evt_1")
        self.assertEqual(event["operator_id"], "ou_operator")
        self.assertEqual(event["source_profile"], module.APP_ID)
        self.assertEqual(json.loads(event["form_value"])["services"], ["news", "weekly"])
        self.assertEqual(event["card_content"], '{"schema":"2.0"}')


if __name__ == "__main__":
    unittest.main()
