import sqlite3
import tempfile
import unittest
from pathlib import Path
from production_edges import (EdgeBlocked, snapshot_to_disposable,
    cancellation_preflight, cancel_once, automatic_mapping_approval)

class Edges(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.execute('CREATE TABLE download_attempts (id INTEGER PRIMARY KEY, series_id INTEGER, season INTEGER, episode INTEGER, torrent_hash TEXT, status TEXT)')
        self.h = 'a'*40
        self.db.execute('INSERT INTO download_attempts VALUES (11,1,1,2,?,?)',(self.h,'DOWNLOADING'))
    def tearDown(self): self.db.close()
    def args(self): return dict(series_id=1, attempt_id=11, torrent_hash=self.h)
    def test_eligible(self): self.assertEqual(cancellation_preflight(self.db,**self.args(),inventory_hashes={self.h}),'ELIGIBLE')
    def test_absent(self): self.assertEqual(cancellation_preflight(self.db,**self.args(),inventory_hashes=set()),'ABSENT')
    def test_wrong_hash(self):
        with self.assertRaises(EdgeBlocked): cancellation_preflight(self.db,**{**self.args(),'torrent_hash':'b'*40},inventory_hashes={self.h})
    def test_newer_attempt(self):
        self.db.execute('INSERT INTO download_attempts VALUES (12,1,1,2,?,?)',('b'*40,'QUEUED'))
        with self.assertRaises(EdgeBlocked): cancellation_preflight(self.db,**self.args(),inventory_hashes={self.h})
    def test_terminal(self):
        self.db.execute("UPDATE download_attempts SET status='CANCELLED'")
        with self.assertRaises(EdgeBlocked): cancellation_preflight(self.db,**self.args(),inventory_hashes={self.h})
    def test_wrong_series(self):
        with self.assertRaises(EdgeBlocked): cancellation_preflight(self.db,**{**self.args(),'series_id':2},inventory_hashes={self.h})
    def test_disabled_no_calls(self):
        def bad(): raise AssertionError('called')
        self.assertEqual(cancel_once(self.db,**self.args(),inventory_provider=bad,remove_torrent=bad)['status'],'DISABLED')
    def test_enabled_false_delete(self):
        calls=[]
        result=cancel_once(self.db,**self.args(),inventory_provider=lambda:{self.h},remove_torrent=lambda h,delete_files:calls.append((h,delete_files)),enabled=True)
        self.assertEqual(result['status'],'REMOVE_REQUESTED')
        self.assertEqual(calls,[(self.h,False)])
    def test_enabled_newer_attempt_blocks(self):
        self.db.execute('INSERT INTO download_attempts VALUES (12,1,1,2,?,?)',('b'*40,'QUEUED'))
        calls=[]
        with self.assertRaises(EdgeBlocked): cancel_once(self.db,**self.args(),inventory_provider=lambda:{self.h},remove_torrent=lambda *a,**k:calls.append(1),enabled=True)
        self.assertFalse(calls)
    def test_enabled_absent_no_remove(self):
        calls=[]
        self.assertEqual(cancel_once(self.db,**self.args(),inventory_provider=lambda:set(),remove_torrent=lambda *a,**k:calls.append(1),enabled=True)['status'],'ALREADY_ABSENT')
        self.assertFalse(calls)
    def test_adapter_error_rolls_back(self):
        def bad(*a,**k): raise RuntimeError('network')
        with self.assertRaises(RuntimeError): cancel_once(self.db,**self.args(),inventory_provider=lambda:{self.h},remove_torrent=bad,enabled=True)
        self.assertFalse(self.db.in_transaction)
    def test_mapping_disabled(self):
        with self.assertRaises(EdgeBlocked): automatic_mapping_approval(authenticated=True)
    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            src,dst=Path(d)/'source.db',Path(d)/'copy.db'
            db=sqlite3.connect(src);db.execute('CREATE TABLE x (v TEXT)');db.execute("INSERT INTO x VALUES ('hi')");db.commit();db.close()
            snapshot_to_disposable(src.resolve(),dst.resolve())
            copy=sqlite3.connect(dst);self.assertEqual(copy.execute('SELECT v FROM x').fetchone()[0],'hi');copy.close()
    def test_snapshot_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            src,dst=Path(d)/'source.db',Path(d)/'copy.db'
            sqlite3.connect(src).close();dst.write_bytes(b'untouched')
            with self.assertRaises(EdgeBlocked): snapshot_to_disposable(src.resolve(),dst.resolve())
            self.assertEqual(dst.read_bytes(),b'untouched')
    def test_snapshot_no_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            src,dst=Path(d)/'source.db',Path(d)/'copy.db'
            real=Path(d)/'real.db';sqlite3.connect(real).close();src.symlink_to(real)
            with self.assertRaises(EdgeBlocked): snapshot_to_disposable(src.absolute(),dst.absolute())

if __name__=='__main__': unittest.main()
