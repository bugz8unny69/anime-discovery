"""Offline Shoko post-import contract checks. No Shoko writes."""
import json
import tempfile
import unittest
from pathlib import Path
from anime_shoko_handoff import inspect_imported_episode

class Response:
    status=200
    def __init__(self,obj): self.obj=obj
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self): return json.dumps(self.obj).encode()

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"Anime"
        self.root.mkdir()
        self.path=self.root/"series"/"ep.mkv"
        self.path.parent.mkdir()
        self.path.write_bytes(b"example")
    def run_check(self,opener,**overrides):
        kw=dict(destination=str(self.path),sonarr_root=str(self.root),
                anidb_episode_id=555,verified_episode_identity=True)
        kw.update(overrides)
        return inspect_imported_episode("https://shoko.arr.internal","test-key",opener=opener,**kw)
    def test_unverified_episode_identity_may_scan_but_does_not_link(self):
        result=self.run_check(lambda req,timeout: Response([]),verified_episode_identity=False)
        self.assertEqual(result["status"],"AWAITING_SHOKO_SCAN")
        self.assertFalse(result["writes_enabled"])
    def test_file_not_seen_waits_for_scan(self):
        result=self.run_check(lambda req,timeout: Response([]))
        self.assertEqual(result["status"],"AWAITING_SHOKO_SCAN")
    def test_unrecognized_null_links_are_checked_against_episode_endpoint(self):
        def opener(req,timeout):
            url=req.full_url
            if "PathEndsWith" in url: return Response([{"ID":62}])
            if "/Location" in url: return Response([{"FileID":62,"AbsolutePath":str(self.path),"IsAccessible":True}])
            if "/File/62/Episode" in url: return Response([])
            if "/File/62" in url: return Response({"ID":62,"SeriesIDs":None})
            if "/Episode/AniDB/555/Episode" in url: return Response({"IDs":{"ID":876,"AniDB":555}})
            raise AssertionError(url)
        result=self.run_check(opener)
        self.assertEqual(result["status"],"LINK_PLAN_READY")
        self.assertFalse(result["writes_enabled"])
    def test_exact_identity_can_prepare_but_not_send_link(self):
        methods=[]
        def opener(req,timeout):
            methods.append(req.get_method())
            url=req.full_url
            if "PathEndsWith" in url: return Response([{"ID":62}])
            if "/Location" in url: return Response([{"FileID":62,"AbsolutePath":str(self.path),"IsAccessible":True}])
            if "/File/62/Episode" in url: return Response([])
            if "/File/62" in url: return Response({"ID":62,"SeriesIDs":[]})
            if "/Episode/AniDB/555/Episode" in url: return Response({"IDs":{"ID":876,"AniDB":555}})
            raise AssertionError(url)
        result=self.run_check(opener)
        self.assertEqual(result["status"],"LINK_PLAN_READY")
        self.assertEqual(result["body"],{"EpisodeIDs":[876]})
        self.assertFalse(result["writes_enabled"])
        self.assertTrue(all(m=="GET" for m in methods))
    def test_suffix_collision_is_not_a_match(self):
        def opener(req,timeout):
            if "PathEndsWith" in req.full_url: return Response([{"ID":62}])
            return Response([{"FileID":62,"AbsolutePath":"/elsewhere/ep.mkv","IsAccessible":True}])
        self.assertEqual(self.run_check(opener)["status"],"AWAITING_SHOKO_SCAN")

if __name__=="__main__": unittest.main()
