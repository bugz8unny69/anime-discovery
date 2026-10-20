"""Offline regression tests for Sonarr KEEP and failures."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_series_lifecycle import keep
from anime_sonarr import ensure_series

class KeepTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbpath=Path(self.tmp.name)/"db.sqlite"
        initialize(self.dbpath)
        self.db=sqlite3.connect(self.dbpath,isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)
        self.sid=self.db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb','123','Example')").lastrowid
        self.nid=self.db.execute("INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at) VALUES ('autobrr','Example E01','demo','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0)").lastrowid
        self.db.execute("INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state) VALUES (?,?,1,1,'DONE')",(self.nid,self.sid))
        stage=Path(self.tmp.name)/"episode.mkv"
        stage.write_bytes(b"fixture")
        self.db.execute("INSERT INTO torrent_recovery_records(notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at) VALUES (?,'hash','magnet',?,'hash',0)",(self.nid,str(stage)))
        self.settings={"storage":{"trial_root":self.tmp.name},"sonarr":{"enabled":True,"base_url":"https://sonarr.example","root_folder":"/mnt/media/Anime","quality_profile_id":4}}
        self.secrets={"sonarr_api_key":"not-a-live-key"}
    def test_keep_persists_only_after_confirmation(self):
        result=keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=lambda *a,**k:{"sonarr_id":22})
        self.assertEqual(result["sonarr_id"],22)
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",(self.sid,)).fetchone()[0],"SONARR_IMPORT_PENDING")
        self.assertEqual(self.db.execute("SELECT tvdb_id FROM sonarr_keep").fetchone()[0],"123")
    def test_keep_warns_and_persists_notice_for_unowned_torrent(self):
        from anime_series_lifecycle import inspect
        from anime_dashboard_pages import detail_page
        outcome=keep(self.db,self.sid,self.settings,self.secrets,
                     sonarr_client=lambda *a,**k:{"sonarr_id":22})
        self.assertEqual(outcome["torrents_preserved"],1)
        self.assertIn("preserved",outcome["cleanup_notice"])
        result=inspect(self.db,self.sid)
        self.assertEqual(result["cleanup_notices"][0]["ownership"],"UNCERTAIN")
        page=detail_page(result)
        self.assertIn("Original qBittorrent files preserved",page)
        self.assertIn("remove these torrents and their files manually",page)
        self.assertIn('role="status"',page)
        # Still visible on reload; this is not a one-time flash.
        self.assertIn("Original qBittorrent files preserved",
                      detail_page(inspect(self.db,self.sid)))

    def test_keep_does_not_warn_for_proven_ownership(self):
        from anime_qb_ownership import ensure_schema,OWNED,CATEGORY
        from anime_series_lifecycle import inspect
        from anime_dashboard_pages import detail_page
        ensure_schema(self.db)
        self.db.execute("""INSERT INTO qb_torrent_ownership
            VALUES (?,?,?,?,1)""",("hash",OWNED,"ad-"+"1"*32,CATEGORY))
        outcome=keep(self.db,self.sid,self.settings,self.secrets,
                     sonarr_client=lambda *a,**k:{"sonarr_id":22})
        self.assertEqual(outcome["torrents_preserved"],0)
        self.assertIsNone(outcome["cleanup_notice"])
        self.assertNotIn("Original qBittorrent files preserved",
                         detail_page(inspect(self.db,self.sid)))

    def test_failed_sonarr_does_not_keep(self):
        def unavailable(*a,**kw):
            raise RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=unavailable)
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",(self.sid,)).fetchone()[0],"DISCOVERED")
    def test_rejected_never_calls_sonarr(self):
        self.db.execute("UPDATE series SET status='REJECTED' WHERE id=?",(self.sid,))
        with self.assertRaises(ValueError):
            keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=lambda *a,**k:self.fail("called"))
    def test_new_keep_adds_monitored_series_without_historical_search(self):
        class Response:
            def __init__(self, data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(self.data).encode()
        requests=[]
        def opener(req,timeout):
            payload=json.loads(req.data) if req.data else None
            requests.append((req.get_method(),req.full_url,payload))
            if req.full_url.endswith("/qualityprofile"):
                return Response([{"id":4,"name":"Anime"}])
            if req.full_url.endswith("/rootfolder"):
                return Response([{"path":"/mnt/media/Anime"}])
            if req.full_url.endswith("/series") and req.get_method()=="GET":
                return Response([])
            if "/series/lookup?" in req.full_url:
                return Response([{"tvdbId":123,"title":"Example","seasons":[
                    {"seasonNumber":1,"monitored":True}]}])
            if req.full_url.endswith("/series") and req.get_method()=="POST":
                self.assertEqual(payload["tvdbId"],123)
                self.assertTrue(payload["monitored"])
                self.assertEqual(payload["monitorNewItems"],"all")
                self.assertEqual(payload["addOptions"]["monitor"],"all")
                self.assertFalse(payload["addOptions"]["searchForMissingEpisodes"])
                self.assertEqual(payload["rootFolderPath"],"/mnt/media/Anime")
                return Response({"id":76})
            raise AssertionError("Unexpected Sonarr request")
        result=ensure_series(self.settings,self.secrets,tvdb_id="123",
                             title="Example",opener=opener)
        self.assertEqual(result,{"sonarr_id":76,"already_exists":False})
        self.assertEqual(sum(r[0]=="POST" for r in requests),1)

    def test_sonarr_existing_id_no_duplicate_post(self):
        class Response:
            def __init__(self,data): self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(self.data).encode()
        calls=[]
        def fake(request,timeout):
            calls.append((request.get_method(),request.full_url,request.get_header("X-api-key")))
            if request.full_url.endswith("/qualityprofile"):
                return Response([{"id":4,"name":"Anime"}])
            if request.full_url.endswith("/rootfolder"):
                return Response([{"path":"/mnt/media/Anime"}])
            return Response([{"tvdbId":123,"id":7}])
        result=ensure_series(self.settings,self.secrets,tvdb_id="123",title="Example",opener=fake)
        self.assertTrue(result["already_exists"])
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0][0],"GET")
        self.assertEqual(calls[0][2],"not-a-live-key")


    def test_existing_sonarr_season_uses_managed_review_not_import(self):
        from unittest.mock import patch
        from anime_series_lifecycle import inspect
        existing={"sonarr_id":124,"already_exists":True}
        observed=[{"season":1,"episode":1,"status":"REGISTERED",
                   "sonarr_episode_id":701,"sonarr_episode_file_id":901}]
        with patch("anime_sonarr.ensure_series",return_value=existing), \
             patch("anime_sonarr_import.inspect_registered_episodes",
                   return_value=observed), \
             patch("anime_sonarr_import.request_import",
                   side_effect=AssertionError("Duplicate import forbidden")):
            result=keep(self.db,self.sid,self.settings,self.secrets)
        self.assertTrue(result["already_managed"])
        self.assertFalse(result["import_pending"])
        self.assertIsNone(result["command_id"])
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",
                                        (self.sid,)).fetchone()[0],"SONARR_MANAGED_REVIEW")
        self.assertIsNone(self.db.execute(
            "SELECT submitted_command_id FROM sonarr_import_manifest").fetchone()[0])
        self.assertEqual(inspect(self.db,self.sid)["cleanup_notices"][0]["ownership"],
                         "UNCERTAIN")

    def test_existing_sonarr_partial_season_imports_only_missing(self):
        from unittest.mock import patch
        nid=self.db.execute("""INSERT INTO notifications
            (source,release_name,source_guid,info_hash,received_at)
            VALUES ('autobrr','Example E02','second','b',0)""").lastrowid
        self.db.execute("""INSERT INTO episode_dispatch
            (notification_id,series_id,season,episode,state)
            VALUES (?,?,1,2,'DONE')""",(nid,self.sid))
        path=Path(self.tmp.name)/"episode2.mkv"
        path.write_bytes(b"second")
        self.db.execute("""INSERT INTO torrent_recovery_records
            (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
            VALUES (?,'b','magnet',?,'hash',0)""",(nid,str(path)))
        observed=[{"season":1,"episode":1,"status":"REGISTERED"},
                  {"season":1,"episode":2,"status":"MISSING"}]
        captured=[]
        def submit(*args,**kwargs):
            captured.extend(kwargs["plan"])
            return {"command_id":512}
        with patch("anime_sonarr.ensure_series",
                   return_value={"sonarr_id":124,"already_exists":True}), \
             patch("anime_sonarr_import.inspect_registered_episodes",
                   return_value=observed), \
             patch("anime_sonarr_import.request_import",side_effect=submit):
            result=keep(self.db,self.sid,self.settings,self.secrets)
        self.assertEqual([(e["season"],e["episode"]) for e in captured],[(1,2)])
        self.assertTrue(result["import_pending"])
        self.assertEqual(json.loads(self.db.execute(
            "SELECT manifest_json FROM sonarr_import_manifest").fetchone()[0])[0]["episode"],2)

if __name__=="__main__": unittest.main()
