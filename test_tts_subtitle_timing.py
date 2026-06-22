import json
import tempfile
import unittest
from pathlib import Path

from tts_service import _write_moss_subtitle_timings


class _FakeRuntime:
    @staticmethod
    def estimate_voice_clone_inter_chunk_pause_seconds(_text):
        return 0.25


class MossSubtitleTimingTests(unittest.TestCase):
    def test_timings_are_rescaled_to_final_waveform_duration(self):
        result = {
            "sample_rate": 10,
            "text_chunks": ["第一句。第二句。", "第三句。"],
            "chunk_results": [
                {"waveform": [0] * 20},
                {"waveform": [0] * 10},
            ],
            "waveform": [0] * 28,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sample.wav"
            _write_moss_subtitle_timings(output_path, result, _FakeRuntime())
            payload = json.loads(output_path.with_suffix(".timings.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["spokenText"], "第一句。第二句。第三句。")
        self.assertEqual(payload["duration"], 2.8)
        self.assertEqual(payload["cues"][-1]["end"], 2.8)
        self.assertEqual([cue["text"] for cue in payload["cues"]], ["第一句。", "第二句。", "第三句。"])
        self.assertTrue(
            all(
                current["end"] <= following["start"]
                for current, following in zip(payload["cues"], payload["cues"][1:])
            )
        )


if __name__ == "__main__":
    unittest.main()
