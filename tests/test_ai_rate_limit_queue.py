import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_rate_limit


class InteractiveQueueTests(unittest.TestCase):
    def test_waiting_request_stays_queued_and_emits_heartbeats(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "rate-limit.json"
            state_path.write_text(json.dumps({"window": 1, "count": 1}), encoding="utf-8")
            heartbeats = []
            with (
                patch.dict(
                    "os.environ",
                    {
                        "CMHK_INTERNAL_AI_RATE_STATE_PATH": str(state_path),
                        "CMHK_INTERNAL_AI_REQUESTS_PER_MINUTE": "1",
                    },
                ),
                patch("ai_rate_limit.time.time", side_effect=[110.0, 120.4]),
                patch("ai_rate_limit.time.sleep"),
            ):
                waited = ai_rate_limit.wait_for_internal_ai_slot(
                    "competitor-insight",
                    wait_callback=heartbeats.append,
                )

        self.assertGreater(waited, 0)
        self.assertTrue(heartbeats)


if __name__ == "__main__":
    unittest.main()
