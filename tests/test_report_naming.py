import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cmhk.reporting.report_naming import performance_output_path, rename_report_bundle
from cmhk.reporting.pdf_preview import pdf_preview_path
import tts_service as tts


class ReportNamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / '9月10日运营商业绩摘要 (4).docx'
        self.new = self.root / '9月10日运营商业绩摘要（19时35分13秒）.docx'
        self.old.write_bytes(b'report unchanged')
        self.audio = self.root / 'audio'
        self.audio.mkdir()

    def test_names_use_hong_kong_time_and_do_not_reuse_a_same_second_file(self):
        clock = datetime(2026, 9, 11, 8, 12, 13, tzinfo=timezone.utc)
        first = performance_output_path(self.root, clock)
        self.assertEqual(first.name, '9月11日运营商业绩摘要（16时12分13秒）.docx')
        first.touch()
        second = performance_output_path(self.root, clock)
        self.assertNotEqual(first, second)
        self.assertNotIn('(1)', second.name)

    def test_rename_preserves_document_audio_subtitles_preview_and_live_preferences(self):
        before = self.old.stat()
        digest = hashlib.sha256(self.old.read_bytes()).hexdigest()
        for suffix in ['.quality.json', '.docx.quality.json']:
            self.old.with_suffix(suffix).write_text(json.dumps({'reportFile': self.old.name, 'reportSha256': digest}))
        for directory, suffixes in [(self.audio, ['.mp3', '.timings.json', '.source.json']),
                                     (self.audio / '.pending', ['.mp3', '.json'])]:
            directory.mkdir(exist_ok=True)
            for suffix in suffixes:
                (directory / (tts.safe_audio_stem(self.old) + suffix)).write_bytes(b'asset')
        previews = self.root / 'web/static/report-previews'
        previews.mkdir(parents=True)
        pdf_preview_path(self.old, previews).write_bytes(b'PDF')
        db_path = self.root / 'var/subscriptions/subscriptions.sqlite3'
        db_path.parent.mkdir(parents=True)
        with sqlite3.connect(db_path) as db:
            db.execute('CREATE TABLE subscription_admin_preferences(preference_key TEXT, preference_value TEXT)')
            db.execute('CREATE TABLE pending_subscription_deliveries(service TEXT, status TEXT, content_ref TEXT)')
            db.execute('INSERT INTO subscription_admin_preferences VALUES (?,?)', ('performance_report_path', self.old.name))
            db.executemany('INSERT INTO pending_subscription_deliveries VALUES (?,?,?)',
                           [('performance', 'queued', self.old.name), ('performance', 'sent', self.old.name)])
        rename_report_bundle(self.root, self.old, self.new)
        self.assertFalse(self.old.exists())
        self.assertEqual(hashlib.sha256(self.new.read_bytes()).hexdigest(), digest)
        self.assertEqual(self.new.stat().st_mtime_ns, before.st_mtime_ns)
        for suffix in ['.quality.json', '.docx.quality.json']:
            self.assertEqual(json.loads(self.new.with_suffix(suffix).read_text())['reportFile'], self.new.name)
        self.assertEqual((self.audio / (tts.safe_audio_stem(self.new) + '.timings.json')).read_bytes(), b'asset')
        self.assertTrue((self.audio / '.pending' / (tts.safe_audio_stem(self.new) + '.json')).exists())
        self.assertEqual(pdf_preview_path(self.new, previews).read_bytes(), b'PDF')
        with sqlite3.connect(db_path) as db:
            self.assertEqual(db.execute('SELECT preference_value FROM subscription_admin_preferences').fetchone()[0], self.new.name)
            self.assertEqual(db.execute('SELECT content_ref FROM pending_subscription_deliveries ORDER BY rowid').fetchall(),
                             [(self.new.name,), (self.old.name,)])

    def test_asset_collision_preserves_both_documents_and_audio(self):
        collision = self.audio / (tts.safe_audio_stem(self.new) + '.mp3')
        collision.write_bytes(b'existing other audio')
        (self.audio / (tts.safe_audio_stem(self.old) + '.mp3')).write_bytes(b'old audio')
        with self.assertRaises(ValueError):
            rename_report_bundle(self.root, self.old, self.new)
        self.assertTrue(self.old.exists())
        self.assertFalse(self.new.exists())
        self.assertEqual(collision.read_bytes(), b'existing other audio')

    def test_invalid_quality_rolls_back_renamed_report(self):
        sidecar = self.old.with_suffix('.quality.json')
        sidecar.write_text('{bad JSON')
        with self.assertRaises(ValueError):
            rename_report_bundle(self.root, self.old, self.new)
        self.assertTrue(self.old.exists())
        self.assertFalse(self.new.exists())
        self.assertEqual(sidecar.read_text(), '{bad JSON')

    def test_busy_audio_blocks_rename_before_file_changes(self):
        with (self.audio / (tts.safe_audio_stem(self.old) + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(ValueError, '正在生成音频'):
                rename_report_bundle(self.root, self.old, self.new)
        self.assertTrue(self.old.exists())

    def test_audio_helper_keeps_full_timing_and_fingerprint_suffixes(self):
        with patch.object(tts, 'AUDIO_DIR', self.audio):
            for suffix in ['.timings.json', '.source.json']:
                tts.audio_path_for_report_ext(self.old, suffix).write_text(suffix)
            tts.rename_audio_for_report(self.old, self.new)
            for suffix in ['.timings.json', '.source.json']:
                self.assertEqual(tts.audio_path_for_report_ext(self.new, suffix).read_text(), suffix)

    def test_historical_names_use_matching_archive_time_instead_of_later_mtime(self):
        from scripts.rename_performance_reports import plan_renames
        archive = self.root / 'archives/20260910_193513' / self.old.name
        archive.parent.mkdir(parents=True)
        archive.write_bytes(self.old.read_bytes())
        os.utime(self.old, (2000000000, 2000000000))
        plan = plan_renames(self.root)
        self.assertEqual(plan[0]['new'], self.new.name)
        self.assertIn('20260910_193513', plan[0]['timeEvidence'])

    def test_unknown_historical_time_is_not_invented_from_filesystem(self):
        from scripts.rename_performance_reports import plan_renames
        plan = plan_renames(self.root)
        self.assertEqual(plan[0]['generatedAt'], '')
        self.assertEqual(plan[0]['new'], '9月10日运营商业绩摘要（原始稿）.docx')
