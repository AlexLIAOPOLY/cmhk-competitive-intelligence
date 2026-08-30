from __future__ import annotations

import importlib
import sys
import unittest
from unittest import mock
from urllib.request import Request

sys.modules.setdefault("pdfplumber", mock.MagicMock())

macro = importlib.import_module("scripts.build_macro_policy_knowledge")


class MacroPolicyNetworkRetryTests(unittest.TestCase):
    def test_official_source_timeout_is_retried_before_failure(self) -> None:
        response = mock.MagicMock()
        with (
            mock.patch.object(
                macro,
                "urlopen",
                side_effect=[TimeoutError("transient timeout"), response],
            ) as opener,
            mock.patch.object(macro.time, "sleep") as sleeper,
        ):
            actual = macro._urlopen_with_retry(
                Request("https://example.test/official"), timeout=30
            )

        self.assertIs(actual, response)
        self.assertEqual(opener.call_count, 2)
        sleeper.assert_called_once()


if __name__ == "__main__":
    unittest.main()
