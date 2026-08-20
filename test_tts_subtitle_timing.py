import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tts_service import (
    _build_asr_subtitle_cues,
    _write_internal_asr_subtitle_timings,
    _write_moss_subtitle_timings,
    audio_info_for_report,
)


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


class InternalAsrSubtitleTimingTests(unittest.TestCase):
    @staticmethod
    def _segments_for(transcript):
        tokens = [
            "Three",
            *list("香港总收益五十四点四八亿同比增长百分之十七"),
            *list("下一句"),
        ]
        segments = []
        cursor = 0.0
        for token in tokens:
            segments.append({"text": token, "start": cursor, "end": cursor + 0.2})
            cursor += 0.2
        return segments

    def test_asr_tokens_are_grouped_into_sentences_with_character_spans(self):
        transcript = "Three香港总收益五十四点四八亿，同比增长百分之十七。下一句。"
        cues = _build_asr_subtitle_cues(transcript, self._segments_for(transcript))

        self.assertEqual([cue["text"] for cue in cues], [
            "Three香港总收益五十四点四八亿，同比增长百分之十七。",
            "下一句。",
        ])
        self.assertEqual(cues[0]["tokens"][0]["text"], "Three")
        self.assertEqual(cues[0]["tokens"][0]["charStart"], 0)
        self.assertEqual(cues[0]["tokens"][0]["charEnd"], 5)
        self.assertEqual(cues[1]["tokens"][0]["charStart"], 0)
        self.assertLessEqual(cues[0]["end"], cues[1]["start"])

    def test_internal_asr_payload_is_persisted_as_version_two_timings(self):
        transcript = "Three香港总收益五十四点四八亿，同比增长百分之十七。下一句。"
        segments = self._segments_for(transcript)
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.mp3"
            audio_path.write_bytes(b"audio")
            with patch(
                "tts_service._internal_asr_timing_payload",
                return_value={"text": transcript, "duration": 7.2, "segments": segments},
            ):
                payload = _write_internal_asr_subtitle_timings(audio_path)
            saved = json.loads(audio_path.with_suffix(".timings.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["backend"], "internal-qwen3-asr")
        self.assertEqual(saved["spokenText"], transcript)
        self.assertTrue(all(cue.get("tokens") for cue in saved["cues"]))

    def test_low_coverage_asr_result_is_rejected(self):
        transcript = "这是一段完整但没有正确识别的字幕。"
        cues = _build_asr_subtitle_cues(
            transcript,
            [{"text": "错", "start": 0.0, "end": 0.2}],
        )
        self.assertEqual(cues, [])

    def test_zero_duration_numeric_tokens_are_interpolated_and_preserved(self):
        transcript = "收益60.29亿港元，同比增长5%。"
        segments = [
            {"text": "收", "start": 0.0, "end": 0.2},
            {"text": "益", "start": 0.2, "end": 0.4},
            {"text": "6029", "start": 0.4, "end": 0.4},
            {"text": "亿", "start": 1.2, "end": 1.4},
            {"text": "港", "start": 1.4, "end": 1.6},
            {"text": "元", "start": 1.6, "end": 1.8},
            {"text": "同", "start": 1.8, "end": 2.0},
            {"text": "比", "start": 2.0, "end": 2.2},
            {"text": "增", "start": 2.2, "end": 2.4},
            {"text": "长", "start": 2.4, "end": 2.6},
            {"text": "5", "start": 2.6, "end": 2.6},
        ]
        cues = _build_asr_subtitle_cues(transcript, segments)

        self.assertEqual(len(cues), 1)
        numeric_tokens = [
            token for token in cues[0]["tokens"]
            if any(character.isdigit() for character in token["text"])
        ]
        self.assertEqual([token["text"] for token in numeric_tokens], ["60.29", "5%"])
        self.assertTrue(all(token["end"] > token["start"] for token in numeric_tokens))
        self.assertEqual(numeric_tokens[-1]["text"], "5%")

    def test_display_text_preserves_brand_spelling_instead_of_asr_guess(self):
        asr_transcript = "香港电信二零二五年增长百分之四"
        display_text = "香港电讯2025年增长4%"
        segments = [
            {"text": character, "start": index * 0.2, "end": (index + 1) * 0.2}
            for index, character in enumerate(asr_transcript)
            if character != "%"
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.mp3"
            audio_path.write_bytes(b"audio")
            with patch(
                "tts_service._internal_asr_timing_payload",
                return_value={
                    "text": asr_transcript,
                    "duration": 3.0,
                    "segments": segments,
                },
            ):
                payload = _write_internal_asr_subtitle_timings(audio_path, display_text)

        self.assertEqual(payload["spokenText"], display_text)
        self.assertIn("香港电讯", payload["cues"][0]["text"])
        self.assertNotIn("香港电信", payload["cues"][0]["text"])
        numeric_token = next(
            token for token in payload["cues"][0]["tokens"]
            if token["text"].startswith("4")
        )
        self.assertEqual(numeric_token["text"], "4%")

    def test_spoken_percentage_does_not_pull_following_sentence_early(self):
        display_text = "香港二季度GDP按年实质增长4.3%。行业方面，受人工智能算力基建带动。"
        spoken_text = "香港二季度GDP按年实质增长百分之四点三。行业方面受人工智能算力基建带动。"
        segments = []
        cursor = 60.0
        for character in spoken_text:
            if character in "。，":
                continue
            segments.append({"text": character, "start": cursor, "end": cursor + 0.2})
            cursor += 0.2

        cues = _build_asr_subtitle_cues(display_text, segments, spoken_text)

        self.assertEqual(len(cues), 2)
        percentage = next(
            token for token in cues[0]["tokens"]
            if token["text"] == "4.3%"
        )
        self.assertGreater(percentage["end"] - percentage["start"], 0.6)
        self.assertGreaterEqual(cues[1]["start"], cues[0]["end"])
        self.assertGreaterEqual(cues[1]["start"], 63.8)

    def test_audio_info_exposes_precise_token_cues_to_the_frontend(self):
        transcript = "Three香港。"
        cues = [{
            "text": transcript,
            "start": 0.0,
            "end": 0.8,
            "tokens": [{
                "text": "Three",
                "start": 0.0,
                "end": 0.4,
                "charStart": 0,
                "charEnd": 5,
            }],
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_dir = Path(temp_dir)
            report_path = audio_dir / "report.docx"
            (audio_dir / "report.mp3").write_bytes(b"audio")
            (audio_dir / "report.timings.json").write_text(
                json.dumps({"spokenText": transcript, "cues": cues}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch("tts_service.AUDIO_DIR", audio_dir):
                info = audio_info_for_report(report_path)

        self.assertEqual(info["spokenText"], transcript)
        self.assertEqual(info["subtitleCues"][0]["tokens"][0]["text"], "Three")


if __name__ == "__main__":
    unittest.main()
