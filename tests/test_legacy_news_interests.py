import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from cmhk.services.subscriptions import SubscriptionService, NEWS_CATEGORY_LABELS

class LegacyInterestTests(unittest.TestCase):
    def test_legacy_choices_and_defaults_are_preserved_across_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);service=SubscriptionService(runtime_root=root)
            service.save_subscriptions('ou_legacy123','测试',['news'])
            with closing(sqlite3.connect(service.db_path)) as db, db:
                defaults=json.loads(db.execute('SELECT default_preferences FROM subscribers').fetchone()[0])
                defaults['news_categories']=list(NEWS_CATEGORY_LABELS)
                db.execute('UPDATE subscribers SET news_categories=?, default_preferences=?',
                           (json.dumps(list(NEWS_CATEGORY_LABELS)),json.dumps(defaults)))
            SubscriptionService(runtime_root=root)
            with closing(sqlite3.connect(service.db_path)) as db, db:
                first=db.execute('SELECT news_categories,default_preferences FROM subscribers').fetchone()
            # Sample four sections per card without rewriting the user's seven
            # saved interests or the preferences restored by the default button.
            chosen=json.loads(first[0]);self.assertEqual(chosen,list(NEWS_CATEGORY_LABELS))
            self.assertEqual(json.loads(first[1])['news_categories'],chosen)
            SubscriptionService(runtime_root=root)
            with closing(sqlite3.connect(service.db_path)) as db, db:
                self.assertEqual(db.execute('SELECT news_categories,default_preferences FROM subscribers').fetchone(),first)
