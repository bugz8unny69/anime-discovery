"""Pinned Shoko v3 API tests; no actual link mutation."""
import json
import unittest
from anime_shoko_v3 import find_file,resolve_episode,plan_link

class Reply:
    status=200
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.payload).encode()

class ShokoTests(unittest.TestCase):
    def test_api_key_header_and_exact_file_location(self):
        calls=[]
        def opener(req,timeout):
            calls.append(req)
            return Reply([{"ID":5,"Locations":[{"AbsolutePath":"/anime/trial/ep.mkv","IsAccessible":True}],"SeriesIDs":[]}])
        file=find_file("https://shoko.arr.internal","fake-secret","/anime/trial/ep.mkv",opener=opener)
        self.assertEqual(file["ID"],5)
        self.assertEqual(calls[0].get_header("Apikey"),"fake-secret")
        self.assertIn("/api/v3/File/PathEndsWith?",calls[0].full_url)
    def test_suffix_collision_cannot_match(self):
        def opener(req,timeout):
            return Reply([{"ID":5,"Locations":[{"AbsolutePath":"/another/ep.mkv","IsAccessible":True}],"SeriesIDs":[]}])
        self.assertIsNone(find_file("https://shoko.arr.internal","key","/anime/ep.mkv",opener=opener))
    def test_anidb_resolution(self):
        calls=[]
        def opener(req,timeout):
            calls.append(req)
            return Reply({"IDs":{"AniDB":701,"ID":42}})
        resolved=resolve_episode("https://shoko.arr.internal","key",701,opener=opener)
        self.assertEqual(resolved["shoko_episode_id"],42)
        self.assertIn("/api/v3/Episode/AniDB/701/Episode",calls[0].full_url)
    def test_link_plan_is_never_executed(self):
        plan=plan_link(file_record={"ID":5,"SeriesIDs":[]},shoko_episode_id=42,
            anidb_episode_id=701,identity_verified=True,ordering_verified=True)
        self.assertEqual(plan["body"],{"EpisodeIDs":[42]})
        self.assertEqual(plan["path"],"/api/v3/File/5/Link")
        self.assertFalse(plan["writes_enabled"])
    def test_existing_links_block_changes(self):
        plan=plan_link(file_record={"ID":5,"SeriesIDs":[{"EpisodeIDs":[{"ID":6}]}]},
           shoko_episode_id=42,anidb_episode_id=701,identity_verified=True,ordering_verified=True)
        self.assertEqual(plan["action"],"NO_WRITE")
    def test_missing_identity_blocks_changes(self):
        plan=plan_link(file_record={"ID":5,"SeriesIDs":[]},shoko_episode_id=42,
           anidb_episode_id=701,identity_verified=False,ordering_verified=True)
        self.assertEqual(plan["action"],"NO_WRITE")

if __name__=="__main__":unittest.main()
