"""Pinned Shoko v3 API tests; no actual link mutation."""
import json
import unittest
from anime_shoko_v3 import find_file,resolve_episode,plan_link,get_file,validate_location

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
    def test_real_shoko_relative_location_fixture(self):
        relative="Solo Leveling/Season 1/[Breeze] Solo Leveling - S01E01 [1080p BD AV1][Multi Audio].mkv"
        record={"ID":62,"Size":731252439,"Locations":[{
            "ID":72,"FileID":62,"ImportFolderID":1,"RelativePath":relative,
            "IsAccessible":True}]}
        verified=validate_location(record,relative_path=relative,import_folder_id=1)
        self.assertEqual(verified,{"file_id":62,"location_id":72,"accessible":True})
        with self.assertRaises(RuntimeError):
            validate_location(record,relative_path=relative,import_folder_id=2)
        with self.assertRaises(RuntimeError):
            validate_location(record,relative_path="wrong.mkv",import_folder_id=1)
        def opener(req,timeout):
            return Reply(record)
        self.assertEqual(get_file("https://shoko.arr.internal","key",62,opener=opener)["ID"],62)
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
    def test_real_unrecognized_file_with_null_links_stays_read_only(self):
        record={"ID":62,"SeriesIDs":None,"Locations":[{"ID":72,"FileID":62,
            "ImportFolderID":1,"RelativePath":"Solo Leveling/Season 1/episode.mkv",
            "IsAccessible":True}]}
        decision=plan_link(file_record=record,shoko_episode_id=42,
            anidb_episode_id=701,identity_verified=True,ordering_verified=True)
        self.assertEqual(decision["action"],"NO_WRITE")
        self.assertFalse(decision["writes_enabled"])

    def test_missing_identity_blocks_changes(self):
        plan=plan_link(file_record={"ID":5,"SeriesIDs":[]},shoko_episode_id=42,
           anidb_episode_id=701,identity_verified=False,ordering_verified=True)
        self.assertEqual(plan["action"],"NO_WRITE")

if __name__=="__main__":unittest.main()
