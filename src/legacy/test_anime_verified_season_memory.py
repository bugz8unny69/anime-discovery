"""Episode-independent season identity memory and safely reusable title hints."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_fresh_database import initialize
from anime_verified_season_memory import (
    remember, known_for_release, for_series, remember_from_report,
    proven_season_mapping,
)
from anime_unified_identity_monitor import investigate
from anime_release_matching import resolve_release

XML=(b'<anime-list>'
     b'<anime anidbid="15610" tvdbid="384541" defaulttvdbseason="1" episodeoffset="0"/>'
     b'<anime anidbid="19445" tvdbid="384541" defaulttvdbseason="2" episodeoffset="0"/>'
     b'</anime-list>')
DIGEST=hashlib.sha256(XML).hexdigest()
NAME="Cyberpunk Edgerunners"

class VerifiedSeasonMemoryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db_path=self.root/"db.sqlite"
        initialize(self.db_path)
        self.db=sqlite3.connect(self.db_path,isolation_level=None)
        self.addCleanup(self.db.close)
        self.sid=self.db.execute(
            "INSERT INTO series(source,external_id,title) VALUES ('tvdb','384541',?)",
            (NAME,)).lastrowid

    def save(self,season,anidb,episode=1):
        # Episode intentionally unused by the memory writer. No E01 gate.
        return remember(self.db,title=NAME,tvdb_id=384541,
                        anidb_id=anidb,season=season,evidence_sha256=DIGEST)

    def test_late_episode_6_and_1001_both_reuse_series_without_release_group(self):
        self.save(1,15610,episode=6)
        for name in ("[Trix] Cyberpunk Edgerunners S01E06 1080p",
                     "[SubsPlease] Cyberpunk Edgerunners S01E03",
                     "[OtherGroup] Cyberpunk Edgerunners S01E1001"):
            found=known_for_release(self.db,name)
            self.assertIsNotNone(found,name)
            self.assertEqual((found["tvdb_id"],found["anidb_id"],found["season"]),
                             ("384541","15610",1))

    def test_out_of_order_episode_does_not_create_new_series_or_replace_identity(self):
        self.save(2,19445,episode=6)
        self.save(1,15610,episode=3)
        self.assertEqual(len(for_series(self.db,self.sid)),2)
        self.assertEqual(known_for_release(self.db,
            "[DifferentUploader] Cyberpunk Edgerunners S02E04")["anidb_id"],"19445")
        self.assertEqual(known_for_release(self.db,
            "[DifferentUploader] Cyberpunk Edgerunners S01E04")["anidb_id"],"15610")

    def test_unscoped_1001_and_special_fail_closed(self):
        self.save(1,15610)
        for title in ("[Group] Cyberpunk Edgerunners - 1001",
                      "[Group] Cyberpunk Edgerunners Episode 1001",
                      "[Group] Cyberpunk Edgerunners S00E04",
                      "[Group] Other Show S01E06"):
            self.assertIsNone(known_for_release(self.db,title),title)

    def test_no_episode_is_learned_from_cache_alone(self):
        self.save(1,15610)
        known=known_for_release(self.db,"[GroupB] Cyberpunk Edgerunners S01E06")
        urls=[]
        def fetch(url,bearer=None):
            urls.append(url)
            if url.endswith("/extended"):
                return {"data":{"id":384541,"genres":[{"name":"Animation"}],
                                "remoteIds":[{"sourceName":"AniDB","id":"15610"}]}}
            return {"data":{"episodes":[
                {"id":9876,"seasonNumber":1,"number":6}]},"links":{"next":None}}
        result=investigate("[GroupB] Cyberpunk Edgerunners S01E06",
            {"tvdb":{"enabled":True},"anidb":{"enabled":True},
             "identity":{"episode_map":{}}},
            {"tvdb_api_key":"test"},None,
            search=lambda *_:self.fail("Cache hit must skip broad TVDB search"),
            login=lambda *_:"token",fetch=fetch,mapping_xml=XML,
            trusted_season=known,
            anidb_resolve=lambda aid,ep: 20006 if (aid,ep)==(15610,6) else None)
        self.assertEqual(result["decision"],"AUTO_VERIFIED")
        self.assertEqual(result["approval"]["episode"],6)
        self.assertEqual(result["approval"]["anidb_id"],15610)
        self.assertTrue(any("/episodes/default" in url for url in urls))
        self.assertIn("Verified season cache",
                      [x["step"] for x in result["workflow"]])

    def test_cache_hit_still_requires_exact_episode_mapping(self):
        self.save(1,15610)
        known=known_for_release(self.db,"[DifferentGroup] Cyberpunk Edgerunners S01E1001")
        def fetch(url,bearer=None):
            if "/extended" in url:
                return {"data":{"id":384541,"genres":[{"name":"Animation"}]}}
            return {"data":{"episodes":[]},"links":{"next":None}}
        report=investigate("[DifferentGroup] Cyberpunk Edgerunners S01E1001",
            {"tvdb":{"enabled":True},"anidb":{"enabled":True},
             "identity":{"episode_map":{}}},
            {"tvdb_api_key":"test"},None,
            search=lambda *_:self.fail("Broad search not needed"),
            login=lambda *_:"token",fetch=fetch,mapping_xml=XML,
            trusted_season=known,
            anidb_resolve=lambda aid,ep:self.fail("Episode absent; no AniDB lookup"))
        self.assertNotEqual(report["decision"],"AUTO_VERIFIED")
        self.assertNotIn("approval",report)
        self.assertIn("TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED",report["issues"])

    def test_cache_never_trusts_stale_or_ambiguous_mapping(self):
        self.save(2,19445)
        self.assertFalse(proven_season_mapping(XML,384541,2,15610))
        duplicate=XML.replace(b'</anime-list>',
            b'<anime anidbid="999" tvdbid="384541" defaulttvdbseason="2"/></anime-list>')
        self.assertFalse(proven_season_mapping(duplicate,384541,2,19445))
        with self.assertRaises(ValueError):
            remember(self.db,title=NAME,tvdb_id=384541,
                     anidb_id=15610,season=2,evidence_sha256=DIGEST)

    def test_proof_records_episode_6_not_just_episode_1(self):
        report={"decision":"AUTO_VERIFIED",
                "matching_pairs":[{"tvdb_id":"384541","anidb_id":"19445"}]}
        result=remember_from_report(self.db,
            "[UnrelatedGroup] Cyberpunk Edgerunners S02E06",report,XML,
            approved={"tvdb_id":384541,"anidb_id":19445,
                      "season":2,"episode":6})
        self.assertEqual(result["anidb_id"],"19445")
        self.assertEqual(known_for_release(self.db,
            "[Trix] Cyberpunk Edgerunners S02E03")["anidb_id"],"19445")
        self.assertIsNone(remember_from_report(self.db,
            "[Trix] Cyberpunk Edgerunners S01E01",
            {"decision":"NEEDS_REVIEW","matching_pairs":[]},XML,
            approved={"tvdb_id":384541,"anidb_id":15610,"season":1}))

    def test_season2_release_cannot_be_misidentified_as_anidb_season1(self):
        # Title search alone discovers the original series; a season
        # mismatch is a hard stop even when TVDB has S01E06 available.
        def fetch(url,bearer=None):
            if url.endswith("/extended"):
                return {"data":{"id":384541,"genres":[{"name":"Animation"}],
                                "remoteIds":[{"sourceName":"AniDB","id":"15610"}]}}
            return {"data":{"episodes":[{"id":111,
                "seasonNumber":1,"number":6}]},"links":{"next":None}}
        rows=[{"anidb_id":"15610","matched_titles":[NAME],"titles":[NAME]}]
        with patch("anime_unified_identity_monitor.anidb_matches",
                   return_value=(rows,False)):
            report=investigate("[NewUploader] Cyberpunk Edgerunners S02E06",
                {"tvdb":{"enabled":True},"anidb":{"enabled":True},
                 "identity":{"episode_map":{}}},
                {"tvdb_api_key":"test"},None,
                search=lambda *_:([{"tvdb_id":"384541","name":NAME}],[]),
                login=lambda *_:"token",fetch=fetch,mapping_xml=XML,
                anidb_resolve=lambda *args:self.fail("Season conflict must stop mapping"))
        self.assertNotEqual(report["decision"],"AUTO_VERIFIED")
        self.assertIn("RELEASE_SEASON_PROVIDER_MISMATCH",report["issues"])
        self.assertNotIn("approval",report)

    def test_qualified_recognized_names_keep_two_anidb_productions_separate(self):
        aliases={NAME+" [S01]":{"tvdb_id":384541,"anidb_id":15610,"season":1},
                 NAME+" [S02]":{"tvdb_id":384541,"anidb_id":19445,"season":2}}
        self.assertEqual(resolve_release("[GroupA] Cyberpunk Edgerunners S01E06",aliases)["anidb_id"],15610)
        self.assertEqual(resolve_release("[GroupB] Cyberpunk Edgerunners S02E04",aliases)["anidb_id"],19445)
        self.assertIsNone(resolve_release("[GroupB] Cyberpunk Edgerunners S03E02",aliases))
        self.assertIsNone(resolve_release("[GroupB] Cyberpunk Edgerunners - 1001",aliases))

    def test_legacy_trusted_verification_backfills_existing_staged_series(self):
        from anime_unified_identity_monitor import ensure_schema
        from anime_webhook_processing import approve
        ensure_schema(self.db)
        nid=self.db.execute("""INSERT INTO notifications
            (source,release_name,source_guid,info_hash,received_at,status)
            VALUES ('autobrr',?,'preupgrade-06',?,1,'IDENTIFYING')""",
            ("[PriorGroup] Cyberpunk Edgerunners S01E06","b"*40)).lastrowid
        result=approve(self.db,nid,{"tvdb_id":384541,"anidb_id":15610,
            "season":1,"episode":6},source="verified_identity_mapping")
        report={"decision":"AUTO_VERIFIED",
            "approval":{"tvdb_id":384541,"anidb_id":15610,"season":1,"episode":6},
            "matching_pairs":[{"tvdb_id":"384541","anidb_id":"15610"}]}
        self.db.execute("""INSERT INTO unified_identity_checks
            (notification_id,checked_at,attempts,next_at,decision,evidence_json)
            VALUES (?,1,1,0,'AUTO_VERIFIED',?)""",(nid,json.dumps(report)))
        self.assertEqual(for_series(self.db,self.sid)[0]["anidb_id"],"15610")
        self.assertIsNotNone(known_for_release(
            self.db,"[NewGroup] Cyberpunk Edgerunners S01E03"))

    def test_auto_remembered_alias_never_bypasses_episode_verification(self):
        from anime_webhook_processing import receive
        self.save(2,19445)
        from anime_series_aliases import remember_verified_season
        from anime_flat_config import DEFAULT_SETTINGS,load_config
        import os
        directory=self.root/"one-click"
        directory.mkdir()
        (directory/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
        (directory/"secrets.json").write_text("{}")
        os.chmod(directory/"secrets.json",0o600)
        remember_verified_season(self.db,directory,self.sid,2)
        aliases=load_config(directory)["settings"]["identity"]["series_map"]
        self.assertEqual(aliases[NAME+" [S02]"]["verify_each_episode"],True)
        incoming=receive(self.db,{"source":"autobrr","source_guid":"groupB-06",
            "release_name":"[DifferentUploader] Cyberpunk Edgerunners S02E06",
            "info_hash":"f"*40},series_map=aliases)
        self.assertEqual(incoming["identity_status"],"IDENTIFYING")
        self.assertFalse(incoming.get("queued",False))
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM episode_dispatch WHERE notification_id=?",
            (incoming["notification_id"],)).fetchone())
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM daemon_jobs WHERE subject_key=?",
            (str(incoming["notification_id"]),)).fetchone())

    def test_series_detail_shows_only_server_proven_seasons(self):
        from anime_dashboard_pages import detail_page
        from anime_series_lifecycle import inspect
        self.save(2,19445)
        info=inspect(self.db,self.sid)
        info["remembered_seasons"]=for_series(self.db,self.sid)
        html=detail_page(info)
        self.assertIn('action="/series-remember"',html)
        self.assertIn("Add Season 2 to Recognized Names",html)
        self.assertIn('name="season" value="2"',html)
        self.assertNotIn("Add Season 1 to Recognized Names",html)

    def test_server_side_button_never_allows_browser_to_replace_ids(self):
        from anime_series_aliases import remember_verified_season
        from anime_flat_config import DEFAULT_SETTINGS
        import os
        self.save(1,15610)
        self.save(2,19445)
        directory=self.root/"config"
        directory.mkdir()
        (directory/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
        (directory/"secrets.json").write_text("{}")
        os.chmod(directory/"secrets.json",0o600)
        with self.assertRaises(ValueError):
            remember_verified_season(self.db,directory,self.sid,3)
        one=remember_verified_season(self.db,directory,self.sid,1)
        two=remember_verified_season(self.db,directory,self.sid,2)
        self.assertEqual(one["alias"],NAME+" [S01]")
        self.assertEqual(two["alias"],NAME+" [S02]")
        self.assertTrue(remember_verified_season(
            self.db,directory,self.sid,2)["already_exists"])
        from anime_flat_config import load_config
        settings=load_config(directory)["settings"]
        self.assertEqual(len(settings["identity"]["series_map"]),2)
        self.assertEqual(settings["identity"]["series_map"][one["alias"]]["anidb_id"],15610)
        self.assertEqual(settings["identity"]["series_map"][two["alias"]]["anidb_id"],19445)

if __name__=="__main__":
    unittest.main()
