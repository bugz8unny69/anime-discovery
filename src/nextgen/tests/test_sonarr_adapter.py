"""Offline Sonarr adapter contracts. Deliberately not executed by CI."""
import io
import json
import unittest
from urllib.error import HTTPError

from src.nextgen.sonarr import SonarrClient, SonarrOptions, SonarrReview, SonarrUnavailable


class Reply:
    status = 200
    def __init__(self, value):self.data = io.BytesIO(json.dumps(value).encode())
    def __enter__(self):return self
    def __exit__(self, *args):pass
    def read(self, count):return self.data.read(count)


class FakeSonarr:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
    def __call__(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url, request.data))
        if not self.replies:raise AssertionError("unexpected API call")
        response = self.replies.pop(0)
        if isinstance(response, Exception):raise response
        return Reply(response)


def options():
    return SonarrOptions("https://sonarr.arr.internal", "/mnt/media/Anime",
                         api_key="secret")


class SonarrTests(unittest.TestCase):
    def test_invalid_configuration(self):
        with self.assertRaises(SonarrReview):
            SonarrOptions("https://a.example/x", "/mnt/media/Anime", api_key="secret")
        with self.assertRaises(SonarrReview):
            SonarrOptions("https://a.example", "/mnt/media/../Anime", api_key="secret")

    def test_existing_series_rejects_conflicting_root(self):
        fake = FakeSonarr([[{"name":"Anime","id":12}], [{"path":"/mnt/media/Anime"}],
                           [{"id":9,"tvdbId":111,"qualityProfileId":12,
                             "rootFolderPath":"/elsewhere"}]])
        with self.assertRaises(SonarrReview):
            SonarrClient(options(),opener=fake).ensure_series(111)
        self.assertEqual([c[0] for c in fake.calls],["GET","GET","GET"])

    def test_existing_series_is_read_only(self):
        fake = FakeSonarr([[{"name":"Anime","id":12}], [{"path":"/mnt/media/Anime"}],
                           [{"id":9,"tvdbId":111,"qualityProfileId":12,
                             "rootFolderPath":"/mnt/media/Anime"}]])
        self.assertEqual(SonarrClient(options(),opener=fake).ensure_series(111),(9,False))

    def test_explicit_episode_override_and_copy_only(self):
        path="/mnt/media/Trial/show/Season 01/episode.mkv"
        fake = FakeSonarr([
            [{"id":42,"seasonNumber":1,"episodeNumber":2,"tvdbId":981}],
            [{"path":path,"quality":{"quality":{"id":7}},"languages":[{"id":1}]}],
            [{"path":path,"seriesId":9,"episodes":[{"id":42}],
              "quality":{"quality":{"id":7}},"languages":[{"id":1}]}],
            {"id":300}])
        client=SonarrClient(options(),opener=fake)
        selected=client.manual_import_preview(9,[{"path":path,"season":1,"episode":2,"tvdb_episode_id":981}])
        self.assertEqual(selected[0]["episodeIds"],[42])
        self.assertEqual(client.submit_copy(selected),300)
        self.assertIn("folder=",fake.calls[1][1])
        self.assertNotIn("seriesId=",fake.calls[1][1])
        payload=json.loads(fake.calls[2][2])
        self.assertEqual(payload[0]["episodeIds"],[42])
        command=json.loads(fake.calls[3][2])
        self.assertEqual(command["importMode"],"copy")
        self.assertEqual(command["files"],selected)

    def test_wrong_tvdb_episode_fails_before_preview_mutation(self):
        fake=FakeSonarr([[{"id":42,"seasonNumber":1,"episodeNumber":2,"tvdbId":982}]])
        with self.assertRaises(SonarrReview):
            SonarrClient(options(),opener=fake).manual_import_preview(9,[
                {"path":"/trial/ep.mkv","season":1,"episode":2,"tvdb_episode_id":981}])
        self.assertEqual(len(fake.calls),1)

    def test_rejection_preserves_secret_and_response(self):
        fake=FakeSonarr([HTTPError("https://sonarr.arr.internal/api/v3/series",401,
                                    "SECRET-RESPONSE",{},None)])
        with self.assertRaises(SonarrUnavailable) as caught:
            SonarrClient(options(),opener=fake).inventory(9)
        self.assertNotIn("SECRET",str(caught.exception))
        self.assertNotIn("secret",str(options()))


if __name__=="__main__":unittest.main()
