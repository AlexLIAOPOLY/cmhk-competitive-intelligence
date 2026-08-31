from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cmhk.crawl.verification import verify_extraction


class _FakeVerificationLlm:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, _messages: object) -> SimpleNamespace:
        return SimpleNamespace(content=self.content)


class CrawlVerificationTests(unittest.TestCase):
    def test_malformed_json_recovers_explicit_partial_fields(self) -> None:
        content = (
            '{"confidence_score": 0.92 '
            '"verification_reason": "来源原文支持提取结果"}'
        )
        with patch(
            "cmhk.crawl.verification.get_verification_llm",
            return_value=_FakeVerificationLlm(content),
        ):
            result = verify_extraction("官方来源原文", {"收入": "100"})

        self.assertEqual(result["confidence_score"], 0.92)
        self.assertEqual(result["verification_reason"], "来源原文支持提取结果")
        self.assertEqual(result["verification_status"], "partial_response")

    def test_unrecoverable_response_remains_explicitly_unavailable(self) -> None:
        with patch(
            "cmhk.crawl.verification.get_verification_llm",
            return_value=_FakeVerificationLlm("not-json"),
        ):
            result = verify_extraction("官方来源原文", {"收入": "100"})

        self.assertEqual(result["confidence_score"], 0.5)
        self.assertEqual(result["verification_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
