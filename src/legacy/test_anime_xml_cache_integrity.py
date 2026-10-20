"""Offline validation for AniDB title and Anime-Lists cache recovery."""
import gzip
import os
import tempfile
import unittest
from pathlib import Path

from anime_unified_identity_monitor import (
    MetadataUnavailable, ensure_anime_lists, ensure_titles
)

TITLES=b'<?xml version="1.0"?><animetitles><anime aid="123"><title>Example</title></anime></animetitles>'
MAP=b'<?xml version="1.0"?><anime-list><anime anidbid="123" tvdbid="456"/></anime-list>'


class MetadataCacheIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def test_valid_compressed_titles_cache_avoids_network(self):
        path=self.folder/"anidb-titles.xml.gz"
        data=gzip.compress(TITLES)
        path.write_bytes(data)
        os.utime(path,(200000,200000))
        def no_network():
            self.fail("Validated fresh metadata should use cache")
        self.assertEqual(ensure_titles(path,now=200001,downloader=no_network),path)
        self.assertEqual(path.read_bytes(),data)

    def test_invalid_cached_titles_are_repaired(self):
        path=self.folder/"anidb-titles.xml.gz"
        path.write_bytes(gzip.compress(b"<animetitles"))
        self.assertEqual(ensure_titles(path,now=300000,
                         downloader=lambda:gzip.compress(TITLES)),path)
        self.assertEqual(gzip.decompress(path.read_bytes()),TITLES)

    def test_malformed_refresh_keeps_last_valid_titles(self):
        path=self.folder/"anidb-titles.xml.gz"
        path.write_bytes(gzip.compress(TITLES))
        os.utime(path,(1,1))
        self.assertEqual(ensure_titles(path,now=200000,
                         downloader=lambda:b"<html>Error</html>"),path)
        self.assertEqual(gzip.decompress(path.read_bytes()),TITLES)

    def test_invalid_new_titles_is_retryable(self):
        path=self.folder/"anidb-titles.xml.gz"
        with self.assertRaises(MetadataUnavailable) as error:
            ensure_titles(path,now=1,downloader=lambda:b"<animetitles")
        self.assertEqual(error.exception.source,"ANIDB_TITLES")
        self.assertFalse(path.exists())

    def test_mapping_cache_repair_and_last_good(self):
        path=self.folder/"anime-lists.xml"
        path.write_bytes(b"<anime-list")
        self.assertEqual(ensure_anime_lists(path,now=200000,
                         downloader=lambda:MAP),MAP)
        os.utime(path,(1,1))
        self.assertEqual(ensure_anime_lists(path,now=200000,
                         downloader=lambda:b"<html>502 Bad Gateway</html>"),MAP)
        self.assertEqual(path.read_bytes(),MAP)

    def test_mapping_corruption_without_valid_fallback_is_retryable(self):
        path=self.folder/"anime-lists.xml"
        path.write_bytes(b"<anime-list")
        with self.assertRaises(MetadataUnavailable) as error:
            ensure_anime_lists(path,now=1,downloader=lambda:b"<broken")
        self.assertEqual(error.exception.source,"ANIME_LISTS")
        self.assertEqual(path.read_bytes(),b"<anime-list")


if __name__=="__main__":
    unittest.main()
