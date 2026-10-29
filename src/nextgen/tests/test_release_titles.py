"""How release groups name single episodes, and which ones match a target episode."""
import unittest

from src.nextgen.acquisition.prowlarr_search import EpisodeTarget, declared_title
from src.nextgen.acquisition.release_titles import (
    AnimeTitles, matches, parse_release, search_queries, season_marker,
)
from src.nextgen.providers.release_mapping import declared_episode

SEASON_ONE = ('Kusuriya no Hitorigoto', 'The Apothecary Diaries', '薬屋のひとりごと')
SEQUEL = ('Kusuriya no Hitorigoto (2025)', 'Kusuriya no Hitorigoto 2nd Season',
          'The Apothecary Diaries Season 2', '薬屋のひとりごと 第2期')

# (anime titles, TVDB season, (TVDB episode, AniDB episode, absolute), release, matches?)
CASES = (
    # Season 1, episode 5: the usual group styles.
    (SEASON_ONE, 1, (5, 5, 5), '[SubsPlease] Kusuriya no Hitorigoto - 05 (1080p) [ABCD1234].mkv', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Erai-raws] Kusuriya no Hitorigoto - 05 [1080p][Multiple Subtitle][ABCD]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Judas] Kusuriya no Hitorigoto - S01E05 [1080p][HEVC x265 10bit][Multi-Subs]', True),
    (SEASON_ONE, 1, (5, 5, 5), 'The.Apothecary.Diaries.S01E05.1080p.NF.WEB-DL.DDP2.0.H.264-VARYG', True),
    (SEASON_ONE, 1, (5, 5, 5), 'Kusuriya no Hitorigoto S01E05 1080p CR WEB-DL AAC2.0 H 264-VARYG', True),
    (SEASON_ONE, 1, (5, 5, 5), '[ASW] Kusuriya no Hitorigoto - 05 [1080p HEVC x265 10Bit][AAC]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto | The Apothecary Diaries - 05 (1080p)', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto (The Apothecary Diaries) - 05 [1080p]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[EMBER] Kusuriya no Hitorigoto - 05v2 [1080p]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto - Episode 05 [1080p]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto Ep 05 [1080p]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto 05 [1080p]', True),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya_no_Hitorigoto_-_05_[1080p].mkv', True),
    # Not this episode, or not one episode.
    (SEASON_ONE, 1, (5, 5, 5), '[SubsPlease] Kusuriya no Hitorigoto - 06 (1080p)', False),
    (SEASON_ONE, 1, (5, 5, 5), '[SubsPlease] Kusuriya no Hitorigoto (01-24) (1080p) [Batch]', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto - 01~12 [1080p]', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto - 05-06 [1080p]', False),
    (SEASON_ONE, 1, (5, 5, 5), 'Kusuriya no Hitorigoto S01E05E06 1080p WEB', False),
    (SEASON_ONE, 1, (5, 5, 5), 'Kusuriya no Hitorigoto S01E05-E06 1080p WEB', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto - 05.5 [1080p]', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto - 05 [OVA]', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto S2 - 05 (1080p)', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto S02E05 (1080p)', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto Movie - 05 (1080p)', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Other Show - 05 (1080p)', False),
    (SEASON_ONE, 1, (5, 5, 5), '[Group] Kusuriya no Hitorigoto Gaiden - 05 (1080p)', False),
    # Sequel whose TVDB entry is season 2 (season 1 had 24 episodes).
    (SEQUEL, 2, (5, 5, 29), '[SubsPlease] Kusuriya no Hitorigoto - 29 (1080p)', True),
    (SEQUEL, 2, (5, 5, 29), '[Erai-raws] Kusuriya no Hitorigoto 2nd Season - 05 [1080p CR WEB-DL AVC AAC][MultiSub]', True),
    (SEQUEL, 2, (5, 5, 29), '[Group] Kusuriya no Hitorigoto S2 - 05 (1080p)', True),
    (SEQUEL, 2, (5, 5, 29), '[Group] Kusuriya no Hitorigoto Season 2 - 05 (1080p)', True),
    (SEQUEL, 2, (5, 5, 29), '[Group] Kusuriya no Hitorigoto Second Season - 05 (1080p)', True),
    (SEQUEL, 2, (5, 5, 29), 'Kusuriya no Hitorigoto S02E05 1080p CR WEB-DL AAC2.0 H 264-VARYG', True),
    (SEQUEL, 2, (5, 5, 29), 'The Apothecary Diaries S02E05 1080p WEB', True),
    (SEQUEL, 2, (5, 5, 29), '[Group] Kusuriya no Hitorigoto (2025) - 05 [1080p]', True),
    (SEQUEL, 2, (5, 5, 29), '[SubsPlease] Kusuriya no Hitorigoto - 05 (1080p)', False),  # Season 1 episode 5.
    (SEQUEL, 2, (5, 5, 29), '[Judas] Kusuriya no Hitorigoto - S01E05 [1080p]', False),
    (SEQUEL, 2, (5, 5, 29), '[Group] Kusuriya no Hitorigoto S3 - 05 (1080p)', False),
    (SEQUEL, 2, (5, 5, 29), '[Group] Kusuriya no Hitorigoto Season 2 - 06 (1080p)', False),
    # Same sequel where TVDB keeps one continuous season (episode 29).
    (SEQUEL, 1, (29, 5, 29), '[SubsPlease] Kusuriya no Hitorigoto - 29 (1080p)', True),
    (SEQUEL, 1, (29, 5, 29), '[Group] Kusuriya no Hitorigoto S2 - 05 (1080p)', True),
    (SEQUEL, 1, (29, 5, 29), 'Kusuriya no Hitorigoto S02E05 1080p WEB', True),
    (SEQUEL, 1, (29, 5, 29), 'Kusuriya no Hitorigoto S01E29 1080p WEB', True),
    (SEQUEL, 1, (29, 5, 29), '[SubsPlease] Kusuriya no Hitorigoto - 05 (1080p)', False),
    # Titles that end in numbers or carry their own season numbering.
    (('Mob Psycho 100',), 1, (5, 5, 5), '[Group] Mob Psycho 100 - 05 [1080p]', True),
    (('Mob Psycho 100',), 1, (5, 5, 5), '[Group] Mob Psycho 100 [1080p]', False),
    (('Mob Psycho 100 III', 'Mob Psycho 100 Season 3'), 3, (5, 5, 29),
     '[Group] Mob Psycho 100 III - 05 [1080p]', True),
    (('Mob Psycho 100 III', 'Mob Psycho 100 Season 3'), 3, (5, 5, 29),
     '[Group] Mob Psycho 100 - 05 [1080p]', False),
)


class ReleaseTitleTests(unittest.TestCase):
    def test_group_naming_styles(self):
        for titles, season, (n, a, absolute), release, expected in CASES:
            target = EpisodeTarget(n, 'SEARCHABLE', a, 9000 + n, absolute)
            with self.subTest(release=release, season=season):
                self.assertEqual(matches(parse_release(release), AnimeTitles.build(titles, season),
                                         target, season), expected)

    def test_season_markers(self):
        self.assertEqual(season_marker('Title 2nd Season'), ('Title', 2))
        self.assertEqual(season_marker('Title Season 3'), ('Title', 3))
        self.assertEqual(season_marker('Title S4'), ('Title', 4))
        self.assertEqual(season_marker('Title II'), ('Title', 2))
        self.assertEqual(season_marker('Title (2025)'), ('Title (2025)', None))

    def test_verification_title_is_always_readable(self):
        for titles in (SEASON_ONE, SEQUEL, ('Mob Psycho 100',), ('Re:Zero kara Hajimeru Isekai Seikatsu',)):
            with self.subTest(titles=titles):
                self.assertEqual(declared_episode(declared_title(titles, 7)), ('anidb', None, 7))

    def test_queries_reach_absolute_and_season_styles(self):
        target = EpisodeTarget(5, 'SEARCHABLE', 5, 9005, 29)
        queries = search_queries(SEQUEL, AnimeTitles.build(SEQUEL, 2), target)
        self.assertIn('Kusuriya no Hitorigoto 05', queries)
        self.assertIn('Kusuriya no Hitorigoto 29', queries)
        self.assertIn('Kusuriya no Hitorigoto S02E05', queries)
        self.assertLessEqual(len(queries), 6)


if __name__ == '__main__':
    unittest.main()
