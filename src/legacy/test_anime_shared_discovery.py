"""Prowlarr-gap discovery tests run without network or live qBittorrent."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_prowlarr_search import ProwlarrClient,candidates
from anime_shared_discovery import schedule,search_once,identity_for_request,handler_factory
from anime_webhook_processing import receive
from anime_async_daemon import claim,finish

HASH_A="a"*40
HASH_B="b"*40
HASH_C="c"*40
MAPPING={"Example Show":{"tvdb_id":123,"anidb_id":456,"season":1}}

def release(ep,h,seeders=5):
    return {"title":"Example Show S01E%02d"%ep,
            "magnetUrl":"magnet:?xt=urn:btih:"+h,"seeders":seeders}


class FakeProwlarr:
    def __init__(self,items):
        self.items=items
        self.queries=[]
    def search(self,title):
        self.queries.append(title)
        return self.items


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"data.sqlite"
        initialize(self.path)
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)

    def test_one_id_or_alias_resolves_known_identity(self):
        for query in ({"title":"example show"},{"tvdb_id":123},{"anidb_id":456},
                      {"tvdb_id":123,"anidb_id":456}):
            self.assertEqual(identity_for_request(MAPPING,**query)["title"],"Example Show")
        with self.assertRaises(ValueError):
            identity_for_request(MAPPING,tvdb_id=999)

    def test_manual_one_shot_finds_candidates_and_queues_existing_pipeline(self):
        schedule(self.db,title="Example Show",tvdb_id=123,anidb_id=456,origin="manual")
        client=FakeProwlarr([release(1,HASH_A),release(2,HASH_B),release(3,HASH_C)])
        self.assertEqual(search_once(self.db,{"title":"Example Show","tvdb_id":"123",
            "anidb_id":"456","season":1,"up_to":None,"origin":"manual"},client)["queued"],3)
        self.assertEqual(client.queries,["Example Show"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM episode_dispatch").fetchone()[0],3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='claimed_acquisition'").fetchone()[0],3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='series_gap_search'").fetchone()[0],1)

    def test_autobrr_catches_only_earlier_missing_episodes(self):
        receive(self.db,{"source":"autobrr","source_guid":"incoming",
            "release_name":"Example Show S01E03","info_hash":HASH_C,
            "tvdb_id":123,"anidb_id":456,"season":1,"episode":3},series_map=MAPPING)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='series_gap_search'").fetchone()[0],1)
        client=FakeProwlarr([release(1,HASH_A),release(2,HASH_B),release(3,HASH_C),
                             release(4,"d"*40)])
        result=search_once(self.db,{"title":"Example Show","tvdb_id":"123",
            "anidb_id":"456","season":1,"up_to":3,"origin":"autobrr"},client)
        self.assertEqual(result["queued"],2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM episode_dispatch").fetchone()[0],3)

    def test_duplicate_candidates_do_not_submit_twice(self):
        client=FakeProwlarr([release(1,HASH_A),release(1,HASH_A)])
        request={"title":"Example Show","tvdb_id":"123","anidb_id":"456",
                 "season":1,"up_to":None,"origin":"manual"}
        self.assertEqual(search_once(self.db,request,client)["queued"],1)
        self.assertEqual(search_once(self.db,request,client)["queued"],0)

    def test_uncertain_equal_seeders_are_skipped(self):
        self.assertEqual(candidates([release(1,HASH_A),release(1,HASH_B)],
            alias="Example Show",tvdb_id=123,anidb_id=456,season=1),[])

    def test_rejected_series_blocks_manual_job(self):
        self.db.execute("INSERT INTO series(source,external_id,title,status) VALUES ('tvdb','123','Example Show','REJECTED')")
        with self.assertRaisesRegex(ValueError,"rejected"):
            schedule(self.db,title="Example Show",tvdb_id=123,anidb_id=456)

    def test_prowlarr_api_uses_key_header(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return json.dumps([release(1,HASH_A)]).encode()
        requests=[]
        def opener(request,timeout):
            requests.append(request)
            return Response()
        client=ProwlarrClient("http://127.0.0.1:9696","private",opener=opener)
        self.assertEqual(len(client.search("Example Show")),1)
        self.assertEqual(requests[0].get_header("X-api-key"),"private")
        self.assertIn("/api/v1/search?",requests[0].full_url)


if __name__=="__main__":
    unittest.main()
