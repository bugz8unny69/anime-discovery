import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import anime_identity_worker_v12 as w

class TestV12(unittest.TestCase):
    def test_done_actions(self):
        for action in w.DONE:
            self.assertEqual(w.retry_delay(action, 1), 0)
    def test_backoff(self):
        self.assertEqual(w.retry_delay('ERROR_RETRY_NO_STATUS_CHANGE', 1), 300)
        self.assertEqual(w.retry_delay('ERROR_RETRY_NO_STATUS_CHANGE', 2), 600)
        self.assertEqual(w.retry_delay('ERROR_RETRY_NO_STATUS_CHANGE', 100), 76800)
    def test_rate_limit(self):
        self.assertEqual(w.retry_delay('RATE_LIMITED_RETRY', 1, 120), 120)
        self.assertEqual(w.retry_delay('RATE_LIMITED_RETRY', 1, 10), 60)
    def test_record_and_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'queue.db'
            w.init(db)
            record = w.record_v12(db, 7, {'action':'INSERTED'}, 1000)
            self.assertEqual(record['attempts'], 1)
            self.assertEqual(record['next_at'], 1000)
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute('SELECT last_action FROM identity_queue').fetchone()[0], 'INSERTED')
    def test_exception_is_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'queue.db'
            w.init(db)
            args=SimpleNamespace(state_db=db, inbox=Path(tmp)/'inbox.db',limit=5,watch=False)
            with patch.object(w,'pending',return_value=[8]), patch.object(w,'process_one',side_effect=RuntimeError('secret')):
                report=w.process_batch(args)
            item=report['items'][0]
            self.assertEqual(item['action'], 'ERROR_RETRY_NO_STATUS_CHANGE')
            self.assertNotIn('secret',str(item))
            self.assertGreater(item['queue']['next_at'],time_now_floor())
    def test_successful_item_not_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'queue.db'
            w.init(db)
            args=SimpleNamespace(state_db=db,inbox=Path(tmp)/'inbox.db',limit=5,watch=False)
            with patch.object(w,'pending',return_value=[1]), patch.object(w,'process_one',return_value={'notification_id':1,'action':'INSERTED'}):
                item=w.process_batch(args)['items'][0]
            self.assertFalse(item['eligible_for_acquisition'])

def time_now_floor():
    import time
    return time.time()
