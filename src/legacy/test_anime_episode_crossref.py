"""Offline TVDB episode -> Shoko AniDB episode cross-reference tests."""
import json
import unittest
from anime_episode_crossref import resolve_anidb_episode,tvdb_episode_id
from anime_episode_identity import resolve_exact_episode

class Reply:
    status=200
    def __init__(self,value): self.value=value
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self):return json.dumps(self.value).encode()

class MappingTests(unittest.TestCase):
    def test_unique_independent_crossref(self):
        def opener(req,timeout):
            u=req.full_url
            if "/Series/AniDB/123/Series" in u:
                return Reply({"IDs":{"AniDB":123,"ID":451}})
            if "/Series/451/Episode" in u:
                return Reply({"Total":2,"List":[
                    {"IDs":{"ID":888,"AniDB":501,"ParentSeries":451,"TvDB":[99001]}},
                    {"IDs":{"ID":889,"AniDB":502,"ParentSeries":451,"TvDB":[99002]}}]})
            self.fail(u)
        self.assertEqual(resolve_anidb_episode("https://shoko.local","key",
            anidb_series_id=123,tvdb_episode_id=99002,opener=opener),502)
    def test_no_implicit_number_match(self):
        def opener(req,timeout):
            if "AniDB" in req.full_url:
                return Reply({"IDs":{"AniDB":123,"ID":451}})
            return Reply({"Total":1,"List":[{"IDs":{"ID":888,"AniDB":1,
                "ParentSeries":451,"TvDB":[]}}]})
        self.assertIsNone(resolve_anidb_episode("https://shoko.local","key",
            anidb_series_id=123,tvdb_episode_id=99002,opener=opener))
    def test_duplicate_crossrefs_are_not_auto_approved(self):
        def opener(req,timeout):
            if "AniDB" in req.full_url:
                return Reply({"IDs":{"AniDB":123,"ID":451}})
            return Reply({"Total":2,"List":[
                {"IDs":{"ID":1,"AniDB":51,"ParentSeries":451,"TvDB":[99002]}},
                {"IDs":{"ID":2,"AniDB":52,"ParentSeries":451,"TvDB":[99002]}}]})
        self.assertIsNone(resolve_anidb_episode("https://shoko.local","key",
            anidb_series_id=123,tvdb_episode_id=99002,opener=opener))
    def test_tvdb_episode_unique_match(self):
        def opener(req,timeout):
            if req.full_url.endswith("/login"):
                return Reply({"data":{"token":"access"}})
            return Reply({"data":{"episodes":[
                {"id":900,"seasonNumber":1,"number":1},
                {"id":901,"seasonNumber":1,"number":2}]},"links":{"next":None}})
        result=tvdb_episode_id({"tvdb":{"enabled":True,
            "base_url":"https://api4.thetvdb.com/v4"}},
            {"tvdb_api_key":"token"},tvdb_id=50,season=1,episode=2,opener=opener)
        self.assertEqual(result,901)
    def test_map_only_when_explicitly_verified(self):
        s={"identity":{"episode_map":{"50:1:2":{"anidb_episode_id":501,"verified":True},
                                    "50:1:3":{"anidb_episode_id":502,"verified":False}}}}
        self.assertEqual(resolve_exact_episode(s,tvdb_id=50,season=1,episode=2),501)
        self.assertIsNone(resolve_exact_episode(s,tvdb_id=50,season=1,episode=3))

if __name__=="__main__":unittest.main()
