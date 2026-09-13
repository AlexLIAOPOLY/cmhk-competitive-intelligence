import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from cmhk.reporting import report_audio_pipeline as pipeline
import tts_service as tts


class AutomaticReportAudioTests(unittest.TestCase):
    def test_retry_and_handoff_keeps_exact_report_path(self):
        synth = Mock(side_effect=[{'ok': False, 'error': 'offline'}, {'ok': True, 'audio': {'exists': True, 'name': 'report.mp3'}}])
        lines = []
        path = Path('/tmp/本轮周报.docx')
        result = pipeline.generate_report_audio(path, synthesize=synth, progress=lambda line, **kw: lines.append(line))
        self.assertTrue(result['ok'])
        self.assertEqual(synth.call_count, 2)
        self.assertEqual(synth.call_args.args, (path,))
        self.assertEqual(pipeline.audio_result_from_output('\n'.join(lines))['report_path'], str(path.resolve()))

    def test_exhausted_retry_is_not_success(self):
        synth = Mock(side_effect=RuntimeError('tts offline'))
        result = pipeline.generate_report_audio(Path('/tmp/report.docx'), synthesize=synth, progress=lambda *a, **k: None)
        self.assertFalse(result['ok'])
        self.assertEqual(synth.call_count, 2)

    def test_revision_cache_and_concurrent_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts, 'AUDIO_DIR', Path(tmp)):
            path = Path(tmp) / 'report.docx'
            path.write_bytes(b'first')
            audio = Path(tmp) / 'report.mp3'
            def synth(*args, **kwargs):
                audio.write_bytes(b'audio')
                return {'ok': True, 'audio': {'exists': True, 'name': audio.name}}
            with patch.object(tts, '_synthesize_report_audio', side_effect=synth) as worker:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: tts.synthesize_report_audio(path), range(2)))
                self.assertTrue(all(r['ok'] for r in results))
                self.assertEqual(worker.call_count, 1)
                path.write_bytes(b'changed in place')
                self.assertTrue(tts.synthesize_report_audio(path)['ok'])
                self.assertEqual(worker.call_count, 2)

    def test_report_changed_during_audio_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts, 'AUDIO_DIR', Path(tmp)):
            path = Path(tmp) / 'report.docx'
            path.write_bytes(b'first')
            def synth(*args, **kwargs):
                path.write_bytes(b'new revision')
                return {'ok': True, 'audio': {'exists': True}}
            with patch.object(tts, '_synthesize_report_audio', side_effect=synth):
                self.assertFalse(tts.synthesize_report_audio(path)['ok'])
            self.assertFalse((Path(tmp) / 'report.source.json').exists())

    def test_performance_cli_hands_its_generated_file_to_audio(self):
        import generate_carrier_performance_report as report
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '业绩摘要.docx'
            path.write_bytes(b'docx')
            with patch('sys.argv', ['generate_carrier_performance_report.py']), \
                 patch.object(report, 'render_report', return_value=path), \
                 patch.object(report, 'convert_docx_to_pdf_preview', return_value=None), \
                 patch.object(pipeline, 'generate_report_audio') as audio:
                report.main()
            audio.assert_called_once_with(path)

    def test_web_consumes_generation_audio_result_without_generating_twice(self):
        import web_app
        class Handler:
            def send_response(self, *a): pass
            def send_header(self, *a): pass
            def end_headers(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            for kind, name in [('weekly', '本轮周报.docx'), ('carrier-performance', '本轮业绩摘要.docx')]:
                for ok in [True, False]:
                    path = Path(tmp) / name
                    path.write_bytes(b'docx')
                    payload = {'ok': ok, 'report_path': str(path), 'audio': {'exists': ok}, 'error': '' if ok else 'tts offline'}
                    proc = Mock(pid=1, returncode=0, stdout=iter([' -> '+str(path)+'\n', pipeline.RESULT_PREFIX+json.dumps(payload)+'\n']))
                    events = []
                    with patch.object(web_app.subprocess, 'Popen', return_value=proc) as spawn, \
                         patch.object(web_app, 'build_status', return_value={'outputs': []}), \
                         patch.object(web_app, 'write_sse', side_effect=lambda handler, value: events.append(value)):
                        web_app._ORIGINAL_STREAM_REPORT_GENERATION(Handler(), 'generate_weekly_report.py', kind)
                    self.assertEqual(spawn.call_count, 1)
                    done = events[-1]
                    self.assertTrue(done['reportGenerated'])
                    self.assertEqual(done['completedWithWarnings'], not ok)
                    self.assertEqual(done['audio']['ok'], ok)

    def test_missing_report_cannot_claim_audio_generated(self):
        import web_app
        class Handler:
            def send_response(self, *a): pass
            def send_header(self, *a): pass
            def end_headers(self): pass
        proc = Mock(pid=1, returncode=0, stdout=iter([]))
        events = []
        with patch.object(web_app.subprocess, 'Popen', return_value=proc), \
             patch.object(web_app, 'build_status', return_value={'outputs': []}), \
             patch.object(web_app, 'write_sse', side_effect=lambda handler, value: events.append(value)):
            web_app._ORIGINAL_STREAM_REPORT_GENERATION(Handler(), 'generate_weekly_report.py', 'weekly')
        self.assertFalse(events[-1]['audio']['ok'])
        self.assertTrue(events[-1]['completedWithWarnings'])
