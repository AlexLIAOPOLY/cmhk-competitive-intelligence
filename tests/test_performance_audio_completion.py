import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tts_service as tts


class PerformanceAudioCompletionTests(unittest.TestCase):
    def test_alignment_recovery_reuses_waveform_only_for_the_same_document(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts, 'AUDIO_DIR', Path(tmp)), \
             patch.object(tts, '_source_text', return_value='业绩摘要'), \
             patch.object(tts, 'build_audio_summary', return_value='香港电讯企业业务保持增长。' * 30) as summary, \
             patch.object(tts, '_audio_duration_seconds', return_value=180):
            report = Path(tmp) / '业绩摘要.docx'
            report.write_bytes(b'first')
            def synth(text, output, **kwargs):
                output.write_bytes(b'complete waveform')
                return 'internal-tts'
            def align(output, *args, **kwargs):
                output.with_suffix('.timings.json').write_text('{}')
                return {}
            with patch.object(tts, '_synthesize_with_internal_tts', side_effect=synth) as worker, \
                 patch.object(tts, '_write_internal_asr_subtitle_timings', side_effect=RuntimeError('HTTP 400')):
                self.assertFalse(tts.synthesize_report_audio(report)['ok'])
                self.assertFalse(tts.audio_info_for_report(report)['exists'])
                self.assertEqual(tts.synthesize_report_audio(report)['resumeStage'], 'subtitle_alignment')
                self.assertEqual(worker.call_count, 1)
                self.assertEqual(summary.call_count, 1)
                report.write_bytes(b'revised')
                self.assertFalse(tts.synthesize_report_audio(report)['ok'])
                self.assertEqual(worker.call_count, 2)
                with patch.object(tts, '_write_internal_asr_subtitle_timings', side_effect=align):
                    self.assertTrue(tts.synthesize_report_audio(report)['ok'])
                self.assertEqual(worker.call_count, 2)
                self.assertTrue(tts.audio_info_for_report(report)['exists'])

    def test_incomplete_waveform_is_not_retained_for_alignment_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts, 'AUDIO_DIR', Path(tmp)), \
             patch.object(tts, 'build_audio_summary', return_value='香港电讯企业业务保持增长。' * 30), \
             patch.object(tts, '_audio_duration_seconds', return_value=180):
            report = Path(tmp) / '业绩摘要.docx'
            report.write_bytes(b'first')
            def synth(text, output, **kwargs):
                output.write_bytes(b'incomplete waveform')
                return 'internal-tts'
            with patch.object(tts, '_synthesize_with_internal_tts', side_effect=synth) as worker, \
                 patch.object(tts, '_write_internal_asr_subtitle_timings', side_effect=tts.AudioContentIncomplete('未完整播出')):
                self.assertEqual(tts.synthesize_report_audio(report)['resumeStage'], 'synthesis')
                tts.synthesize_report_audio(report)
                self.assertEqual(worker.call_count, 2)

    def test_long_prefix_cannot_pass_when_final_company_and_views_are_missing(self):
        text = "香港电讯业绩增长，数码通维持派息。" * 20 + "最后是香港宽频和有线宽频的表现，以及机构对企业转型的判断。"
        with self.assertRaisesRegex(RuntimeError, "未完整播出"):
            tts._verify_complete_spoken_text(text, text.rsplit("最后是", 1)[0])

    def test_missing_middle_is_rejected_even_if_ending_is_present(self):
        text = "中国移动公布每股派息。中国电信扩充算力服务。香港电讯企业收入增长。数码通降低资本开支。"
        with self.assertRaisesRegex(RuntimeError, "未完整播出"):
            tts._verify_complete_spoken_text(text, text.replace("中国电信扩充算力服务。香港电讯企业收入增长。", ""))

    def test_complete_spoken_numbers_allow_minor_asr_brand_variation(self):
        text = "香港电讯企业收入增长8%，资本开支10.42亿港元。数码通资本开支降低21%。"
        spoken = tts.prepare_tts_text(text).replace("电讯", "电信")
        check = tts._verify_complete_spoken_text(text, spoken)
        self.assertGreater(check["matchedTextFraction"], 0.9)
        self.assertGreater(check["endingMatchedFraction"], 0.9)

    def test_rejected_partial_audio_cannot_write_success_timings(self):
        text = "香港电讯业绩增长。" * 20 + "最后是机构观点和有线宽频的亏损变化。"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.mp3"
            with patch.object(tts, "_internal_asr_timing_payload", return_value={"text": text.rsplit("最后是", 1)[0]}):
                with self.assertRaises(RuntimeError):
                    tts._write_internal_asr_subtitle_timings(output, text, require_complete=True)
            self.assertFalse(output.with_suffix(".timings.json").exists())

    def test_performance_chunks_preserve_every_sentence_and_last_view(self):
        text = "香港电讯企业收入增长百分之八，资本开支十点四二亿港元。" * 20 + "最后是机构对企业转型的判断。"
        requests = []

        def request_audio(request, **kwargs):
            requests.append(json.loads(request.data)["input"])
            return io.BytesIO(b"audio" * 400)

        with tempfile.TemporaryDirectory() as tmp, \
             patch("cmhk.ai.ai_config.load_ai_config", return_value={"base_url": "https://test.invalid", "api_key": "test-only"}), \
             patch("cmhk.ai.ai_config.is_internal_ai_base_url", return_value=True), \
             patch.object(tts, "wait_for_internal_ai_slot"), \
             patch.object(tts, "open_llm_request", side_effect=request_audio), \
             patch.object(tts.shutil, "which", return_value="ffmpeg"), \
             patch.object(tts, "_normalize_and_merge_internal_tts_parts"):
            tts._synthesize_with_internal_tts(text, Path(tmp) / "report.mp3", chunk_chars=360)
        self.assertGreater(len(requests), 1)
        self.assertTrue(all(len(chunk) <= 360 for chunk in requests))
        self.assertEqual("".join(requests), text)
        self.assertTrue(requests[-1].endswith("最后是机构对企业转型的判断。"))


if __name__ == "__main__":
    unittest.main()
