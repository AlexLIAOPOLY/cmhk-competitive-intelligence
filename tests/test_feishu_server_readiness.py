import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_feishu_server_readiness.py"
SPEC = importlib.util.spec_from_file_location("check_feishu_server_readiness", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeishuServerReadinessTests(unittest.TestCase):
    def _run(self, argv: list[str], env: dict[str, str]) -> tuple[int, dict]:
        outputs: list[str] = []

        def fake_lark(argv: list[str]) -> dict:
            if "whoami" in argv:
                return {"identity": "bot", "available": True}
            return {"ok": True}

        with patch.object(sys, "argv", argv), patch.dict(MODULE.os.environ, env, clear=True), patch.object(
            MODULE, "resolve_lark_cli", return_value=sys.executable
        ), patch.object(MODULE, "_run_json", side_effect=fake_lark), patch.object(
            MODULE, "print", side_effect=outputs.append, create=True
        ):
            result = MODULE.main()
        return result, json.loads(outputs[-1])

    def test_require_drive_fails_when_probe_token_is_missing(self):
        result, payload = self._run(
            ["check_feishu_server_readiness.py", "--require-drive", "--env-file", ""],
            {"CMHK_FEISHU_APP_ID": "cli_test", "CMHK_FEISHU_APP_SECRET": "secret"},
        )

        drive_check = next(item for item in payload["checks"] if item["name"] == "drive_probe_configured")
        self.assertEqual(result, 1)
        self.assertFalse(drive_check["ok"])
        self.assertTrue(payload["live"])

    def test_require_drive_executes_read_only_statistics_probe(self):
        result, payload = self._run(
            ["check_feishu_server_readiness.py", "--require-drive", "--env-file", ""],
            {
                "CMHK_FEISHU_APP_ID": "cli_test",
                "CMHK_FEISHU_APP_SECRET": "secret",
                "CMHK_FEISHU_PROFILE": "server-bot",
                "CMHK_FEISHU_DIRECTORY_PROFILE": "server-bot",
                "CMHK_FEISHU_DELIVERY_PROFILE": "server-bot",
                "CMHK_FEISHU_DRIVE_PROBE_TOKEN": "file_test",
            },
        )

        names = {item["name"] for item in payload["checks"]}
        self.assertEqual(result, 0)
        self.assertIn("drive_probe_configured", names)
        self.assertIn("drive_statistics_read", names)


if __name__ == "__main__":
    unittest.main()
