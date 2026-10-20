import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from anime_anidb_episode_lookup import parse_episode_id, lookup_episode_id

XML=b'''<anime id="456"><episodes>
<episode id="9876"><epno type="1">02</epno></episode>
<episode id="9910"><epno type="2">2</epno></episode>
</episodes></anime>'''

class AniDBEpisodeLookupTests(unittest.TestCase):
    def test_exact_regular_episode_only(self):
        self.assertEqual(parse_episode_id(XML,456,2),9876)
        self.assertIsNone(parse_episode_id(XML,456,3))
        with self.assertRaises(ValueError):
            parse_episode_id(XML,999,2)

    def test_duplicate_or_wrong_parent_fails_closed(self):
        duplicate=XML.replace(b'</episodes>',b'<episode id="1111"><epno type="1">2</epno></episode></episodes>')
        self.assertIsNone(parse_episode_id(duplicate,456,2))
        with self.assertRaises(ValueError):
            parse_episode_id(b'<error>Busy</error>',456,2)

    def test_gateway_cache_and_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            response=Mock()
            response.read.return_value=XML
            response.__enter__=Mock(return_value=response)
            response.__exit__=Mock(return_value=None)
            opener=Mock(return_value=response)
            params=dict(endpoint="https://anidb-proxy.example/httpapi",
                        client="registeredclient",clientver=1,
                        cache_dir=Path(root),opener=opener)
            self.assertEqual(lookup_episode_id(456,2,now=100000,**params),9876)
            self.assertEqual(lookup_episode_id(456,2,now=100001,**params),9876)
            self.assertEqual(opener.call_count,1)
            with self.assertRaises(ValueError):
                lookup_episode_id(456,2,endpoint="http://api.anidb.net:9001/httpapi",
                    client="registeredclient",clientver=1,cache_dir=Path(root))
