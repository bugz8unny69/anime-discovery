"""Offline dual identities and TVDB-authoritative Sonarr mapping; unrun."""
import unittest
from src.nextgen.keep_selection import KeepSelection, KeepSelectionInvalid


class KeepSelectionTests(unittest.TestCase):
    def selection(self):return KeepSelection(100,101,200,201,0,7,1,'/staging','Series/Season 00/S00E07.mkv')

    def test_tvdb_mapping_is_separate_from_anidb_and_preserves_specials(self):
        selection=self.selection()
        result=selection.match_sonarr_episode({'id':300,'tvdbId':200},[
            {'id':400,'seriesId':300,'seasonNumber':0,'episodeNumber':7,'tvdbId':201}])
        self.assertEqual(result,(300,400))
        self.assertEqual((selection.anidb_id,selection.anidb_episode_id),(100,101))
        self.assertEqual(selection.media_path,'/staging/Series/Season 00/S00E07.mkv')

    def test_anidb_id_cannot_substitute_for_tvdb_series_id(self):
        with self.assertRaises(KeepSelectionInvalid):self.selection().match_sonarr_episode({'id':300,'tvdbId':100},[])

    def test_wrong_season_duplicate_or_conflicting_tvdb_episode_requires_review(self):
        valid={'id':400,'seriesId':300,'seasonNumber':0,'episodeNumber':7,'tvdbId':201}
        for rows in ([{**valid,'seasonNumber':1}],[valid,valid],[{**valid,'tvdbId':999}]):
            with self.subTest(rows=rows),self.assertRaises(KeepSelectionInvalid):
                self.selection().match_sonarr_episode({'id':300,'tvdbId':200},rows)


class KeepEpisodeMappingTests(unittest.TestCase):
    def test_keep_reuses_identical_verified_episode_mapping(self):
        from src.nextgen.sonarr_episode import VerifiedEpisode, resolve_episode
        identity = VerifiedEpisode(100, 200, 1, 10)
        selection = KeepSelection(1, 2, 100, 200, 1, 10, 1, '/tmp/staging', 'episode.mkv')
        series = {'id': 11, 'tvdbId': 100}
        episodes = [{'id': 22, 'seriesId': 11, 'seasonNumber': 1,
                     'episodeNumber': 10, 'tvdbId': 200}]
        self.assertEqual(resolve_episode(identity, series, episodes),
                         selection.match_sonarr_episode(series, episodes))
        with self.assertRaises(KeepSelectionInvalid):
            selection.match_sonarr_episode(series, [])
