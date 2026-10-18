import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from ownership_audit import audit_attempts, snapshot_rows, AuditBlocked
H1='a'*40
H2='b'*40
T=lambda h: SimpleNamespace(torrent_hash=h)
class OwnershipAuditTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(audit_attempts([],[])['attempts'],0)
    def test_match_does_not_grant_ownership(self):
        r=audit_attempts([(1,1,1,1,H1,'DOWNLOADING')],[T(H1)])
        self.assertEqual(r['present_in_qb'],1)
        self.assertFalse(r['ownership_verified'])
        self.assertFalse(r['cancellation_enabled'])
    def test_absent(self):
        self.assertEqual(audit_attempts([(1,1,1,1,H1,'QUEUED')],[])['absent_from_qb'],1)
    def test_superseded(self):
        r=audit_attempts([(1,1,1,1,H1,'QUEUED'),(2,1,1,1,H2,'QUEUED')],[T(H1),T(H2)])
        self.assertEqual(r['superseded'],1)
    def test_duplicate_controller_hash(self):
        r=audit_attempts([(1,1,1,1,H1,'QUEUED'),(2,2,1,1,H1,'QUEUED')],[T(H1)])
        self.assertEqual(r['invalid_or_ambiguous'],1)
    def test_duplicate_qb_hash(self):
        with self.assertRaises(AuditBlocked): audit_attempts([], [T(H1),T(H1)])
    def test_bad_hash(self):
        self.assertEqual(audit_attempts([(1,1,1,1,'bad','QUEUED')],[])['invalid_or_ambiguous'],1)
    def test_invalid_id(self):
        self.assertEqual(audit_attempts([(0,1,1,1,H1,'QUEUED')],[])['invalid_or_ambiguous'],1)
    def test_snapshot_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE download_attempts (id INTEGER,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT)')
                db.execute('INSERT INTO download_attempts VALUES (1,1,1,1,?,?)',(H1,'QUEUED'))
            self.assertEqual(len(snapshot_rows(path)),1)
            with sqlite3.connect(path) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM download_attempts').fetchone()[0],1)
    def test_schema_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite'
            with sqlite3.connect(path) as db: db.execute('CREATE TABLE download_attempts (id INTEGER)')
            with self.assertRaises(AuditBlocked): snapshot_rows(path)
if __name__=='__main__': unittest.main()
