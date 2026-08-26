import os
import unittest
from unittest.mock import patch

from cmhk.integrations.feishu_runtime import (
    lark_cli_env,
    portable_lark_argv,
    resolve_lark_cli,
)


class FeishuRuntimeTests(unittest.TestCase):
    def test_explicit_cli_path_wins(self):
        with patch("cmhk.integrations.feishu_runtime.shutil.which", return_value=None):
            self.assertEqual(
                resolve_lark_cli({"LARK_CLI_PATH": "/srv/cmhk/bin/lark-cli"}),
                "/srv/cmhk/bin/lark-cli",
            )

    def test_command_is_resolved_without_changing_arguments(self):
        with patch("cmhk.integrations.feishu_runtime.resolve_lark_cli", return_value="/usr/local/bin/lark-cli"):
            self.assertEqual(
                portable_lark_argv(["lark-cli", "whoami", "--as", "bot"]),
                ["/usr/local/bin/lark-cli", "whoami", "--as", "bot"],
            )

    def test_cli_environment_drops_proxy_and_keeps_other_values(self):
        env = lark_cli_env({"HTTPS_PROXY": "http://127.0.0.1:7890", "CMHK_TEST": "yes"})
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertEqual(env["CMHK_TEST"], "yes")
        self.assertEqual(env["LARK_CLI_NO_PROXY"], "1")


if __name__ == "__main__":
    unittest.main()
