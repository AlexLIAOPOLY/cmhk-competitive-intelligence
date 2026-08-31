from __future__ import annotations

import unittest

import crawl


class CrawlRunLogTests(unittest.TestCase):
    def test_unsuccessful_http_status_is_failed(self) -> None:
        self.assertEqual(crawl.log_live_fetch_status({"status": 403}), "failed")
        self.assertEqual(crawl.log_live_fetch_status({"status": 404}), "failed")
        self.assertEqual(crawl.log_live_fetch_status({"status": 202}), "success")
        self.assertEqual(crawl.log_live_fetch_status({"status": 200}), "success")
        self.assertEqual(
            crawl.log_live_fetch_status(
                {"status": 200, "evidence_fallback_used": True}
            ),
            "failed",
        )
        self.assertEqual(
            crawl.log_live_fetch_status(
                {"status": 403, "live_fetch_status": "retry_pending"}
            ),
            "retry_pending",
        )


if __name__ == "__main__":
    unittest.main()
