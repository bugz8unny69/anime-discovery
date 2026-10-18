import sqlite3, tempfile, unittest
from pathlib import Path
from anime_v19_rejection_guard import blocked, PILOT_HASH
class GuardTests(unittest.TestCase):
    def test_reject_restore(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'events.db'
            with sqlite3.connect(p) as db:
                db.execute('CREATE TABLE trial_events (id INTEGER PRIMARY KEY, torrent_hash TEXT, action TEXT)')
                db.execute('INSERT INTO trial_events(torrent_hash,action) VALUES (?,?)',(PILOT_HASH,'REJECTED'))
            self.assertTrue(blocked(PILOT_HASH,p))
            self.assertFalse(blocked('a'*40,p))
            with sqlite3.connect(p) as db:
                db.execute('INSERT INTO trial_events(torrent_hash,action) VALUES (?,?)',(PILOT_HASH,'RESTORED'))
            self.assertFalse(blocked(PILOT_HASH,p))
    def test_missing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError): blocked(PILOT_HASH,Path(td)/'missing.db')
if __name__=='__main__': unittest.main()
