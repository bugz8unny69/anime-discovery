"""Offline season recognition tests; not executed until CI approval."""
import json
from types import SimpleNamespace
import sqlite3
import unittest

from src.nextgen.storage.sqlite import initialize
from src.nextgen.storage.recognition import (
    RecognitionConflict, recognized_for_release, remember_verified_release)


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        initialize(self.db)
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO identified_anime VALUES(1001,2001,'Example Anime')")
        for id_,season,episode in ((11,1,3),(12,2,1)):
            event=id_
            self.db.execute(
                "INSERT INTO incoming_events(event_id,source,raw_body,received_at_ms) VALUES(?, 'autobrr',?,1)",
                (event,json.dumps({"release_name":f"Example Anime S{season:02d}E{episode:02d}"}).encode()))
            self.db.execute("INSERT INTO jobs(job_id,event_id,kind,payload_json,available_at_ms,created_at_ms,updated_at_ms) VALUES(?,?,'VERIFY_RELEASE','{}',1,1,1)",(id_,event))
            self.db.execute("INSERT INTO identity_results VALUES(?,?,1001,2,'{}',1)",(id_,event))
            self.db.execute("INSERT INTO identified_episodes VALUES(?,1001)",(10000+id_,))
            self.db.execute("INSERT INTO release_verifications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (id_,id_,id_,1001,'a'*64,'DECLARED_SINGLE_EPISODE',episode,10000+id_,
                 2001,season,episode,20000+id_,100000))
        self.db.commit()

    def remember(self,id_,season):
        source=SimpleNamespace(anidb_id=1001,tvdb_series_id=2001,
            raw_body=json.dumps({"release_name":f"Example Anime S{season:02d}E01"}).encode())
        self.db.execute("BEGIN")
        try:
            remember_verified_release(self.db,verification_id=id_,source=source,season=season)
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def test_automatic_series_season_recognition_is_not_per_episode(self):
        self.remember(11,1)
        self.remember(12,2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM recognized_seasons").fetchone()[0],2)
        first=recognized_for_release(self.db,"Example Anime S01E09",season=1)
        second=recognized_for_release(self.db,"Example Anime S02E03",season=2)
        self.assertEqual(first["anidb_id"],1001)
        self.assertEqual(second["tvdb_series_id"],2001)
        self.assertEqual(second["tvdb_season"],2)
        self.assertIsNone(recognized_for_release(self.db,"Example Anime - 01"))
        self.assertIsNone(recognized_for_release(self.db,"Unknown Anime S02E01",season=2))
        self.assertEqual(self.db.execute("SELECT count(*) FROM release_verifications").fetchone()[0],2)

    def test_idempotence_and_verified_provenance_enforced(self):
        self.remember(11,1)
        self.remember(11,1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM recognized_aliases").fetchone()[0],1)
        source=SimpleNamespace(anidb_id=999,tvdb_series_id=2001,
            raw_body=b'{"release_name":"Untrusted S01E01"}')
        self.db.execute("BEGIN")
        with self.assertRaises(RecognitionConflict):
            remember_verified_release(self.db,verification_id=11,source=source,season=1)
        self.db.rollback()
        self.assertIsNone(recognized_for_release(self.db,"Untrusted S01E01",season=1))


if __name__=="__main__":
    unittest.main()
