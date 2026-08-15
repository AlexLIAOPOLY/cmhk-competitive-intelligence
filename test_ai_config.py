import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ai_config


class AIConfigTests(unittest.TestCase):
    def test_save_preserves_model_bound_fallback_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "provider": "deepseek",
                        "base_url": ai_config.INTERNAL_AI_BASE_URL,
                        "model": "deepseek-v4",
                        "api_key": "primary-key",
                        "strategy_api_keys": ["primary-key"],
                        "model_api_keys": {"fallback-model": ["fallback-key"]},
                        "extra_parameters": {},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(ai_config, "AI_CONFIG_PATH", config_path):
                ai_config.save_ai_config(
                    {
                        "model": "deepseek-v4",
                        "api_key": "********",
                    }
                )
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(saved["strategy_api_keys"], ["primary-key"])
        self.assertEqual(
            saved["model_api_keys"],
            {"fallback-model": ["fallback-key"]},
        )


if __name__ == "__main__":
    unittest.main()
