"""Offline Sonarr import preparation tests; no remote or destructive operations."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_sonarr_import import plan_staged_imports, request_import

class StagedPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"trial"
        self.root.mkdir()
        initialize(Path(self.tmp.name)/"db.sqlite")
        self.db=sqlite3.connect(Path(self.tmp.name)/"db.sqlite",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.sid=self.db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb','123','Example')").lastrowid
        nid=self.db.execute("INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at) VALUES ('autobrr','Episode 1','guid','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0)").lastrowid
        self.db.execute("INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state) VALUES (?,?,1,1,'DONE')",(nid,self.sid))
        self.path=self.root/"episode.mkv"
        self.path.write_bytes(b"test media")
        self.db.execute("INSERT INTO torrent_recovery_records(notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at) VALUES (?,'hash','magnet',?,'sha',0)",(nid,str(self.path)))
    def test_exact_path_is_planned(self):
        plan=plan_staged_imports(self.db,self.sid,trial_root=self.root)
        self.assertEqual(plan[0]["path"],str(self.path))
        self.assertEqual(plan[0]["episode"],1)
    def test_missing_media_fails_closed(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            plan_staged_imports(self.db,self.sid,trial_root=self.root)
    def test_outside_trial_root_is_rejected(self):
        outside=Path(self.tmp.name)/"other.mkv"
        outside.write_bytes(b"test")
        self.db.execute("UPDATE torrent_recovery_records SET staged_path=?",(str(outside),))
        with self.assertRaises(ValueError):
            plan_staged_imports(self.db,self.sid,trial_root=self.root)

class KeepCandidateDiagnosisTests(unittest.TestCase):
    PATH="/mnt/media/Anime-Trial/Example/Season 01/S01E01.mkv"

    def call_import(self,candidates):
        import json
        from anime_sonarr_import import SonarrImportNeedsReview
        class Reply:
            def __init__(self,data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(self.data).encode()
        def opener(request,timeout):
            if "episode?seriesId" in request.full_url:
                return Reply([{"id":2443,"seasonNumber":1,"episodeNumber":1}])
            if "manualimport?folder=" in request.full_url:
                return Reply(candidates)
            if request.full_url.endswith("/manualimport"):
                return Reply([])  # Deliberately fail the identity reprocess.
            raise AssertionError("Manual import command must not be sent on mismatch")
        with self.assertLogs("anime_discovery.sonarr",level="WARNING") as lines:
            with self.assertRaises(SonarrImportNeedsReview) as failure:
                request_import({"sonarr":{"base_url":"https://sonarr.example"}},
                    {"sonarr_api_key":"test"},sonarr_id=124,
                    plan=[{"season":1,"episode":1,"path":self.PATH}],
                    opener=opener)
        self.assertIn(failure.exception.reason,"\\n".join(lines.output))
        return failure.exception.reason

    def test_sonarr_missing_staged_directory_guides_mount_check(self):
        self.assertEqual(self.call_import([]),"SOURCE_FOLDER_NOT_VISIBLE")

    def test_sonarr_other_absolute_path_guides_mount_check(self):
        self.assertEqual(self.call_import([{"path":"/data/trial/Example/S01E01.mkv",
                "series":{"id":124},"episodes":[{"id":2443}]}]),
                "STAGED_FILE_PATH_NOT_VISIBLE")

    def test_sonarr_sees_path_but_wrong_series(self):
        self.assertEqual(self.call_import([{"path":self.PATH,
                "series":{"id":999},"episodes":[{"id":2443}],
                "quality":{"quality":{"id":9}},"languages":[{"id":8}]}]),
                "SONARR_REPROCESS_UNCONFIRMED")

    def test_sonarr_sees_series_but_wrong_episode(self):
        self.assertEqual(self.call_import([{"path":self.PATH,
                "series":{"id":124},"episodes":[{"id":2442}],
                "quality":{"quality":{"id":9}},"languages":[{"id":8}]}]),
                "SONARR_REPROCESS_UNCONFIRMED")

    def test_malformed_candidate_does_not_cause_attribute_error(self):
        self.assertEqual(self.call_import([None,{"path":self.PATH,
                "series":None,"episodes":None}]),"QUALITY_LANGUAGE_UNRESOLVED")


class VerifiedOverrideTests(unittest.TestCase):
    def test_explicit_sonarr_identity_reprocesses_name_only_stage_and_copies(self):
        import json
        path="/mnt/media/Anime-Trial/Solo Leveling/Season 01/S01E01.mkv"
        requests=[]
        class Reply:
            def __init__(self,data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(self.data).encode()
        def opener(req,timeout):
            payload=json.loads(req.data) if req.data else None
            requests.append((req.get_method(),req.full_url,payload))
            if "episode?seriesId" in req.full_url:
                return Reply([{"id":777,"seasonNumber":1,"episodeNumber":1}])
            if "manualimport?folder=" in req.full_url:
                # Sonarr can read the file but cannot infer Solo Leveling from S01E01.mkv.
                return Reply([{"path":path,"series":None,"episodes":[],
                               "quality":{"quality":{"id":9}},
                               "languages":[{"id":8}],"rejections":[{"reason":"Unknown Series"}]}])
            if req.full_url.endswith("/manualimport"):
                self.assertEqual(payload[0]["path"],path)
                self.assertEqual(payload[0]["seriesId"],24)
                self.assertEqual(payload[0]["episodeIds"],[777])
                return Reply([{**payload[0],"episodeIds":None,
                    "episodes":[{"id":777}],"rejections":[]}])
            if req.full_url.endswith("/command"):
                self.assertEqual(payload["name"],"ManualImport")
                self.assertEqual(payload["importMode"],"copy")
                self.assertEqual(payload["files"][0]["path"],path)
                self.assertEqual(payload["files"][0]["seriesId"],24)
                self.assertEqual(payload["files"][0]["episodeIds"],[777])
                return Reply({"id":501})
            raise AssertionError("Unexpected Sonarr API call")
        with self.assertLogs("anime_discovery.sonarr",level="INFO") as lines:
            result=request_import({"sonarr":{"base_url":"https://sonarr.example"}},
                {"sonarr_api_key":"dummy"},sonarr_id=24,
                plan=[{"season":1,"episode":1,"path":path}],opener=opener)
        self.assertEqual(result["command_id"],501)
        self.assertFalse(result["source_cleanup_authorized"])
        self.assertIn("EXPLICIT_VERIFIED_EPISODE"," ".join(lines.output))
        self.assertEqual([r[0] for r in requests],["GET","GET","POST","POST"])

    def test_reprocess_wrong_episode_is_not_trusted(self):
        import json
        from anime_sonarr_import import SonarrImportNeedsReview
        path="/mnt/media/Anime-Trial/Solo Leveling/Season 01/S01E01.mkv"
        class Reply:
            def __init__(self,data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(self.data).encode()
        def opener(req,timeout):
            payload=json.loads(req.data) if req.data else None
            if "episode?seriesId" in req.full_url:
                return Reply([{"id":777,"seasonNumber":1,"episodeNumber":1}])
            if "manualimport?folder=" in req.full_url:
                return Reply([{"path":path,"series":None,"episodes":[],
                               "quality":{"quality":{"id":9}},
                               "languages":[{"id":8}]}])
            if req.full_url.endswith("/manualimport"):
                return Reply([{**payload[0],"episodeIds":None,
                               "episodes":[{"id":999}],"rejections":[]}])
            raise AssertionError("Rejected reprocess must never submit import")
        with self.assertRaises(SonarrImportNeedsReview) as failure:
            request_import({"sonarr":{"base_url":"https://sonarr.example"}},
                {"sonarr_api_key":"dummy"},sonarr_id=24,
                plan=[{"season":1,"episode":1,"path":path}],opener=opener)
        self.assertEqual(failure.exception.reason,"SONARR_REPROCESS_IDENTITY_MISMATCH")

class RejectionTests(unittest.TestCase):
    def test_existing_higher_quality_blocks_manual_import(self):
        class Reply:
            def __init__(self,data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self):
                import json
                return json.dumps(self.data).encode()
        calls=[]
        def opener(req,timeout):
            calls.append(req.get_method())
            if "episode?seriesId" in req.full_url:
                return Reply([{"id":2443,"seasonNumber":1,"episodeNumber":1}])
            return Reply([{"path":"/mnt/media/Anime-Trial/Solo Leveling/Season 01/Solo Leveling - S01E01.mkv",
                "series":{"id":124},"episodes":[{"id":2443}],
                "quality":{"quality":{"id":9}},"languages":[{"id":8}],
                "rejections":[{"type":"permanent","reason":"Not an upgrade"}]}])
        with self.assertRaises(RuntimeError):
            request_import({"sonarr":{"base_url":"https://sonarr.example"}},
                {"sonarr_api_key":"test"},sonarr_id=124,
                plan=[{"season":1,"episode":1,"path":"/mnt/media/Anime-Trial/Solo Leveling/Season 01/Solo Leveling - S01E01.mkv"}],
                opener=opener)
        self.assertEqual(calls,["GET","GET"])

if __name__=="__main__":unittest.main()
