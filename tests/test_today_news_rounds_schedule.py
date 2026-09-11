import json
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch

import strategic_briefing as briefing
import web_app


class TodayNewsRoundsScheduleTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        for obj,name,value in ((web_app,'STRATEGIC_BRIEFING_RUNS_DIR',self.root),
                               (briefing,'SCAN_TIMES',(time(3),time(14)))):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.today=datetime.now(briefing.HKT).strftime('%Y-%m-%d')

    def archive(self,day,clock,count,*,filename=None,slot=None):
        name=filename or f'{day}@{clock.replace(":","-")}.json'
        (self.root/name).write_text(json.dumps({'slot':slot or f'{day}@{clock}',
            'status':'completed','review_sheet':{'input_count':count,'batch_count':count,'new_count':count}}))

    def test_current_day_uses_configured_three_and_fourteen_not_legacy_or_manual(self):
        for clock,count in [('03:00',179),('14:00',42),('09:00',999),('15:00',888)]:
            self.archive(self.today,clock,count)
        self.archive(self.today,'03:00',777,filename=f'review@{self.today}@03-00.json',slot=f'review@{self.today}')
        self.archive(self.today,'03:01',666,slot=f'manual@{self.today}@03:01')
        self.assertEqual([(r['label'],r['time'],r['newCount']) for r in web_app.build_today_news_rounds()],
                         [('上午','03:00',179),('下午','14:00',42)])

    def test_old_schedule_does_not_fill_missing_current_day_round(self):
        for clock in ('09:00','15:00'):
            self.archive(self.today,clock,99)
        self.assertEqual(web_app.build_today_news_rounds(self.today),[])

    def test_history_preserves_old_nine_and_fifteen_slot_times(self):
        for clock in ('09:00','15:00'):
            self.archive('2026-07-29',clock,20)
        rounds=web_app.build_today_news_rounds('2026-07-29')
        self.assertEqual([r['time'] for r in rounds],['09:00','15:00'])
        self.assertEqual([r['key'] for r in rounds],['2026-07-29-09-00','2026-07-29-15-00'])

    def test_historical_three_and_fourteen_are_not_overridden_by_newer_legacy_files(self):
        for clock,count in [('03:00',18),('14:00',4),('09:00',999),('15:00',888)]:
            self.archive('2026-09-10',clock,count)
        self.assertEqual([(r['time'],r['newCount']) for r in web_app.build_today_news_rounds('2026-09-10')],
                         [('03:00',18),('14:00',4)])

    def test_schedule_minutes_and_archive_slot_must_match(self):
        for clock,count in [('03:00',999),('03:30',18),('14:45',4)]:
            self.archive(self.today,clock,count)
        with patch.object(briefing,'SCAN_TIMES',(time(3,30),time(14,45))):
            self.assertEqual([r['time'] for r in web_app.build_today_news_rounds()],['03:30','14:45'])
            self.archive(self.today,'14:45',555,slot=f'review@{self.today}')
            self.assertEqual([r['time'] for r in web_app.build_today_news_rounds()],['03:30'])
