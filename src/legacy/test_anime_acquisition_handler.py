import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_acquisition_handler import make_acquisition_handler

class HandlerTests(unittest.TestCase):
    def test_malformed_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            handler=make_acquisition_handler('unused.db',lambda:None,
                download_root=directory,trial_root=directory)
            result=asyncio.run(handler({'payload_json':'{}','subject_key':'1'}))
            self.assertEqual(result,'NEEDS_REVIEW')

    def test_stale_lease_blocks_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'jobs.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE daemon_jobs (id INTEGER,kind TEXT,state TEXT,lease_token TEXT,lease_until REAL)')
                db.execute('INSERT INTO daemon_jobs VALUES (1,?,?,?,?)',
                    ('claimed_acquisition','LEASED','new-token',time.time()+300))
            handler=make_acquisition_handler(path,lambda:object(),
                download_root=directory,trial_root=directory)
            job={'id':1,'lease_token':'old-token','subject_key':'4',
                'payload_json':json.dumps({'notification_id':4,'infohash':'a'*40,
                'magnet_uri':'magnet:?xt=urn:btih:'+'a'*40,
                'title':'Example','tvdb_id':123})}
            with patch('anime_acquisition_handler.process_claimed') as pipeline:
                with self.assertRaisesRegex(ValueError,'Stale acquisition lease'):
                    asyncio.run(handler(job))
                pipeline.assert_not_called()

    def test_current_lease_runs_pipeline_and_finalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'jobs.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE daemon_jobs (id INTEGER,kind TEXT,state TEXT,lease_token TEXT,lease_until REAL)')
                db.execute('INSERT INTO daemon_jobs VALUES (1,?,?,?,?)',
                    ('claimed_acquisition','LEASED','current',time.time()+300))
            handler=make_acquisition_handler(path,lambda:object(),
                download_root=directory,trial_root=directory)
            job={'id':1,'lease_token':'current','subject_key':'4',
                'payload_json':json.dumps({'notification_id':4,'infohash':'a'*40,
                'magnet_uri':'magnet:?xt=urn:btih:'+'a'*40,
                'title':'Example','tvdb_id':123})}
            with patch('anime_acquisition_handler.process_claimed',return_value={'state':'DONE'}), \\
                 patch('anime_acquisition_handler.finalize_acquisition') as finalize:
                self.assertEqual(asyncio.run(handler(job)),'DONE')
                finalize.assert_called_once()

if __name__=='__main__':
    unittest.main()
