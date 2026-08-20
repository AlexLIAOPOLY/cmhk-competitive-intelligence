from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tts_service import _normalize_and_merge_internal_tts_parts


class InternalTtsMergeTests(unittest.TestCase):
    def test_mixed_response_containers_are_normalized_before_merge(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            self.skipTest("ffmpeg/ffprobe unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "part_001.mp3"
            # Deliberately give WAV bytes an .mp3 suffix. The internal endpoint
            # has historically varied response details across chunks, and the
            # merge path must trust decoding rather than extensions/headers.
            second = root / "part_002.mp3"
            output = root / "merged.mp3"
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6", "-ar", "24000", "-ac", "1", str(first)],
                check=True,
            )
            wav = root / "second.wav"
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=550:duration=0.6", "-ar", "24000", "-ac", "1", str(wav)],
                check=True,
            )
            second.write_bytes(wav.read_bytes())

            _normalize_and_merge_internal_tts_parts(
                [first, second], "测试音频分段合并。", output, ffmpeg, root
            )

            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "json", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual(stream["codec_name"], "mp3")
            self.assertEqual(stream["sample_rate"], "24000")
            self.assertEqual(stream["channels"], 1)
            self.assertGreater(output.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
