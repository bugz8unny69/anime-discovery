import io
import json
import unittest
from anime_qb_api import QBittorrentAPI

class Response:
    status=200
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return self.data

class Opener:
    def __init__(self,body):self.body=body;self.requests=[]
    def open(self,request,timeout=None):
        self.requests.append(request)
        return Response(self.body)

class QBApiTests(unittest.TestCase):
    def test_read_only_query(self):
        infohash="a"*40
        opener=Opener(json.dumps([{"hash":infohash}]).encode())
        qb=QBittorrentAPI("http://127.0.0.1:8080",opener=opener)
        self.assertTrue(qb.contains_hash(infohash))
        with self.assertRaises(PermissionError):
            qb.add_magnet("magnet:?xt=urn:btih:"+infohash)
        with self.assertRaises(PermissionError):
            qb.remove_torrent(infohash)
        self.assertEqual(len(opener.requests),1)

    def test_explicit_write_and_file_deletion(self):
        opener=Opener(b"Ok.")
        qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
        qb.remove_torrent("b"*40,delete_files=False)
        self.assertIn(b"deleteFiles=false",opener.requests[0].data)
        qb.remove_torrent("b"*40,delete_files=True)
        self.assertIn(b"deleteFiles=true",opener.requests[1].data)
        qb.add_magnet("magnet:?xt=urn:btih:"+"b"*40)
        self.assertEqual(len(opener.requests),3)

    def test_category_and_ownership_marker_are_sent_with_magnet(self):
        import json
        class MultiOpener:
            def __init__(self):self.requests=[]
            def open(self,request,timeout=None):
                self.requests.append(request)
                url=request.full_url
                if url.endswith("/torrents/categories"):
                    return Response(json.dumps({"anime-discovery":{"name":"anime-discovery","savePath":""}}).encode())
                return Response(b"Ok.")
        opener=MultiOpener()
        qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
        marker="ad-"+"f"*32
        qb.add_magnet("magnet:?xt=urn:btih:"+"a"*40,
                      category="anime-discovery",tag=marker)
        self.assertEqual(len(opener.requests),2)
        data=opener.requests[-1].data
        self.assertIn(b"category=anime-discovery",data)
        self.assertIn(b"tags="+marker.encode(),data)
        with self.assertRaises(ValueError):
            qb.add_magnet("magnet:?xt=urn:btih:"+"a"*40,category="movies",tag=marker)

    def test_missing_fixed_category_is_created_once(self):
        import json
        class Categories:
            def __init__(self):self.requests=[];self.exists=False
            def open(self,request,timeout=None):
                self.requests.append(request)
                if request.full_url.endswith("/torrents/categories"):
                    return Response(json.dumps({"anime-discovery":{}} if self.exists else {}).encode())
                if request.full_url.endswith("/torrents/createCategory"):
                    self.exists=True
                return Response(b"Ok.")
        opener=Categories()
        qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
        qb.add_magnet("magnet:?xt=urn:btih:"+"a"*40,category="anime-discovery",
                      tag="ad-"+"a"*32)
        self.assertTrue(opener.exists)
        self.assertIn(b"savePath=",opener.requests[1].data)
        self.assertIn(b"category=anime-discovery",opener.requests[1].data)

    def test_torrent_identity_requires_exact_hash(self):
        payload=json.dumps([{"hash":"b"*40,"category":"anime-discovery","tags":"ad-test"},
                            {"hash":"a"*40,"category":"anime-discovery","tags":"ad-valid"}]).encode()
        qb=QBittorrentAPI("http://localhost:8080",opener=Opener(payload))
        self.assertEqual(qb.torrent_identity("a"*40)["tags"],"ad-valid")

    def test_login_does_not_enable_writes(self):
        opener=Opener(b"Ok.")
        qb=QBittorrentAPI("http://localhost:8080",opener=opener)
        qb.login("admin","test-password")
        self.assertIn(b"username=admin",opener.requests[0].data)
        with self.assertRaises(PermissionError):
            qb.remove_torrent("a"*40)
        self.assertEqual(len(opener.requests),1)

    def test_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            QBittorrentAPI("http://user:password@localhost:8080")


class PriorityOpener:
    """Simulate an owned, stopped torrent whose priorities can be read back."""
    def __init__(self, *, state="stoppedDL", owned=True, apply=True):
        self.requests=[]
        self.state=state
        self.owned=owned
        self.apply=apply
        self.priorities={0:1,1:1,2:1}

    def open(self,request,timeout=None):
        from urllib.parse import parse_qs
        self.requests.append(request)
        url=request.full_url
        if "/torrents/info?" in url:
            row={"hash":"a"*40,"state":self.state,
                 "category":"anime-discovery" if self.owned else "other",
                 "tags":"ad-"+"f"*32 if self.owned else ""}
            return Response(json.dumps([row]).encode())
        if "/torrents/files?" in url:
            rows=[{"index":i,"name":"Show S01E%02d.mkv"%(i+1),
                   "priority":p} for i,p in self.priorities.items()]
            return Response(json.dumps(rows).encode())
        if "/torrents/filePrio" in url:
            values=parse_qs(request.data.decode())
            if self.apply:
                for idx in values["id"][0].split("|"):
                    self.priorities[int(idx)]=int(values["priority"][0])
            return Response(b"Ok.")
        raise AssertionError("Unexpected API endpoint "+url)


class QBFileSelectionTests(unittest.TestCase):
    def test_owned_stopped_torrent_selects_first_two_and_skips_third(self):
        opener=PriorityOpener()
        qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
        result=qb.apply_stopped_file_selection("a"*40,
                                              wanted_indices=[0,1],
                                              skip_indices=[2])
        self.assertEqual(result,{"wanted_indices":[0,1],"skip_indices":[2]})
        self.assertEqual(opener.priorities,{0:1,1:1,2:0})
        priority_calls=[r for r in opener.requests if "/filePrio" in r.full_url]
        self.assertEqual(len(priority_calls),2)
        self.assertIn(b"priority=0",priority_calls[0].data)
        self.assertIn(b"priority=1",priority_calls[1].data)

    def test_read_only_refuses_without_write(self):
        opener=PriorityOpener()
        qb=QBittorrentAPI("http://localhost:8080",opener=opener)
        with self.assertRaises(PermissionError):
            qb.apply_stopped_file_selection("a"*40,
                                            wanted_indices=[0],skip_indices=[1,2])
        self.assertEqual(opener.requests,[])

    def test_unowned_or_running_refuses_before_priority_write(self):
        for opts in ({"owned":False},{"state":"downloading"}):
            opener=PriorityOpener(**opts)
            qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
            with self.assertRaises((PermissionError,RuntimeError)):
                qb.apply_stopped_file_selection("a"*40,
                                                wanted_indices=[0],skip_indices=[1,2])
            self.assertFalse(any("/filePrio" in r.full_url for r in opener.requests))

    def test_mismatched_or_partial_plan_refuses_without_priority_write(self):
        for wanted,skipped in (([0],[1]),([0,1],[1,2]),([0,0],[1,2])):
            opener=PriorityOpener()
            qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
            with self.assertRaises(ValueError):
                qb.apply_stopped_file_selection("a"*40,
                                                wanted_indices=wanted,skip_indices=skipped)
            self.assertFalse(any("/filePrio" in r.full_url for r in opener.requests))

    def test_write_ack_without_readback_confirmation_fails(self):
        opener=PriorityOpener(apply=False)
        qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
        with self.assertRaisesRegex(RuntimeError,"priority verification"):
            qb.apply_stopped_file_selection("a"*40,
                                            wanted_indices=[0,1],skip_indices=[2])
        self.assertEqual(opener.state,"stoppedDL")


if __name__=="__main__":
    unittest.main()
