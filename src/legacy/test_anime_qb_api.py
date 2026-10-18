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

    def test_explicit_write_and_no_file_deletion(self):
        opener=Opener(b"Ok.")
        qb=QBittorrentAPI("http://localhost:8080",opener=opener,allow_writes=True)
        qb.remove_torrent("b"*40,delete_files=False)
        self.assertIn(b"deleteFiles=false",opener.requests[0].data)
        with self.assertRaises(ValueError):
            qb.remove_torrent("b"*40,delete_files=True)
        qb.add_magnet("magnet:?xt=urn:btih:"+"b"*40)
        self.assertEqual(len(opener.requests),2)

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

if __name__=="__main__":
    unittest.main()
