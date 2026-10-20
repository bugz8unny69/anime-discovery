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

    def test_preparsed_correct_identity_still_requires_explicit_reprocess(self):
        self.assertEqual(self.call_import([{"path":self.PATH,
                "series":{"id":124},"episodes":[{"id":2443}],
                "quality":{"quality":{"id":9}},"languages":[{"id":8}]}]),
                "SONARR_REPROCESS_UNCONFIRMED")


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

class ExistingSonarrInventoryTests(unittest.TestCase):
    PATH="/mnt/media/Anime-Trial/Solo Leveling/Season 01/S01E01.mkv"

    def run_rejection(self, *, existing=True, complete=True):
        import json
        from anime_sonarr_import import SonarrImportNeedsReview
        issued=[]
        class Reply:
            def __init__(self,data): self.data=data
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(self.data).encode()
        def opener(req,timeout):
            payload=json.loads(req.data) if req.data else None
            issued.append((req.get_method(),req.full_url))
            if "episode?seriesId" in req.full_url:
                return Reply([{"id":777,"seasonNumber":1,"episodeNumber":1,
                               "hasFile":existing,"episodeFileId":901 if existing else 0},
                              {"id":778,"seasonNumber":1,"episodeNumber":2,
                               "hasFile":existing and complete,
                               "episodeFileId":902 if existing and complete else 0}])
            if "manualimport?folder=" in req.full_url:
                return Reply([{"path":self.PATH,"series":None,"episodes":[],
                               "quality":{"quality":{"id":9}},"languages":[{"id":8}]}])
            if req.full_url.endswith("/manualimport"):
                return Reply([{**payload[0],"episodes":[{"id":777}],
                    "rejections":[{"type":"permanent",
                                   "reason":"Not an upgrade for existing episode file(s)"}]}])
            if "episodefile?seriesId" in req.full_url:
                if not complete:
                    return Reply([{"id":901,"seriesId":124,"path":"/library/S01E01.mkv",
                                   "size":500000000}])
                return Reply([{"id":901,"seriesId":124,"path":"/library/S01E01.mkv",
                               "size":500000000},
                              {"id":902,"seriesId":124,"path":"/library/S01E02.mkv",
                               "size":550000000}])
            raise AssertionError("Rejected import must never submit ManualImport command")
        with self.assertLogs("anime_discovery.sonarr",level="INFO") as logs:
            with self.assertRaises(SonarrImportNeedsReview) as failure:
                request_import({"sonarr":{"base_url":"https://sonarr.example"}},
                    {"sonarr_api_key":"secret"},sonarr_id=124,
                    plan=[{"season":1,"episode":1,"path":self.PATH},
                          {"season":1,"episode":2,"path":self.PATH.replace("E01","E02")}],
                    opener=opener)
        return failure.exception, "\n".join(logs.output),issued

    def test_existing_entire_plan_is_reported_using_sonarr_api_only(self):
        error,log,calls=self.run_rejection()
        self.assertEqual(error.reason,"SONARR_EPISODE_ALREADY_PRESENT")
        self.assertIn("Not an upgrade for existing episode file(s)",str(error))
        self.assertIn("event=SONARR_MANUAL_IMPORT_REJECTIONS",log)
        self.assertIn("reason=SONARR_EPISODE_ALREADY_PRESENT",log)
        self.assertIn('"type":"permanent"',log)
        self.assertIn('"reason":"Not an upgrade for existing episode file(s)"',log)
        self.assertIn("staged_count=2 registered_count=2",log)
        self.assertIn("all_staged_registered=true",log)
        self.assertEqual([call[0] for call in calls],["GET","GET","POST","GET"])

    def test_partial_sonarr_inventory_does_not_claim_complete_season(self):
        error,log,_=self.run_rejection(complete=False)
        self.assertEqual(error.reason,"SONARR_EPISODE_ALREADY_PRESENT")
        self.assertIn("staged_count=2 registered_count=1",log)
        self.assertIn("all_staged_registered=false",log)

    def test_rejection_alone_never_proves_existing_sonarr_media(self):
        error,log,calls=self.run_rejection(existing=False)
        self.assertEqual(error.reason,"SONARR_REJECTED_CANDIDATE")
        self.assertIn("registered_count=0",log)
        self.assertFalse(any("episodefile?" in url for _,url in calls))

    def test_existing_inventory_has_distinct_html_not_mount_error(self):
        from anime_dashboard_pages import keep_review_page
        from anime_sonarr_import import SonarrImportNeedsReview
        page=keep_review_page(11,SonarrImportNeedsReview(
            "SONARR_EPISODE_ALREADY_PRESENT",
            "Sonarr: Not an upgrade for existing episode file(s)"))
        self.assertIn("Episode already registered in Sonarr",page)
        self.assertIn("has not marked Keep complete",page)
        self.assertIn("Not an upgrade",page)
        self.assertNotIn("Check these Sonarr settings",page)
        self.assertIn("/series?id=11",page)

    def test_rejection_detail_redacts_paths_credentials_and_newlines(self):
        from anime_sonarr_import import _public_rejections
        result=_public_rejections([{"type":"permanent",
            "reason":"Bad file /mnt/media/example.mkv https://sonarr.invalid/api?token=secret\nNext"}])
        import json
        clean=json.dumps(result)
        self.assertNotIn("/mnt/media",clean)
        self.assertNotIn("sonarr.invalid",clean)
        self.assertNotIn("secret",clean)
        self.assertNotIn("\\n",clean)
        self.assertIn("[redacted-path]",clean)


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
            import json
            calls.append(req.get_method())
            if "episode?seriesId" in req.full_url:
                return Reply([{"id":2443,"seasonNumber":1,"episodeNumber":1}])
            if "manualimport?folder=" in req.full_url:
                return Reply([{"path":"/mnt/media/Anime-Trial/Solo Leveling/Season 01/Solo Leveling - S01E01.mkv",
                    "series":{"id":124},"episodes":[{"id":2443}],
                    "quality":{"quality":{"id":9}},"languages":[{"id":8}],
                    "rejections":[{"type":"permanent","reason":"Not an upgrade"}]}])
            if req.full_url.endswith("/manualimport"):
                payload=json.loads(req.data)
                self.assertEqual(payload[0]["seriesId"],124)
                self.assertEqual(payload[0]["episodeIds"],[2443])
                return Reply([{**payload[0],"episodeIds":None,"episodes":[{"id":2443}],
                    "rejections":[{"type":"permanent","reason":"Not an upgrade"}]}])
            raise AssertionError("Rejected reprocess must never send a copy command")
        with self.assertRaises(RuntimeError):
            request_import({"sonarr":{"base_url":"https://sonarr.example"}},
                {"sonarr_api_key":"test"},sonarr_id=124,
                plan=[{"season":1,"episode":1,"path":"/mnt/media/Anime-Trial/Solo Leveling/Season 01/Solo Leveling - S01E01.mkv"}],
                opener=opener)
        self.assertEqual(calls,["GET","GET","POST"])


class ReadOnlyReconciliationTests(unittest.TestCase):
    def classify(self, episodes, files, plan=None):
        import json
        from anime_sonarr_import import inspect_registered_episodes
        calls=[]
        class Reply:
            def __init__(self, value): self.value=value
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(self.value).encode()
        def opener(req,timeout):
            calls.append((req.get_method(),req.full_url))
            if "episodefile?seriesId=" in req.full_url: return Reply(files)
            if "episode?seriesId=" in req.full_url: return Reply(episodes)
            raise AssertionError("Read-only reconciliation must not write")
        plan=plan if plan is not None else [
            {"season":1,"episode":1},{"season":1,"episode":2}]
        result=inspect_registered_episodes(
            {"sonarr":{"base_url":"https://sonarr.example"}},
            {"sonarr_api_key":"dummy"},sonarr_id=124,plan=plan,opener=opener)
        self.assertEqual([method for method,_ in calls],["GET","GET"])
        return result

    def test_seerr_existing_full_season_is_registered_not_imported(self):
        episodes=[
            {"id":701,"seasonNumber":1,"episodeNumber":1,"hasFile":True,"episodeFileId":901},
            {"id":702,"seasonNumber":1,"episodeNumber":2,"hasFile":True,"episodeFileId":902}]
        files=[{"id":901,"seriesId":124,"size":1000,"path":"/library/E01.mkv"},
               {"id":902,"seriesId":124,"size":1000,"path":"/library/E02.mkv"}]
        result=self.classify(episodes,files)
        self.assertEqual([x["status"] for x in result],["REGISTERED","REGISTERED"])
        self.assertNotIn("cleanup_authorized",result[0])

    def test_partial_inventory_reports_only_canonical_missing_episode(self):
        episodes=[
            {"id":701,"seasonNumber":1,"episodeNumber":1,"hasFile":True,"episodeFileId":901},
            {"id":702,"seasonNumber":1,"episodeNumber":2,"hasFile":False,"episodeFileId":0}]
        files=[{"id":901,"seriesId":124,"size":1000,"path":"/library/E01.mkv"}]
        self.assertEqual([x["status"] for x in self.classify(episodes,files)],
                         ["REGISTERED","MISSING"])

    def test_invalid_file_link_and_ambiguous_episode_hold_for_review(self):
        episodes=[
            {"id":701,"seasonNumber":1,"episodeNumber":1,"hasFile":True,"episodeFileId":901},
            {"id":702,"seasonNumber":1,"episodeNumber":2,"hasFile":True,"episodeFileId":902},
            {"id":703,"seasonNumber":1,"episodeNumber":2,"hasFile":True,"episodeFileId":902}]
        files=[{"id":901,"seriesId":999,"size":1000,"path":"/library/E01.mkv"},
               {"id":902,"seriesId":124,"size":1000,"path":"/library/E02.mkv"}]
        self.assertEqual([x["status"] for x in self.classify(episodes,files)],
                         ["NEEDS_REVIEW","NEEDS_REVIEW"])

    def test_broken_or_duplicate_manifest_fails_before_sonarr_call(self):
        from anime_sonarr_import import inspect_registered_episodes
        settings={"sonarr":{"base_url":"https://sonarr.example"}}
        secret={"sonarr_api_key":"dummy"}
        for plan in ([{"season":1,"episode":1}]*2,
                     [{"season":True,"episode":1}],[]):
            with self.assertRaises(ValueError):
                inspect_registered_episodes(settings,secret,sonarr_id=124,plan=plan,
                    opener=lambda *args: self.fail("should not request Sonarr"))

if __name__=="__main__":unittest.main()
