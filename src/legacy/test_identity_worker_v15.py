import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import anime_identity_worker_v15 as v
from anime_identity_confidence_v14 import DEFAULTS

class Tests(unittest.TestCase):
    def test_score_store_upsert(self):
        with tempfile.TemporaryDirectory() as t:
            db = Path(t)/'scores.db'
            v.init_scores(db)
            obj = {'policy_version': 'v14.1', 'score_points': 90, 'decision': 'SHADOW_HIGH_CONFIDENCE'}
            v.store_score(db, 2, obj)
            obj['score_points'] = 80
            v.store_score(db, 2, obj)
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute('select count(*), score from confidence_shadow_v15').fetchone(), (1,80))
    def test_saved_identity_requires_fresh_episode_lookup(self):
        from contextlib import nullcontext
        args = SimpleNamespace(verified=None, rate_state=None, interval=2, shadow_db=None)
        with patch.object(v, 'saved_readonly', return_value=('17495','389597','X',0,0)), \
             patch.object(v, 'protected', return_value=nullcontext(SimpleNamespace(count=2))), \
             patch.object(v, 'network_runner', return_value={'notification_id':1}) as lookup, \
             patch.object(v, 'score', return_value={'score_points':91,'decision':'SHADOW_HIGH_CONFIDENCE','blockers':[]}), \
             patch.object(v, 'store_score') as store:
            item = v.process_one(1, args, DEFAULTS)
        lookup.assert_called_once_with(1)
        store.assert_called_once()
        self.assertEqual(item['shadow_score'], 91)

    def test_saved_approval_rejected(self):
        with patch.object(v, 'saved_readonly', return_value=('17495','389597','X',1,0)):
            with self.assertRaises(ValueError):
                v.process_one(1, SimpleNamespace(verified=None), DEFAULTS)
    def test_network_path_records_shadow_and_persists_series(self):
        args = SimpleNamespace(verified=None, rate_state=None, interval=2, shadow_db=None)
        from contextlib import nullcontext
        with patch.object(v, 'saved_readonly', return_value=None), \
             patch.object(v, 'protected', return_value=nullcontext(SimpleNamespace(count=3))), \
             patch.object(v, 'network_runner', return_value={'notification_id': 7}), \
             patch.object(v, 'decide', return_value={'decision':'SERIES_VERIFIED_EPISODE_PENDING','series_identity_verified':True,'tvdb_episode_exists':True}), \
             patch.object(v, 'score', return_value={'score_points': 91,'decision':'SHADOW_HIGH_CONFIDENCE','blockers':[]}), \
             patch.object(v, 'store_score') as store, \
             patch.object(v, 'persist', return_value={'action':'INSERTED','anidb_id':'1','tvdb_id':'2'}):
            item = v.process_one(7, args, DEFAULTS)
        self.assertEqual(item['shadow_score'],91)
        self.assertEqual(item['action'],'INSERTED')
        store.assert_called_once()
    def test_unverified_series_does_not_persist(self):
        args = SimpleNamespace(verified=None, rate_state=None, interval=2, shadow_db=None)
        from contextlib import nullcontext
        with patch.object(v, 'saved_readonly', return_value=None), \
             patch.object(v, 'protected', return_value=nullcontext(SimpleNamespace(count=0))), \
             patch.object(v, 'network_runner', return_value={}), \
             patch.object(v, 'decide', return_value={'decision':'PENDING','series_identity_verified':False}), \
             patch.object(v, 'score', return_value={'score_points': 0,'decision':'SHADOW_BLOCKED','blockers':['X']}), \
             patch.object(v, 'store_score'), patch.object(v, 'persist', side_effect=AssertionError('persist called')):
            item = v.process_one(7, args, DEFAULTS)
        self.assertEqual(item['action'],'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE')

if __name__ == '__main__': unittest.main()
