"""Offline verified AniDB-number -> TVDB episode mapping reuse tests."""
import unittest
from anime_verified_episode_map import from_anime_lists


def xml(season, offset):
    return (('<anime-list><anime anidbid="456" tvdbid="123" '
             'defaulttvdbseason="%d" episodeoffset="%d" />'
             '</anime-list>') % (season,offset)).encode()


class MappingTests(unittest.TestCase):
    def test_absolute_second_season_anidb_13_through_24_to_tvdb_1_through_12(self):
        result=from_anime_lists(xml(2,-12),anidb_id=456,tvdb_id=123,
            season=2,release_episodes=list(range(13,25)))
        self.assertEqual(result["episode_map"],{i:i-12 for i in range(13,25)})
        self.assertTrue(result["evidence_ref"].startswith("anime-lists:"))

    def test_second_cour_anidb_1_maps_to_tvdb_13(self):
        result=from_anime_lists(xml(1,12),anidb_id=456,tvdb_id=123,
            season=1,release_episodes=list(range(1,13)))
        self.assertEqual(result["episode_map"],{i:i+12 for i in range(1,13)})

    def test_ongoing_episode_1001_keeps_same_number(self):
        result=from_anime_lists(xml(1,0),anidb_id=456,tvdb_id=123,
            season=1,release_episodes=[1001,1002,1003])
        self.assertEqual(result["episode_map"],{1001:1001,1002:1002,1003:1003})

    def test_wrong_series_or_season_never_infers_offset(self):
        for kwargs in (dict(anidb_id=999,tvdb_id=123,season=2),
                       dict(anidb_id=456,tvdb_id=999,season=2),
                       dict(anidb_id=456,tvdb_id=123,season=3)):
            with self.assertRaisesRegex(ValueError,"absent or conflicting"):
                from_anime_lists(xml(2,-12),release_episodes=[13],**kwargs)

    def test_mapping_gaps_or_duplicate_number_lists_fail_closed(self):
        with self.assertRaises(ValueError):
            from_anime_lists(xml(2,-12),anidb_id=456,tvdb_id=123,
                season=2,release_episodes=[13,13])
        with self.assertRaises(ValueError):
            from_anime_lists(xml(2,-12),anidb_id=456,tvdb_id=123,
                season=2,release_episodes=[1])

    def test_invalid_xml_is_not_a_partial_mapping(self):
        with self.assertRaises(ValueError):
            from_anime_lists(b"invalid",anidb_id=456,tvdb_id=123,
                season=2,release_episodes=[])


if __name__=="__main__":
    unittest.main()
