import json
import unittest
from anime_completed_snapshot import completed_torrent_snapshot

class Stub:
    def __init__(self, torrent, files):
        self.responses=[json.dumps(torrent).encode(),json.dumps(files).encode()]
        self.calls=[]
    def _request(self, path):
        self.calls.append(path)
        return self.responses.pop(0)

class SnapshotTests(unittest.TestCase):
    def test_reads_matching_torrent_and_manifest(self):
        infohash="a"*40
        stub=Stub([{"hash":infohash,"progress":1,"state":"uploading"}],
                  [{"name":"episode.mkv","progress":1}])
        result=completed_torrent_snapshot(stub,infohash)
        self.assertEqual(result["files"][0]["name"],"episode.mkv")
        self.assertEqual(len(stub.calls),2)
        self.assertTrue(all(path.startswith("torrents/") for path in stub.calls))

    def test_rejects_mismatched_hash(self):
        stub=Stub([{"hash":"b"*40}],[])
        with self.assertRaisesRegex(ValueError,"matching torrent"):
            completed_torrent_snapshot(stub,"a"*40)
        self.assertEqual(len(stub.calls),1)

if __name__=="__main__":
    unittest.main()
