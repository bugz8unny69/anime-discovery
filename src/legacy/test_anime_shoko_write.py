"""Mock Shoko 5.3.3 scan/link/readback API requests."""
import json
import unittest
from anime_shoko_write import request_scan, link_verified, confirm_association

class Reply:
    status=200
    def __init__(self,data=None):self.data=data
    def __enter__(self):return self
    def __exit__(self,*unused):return False
    def read(self):return json.dumps(self.data).encode() if self.data is not None else b""

class ShokoWriteTests(unittest.TestCase):
    def test_scan_uses_configured_folder(self):
        seen=[]
        def opener(req,timeout):
            seen.append((req.full_url,req.get_method()))
            return Reply({})
        request_scan("https://shoko.local","secret",1,opener=opener)
        self.assertEqual(seen,[("https://shoko.local/api/v3/ImportFolder/1/Scan","GET")])
        with self.assertRaises(ValueError):
            request_scan("https://shoko.local","key",0,opener=opener)
    def test_link_requires_optin_and_readback(self):
        state={"linked":False}
        def opener(req,timeout):
            if req.full_url.endswith("/File/62/Episode"):
                return Reply([{"IDs":{"ID":876,"AniDB":555}}] if state["linked"] else [])
            if req.full_url.endswith("/File/62/Link"):
                self.assertEqual(req.get_method(),"POST")
                self.assertEqual(json.loads(req.data),{"EpisodeIDs":[876]})
                state["linked"]=True
                return Reply({})
            self.fail(req.full_url)
        with self.assertRaises(ValueError):
            link_verified("https://shoko.local","key",file_id=62,
                shoko_episode_id=876,anidb_episode_id=555,
                verified_identity=True,opener=opener)
        self.assertEqual(link_verified("https://shoko.local","key",file_id=62,
            shoko_episode_id=876,anidb_episode_id=555,
            verified_identity=True,allow_writes=True,opener=opener),
            "SHOKO_LINK_VERIFIED")
        self.assertEqual(link_verified("https://shoko.local","key",file_id=62,
            shoko_episode_id=876,anidb_episode_id=555,
            verified_identity=True,allow_writes=True,opener=opener),
            "SHOKO_ALREADY_LINKED_VERIFIED")
    def test_conflicting_link_never_overwritten(self):
        seen=[]
        def opener(req,timeout):
            seen.append(req.get_method())
            return Reply([{"IDs":{"ID":901,"AniDB":999}}])
        with self.assertRaises(RuntimeError):
            link_verified("https://shoko.local","key",file_id=62,
                shoko_episode_id=876,anidb_episode_id=555,
                verified_identity=True,allow_writes=True,opener=opener)
        self.assertEqual(seen,["GET"])

if __name__=="__main__":unittest.main()
