import importlib
import os
import unittest
from unittest.mock import patch


class NewsVoteServiceTests(unittest.TestCase):
    def test_event_secret_prefers_server_environment(self):
        with patch.dict(os.environ, {"CMHK_FEISHU_EVENT_APP_SECRET": "server-secret"}, clear=False):
            module = importlib.import_module("news_vote_service")
            self.assertEqual(module._load_app_secret(), "server-secret")

    def test_default_state_directory_is_project_relative(self):
        module = importlib.import_module("news_vote_service")
        if "CMHK_STRATEGY_STATE_DIR" not in os.environ:
            self.assertEqual(module.STATE_DIR, module.ROOT / "var" / "strategy_briefing")


if __name__ == "__main__":
    unittest.main()
