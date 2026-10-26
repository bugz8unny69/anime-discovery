"""Offline tests of advisory batch classification and pure selection planning."""
import unittest

from src.nextgen.acquisition.metadata import BatchInventory, TorrentFile
from src.nextgen.batch.recognition import release_scope_hint
from src.nextgen.batch.selection import BatchPlanningError, plan_verified_batch


def inventory(*paths):
    return BatchInventory('a' * 40, 'b' * 64, tuple(TorrentFile(i, p, 100) for i, p in enumerate(paths)))


class BatchHintsTests(unittest.TestCase):
    def test_shiki_mixed_regular_season_and_ova(self):
        hint = release_scope_hint('[Sristi] Shiki (S01 + OVA) [BD Remux 1080p]')
        self.assertEqual((hint.kind, hint.season_hint, hint.episode_hint), ('mixed_pack', 1, None))

    def test_season_two_batch_and_single_episode(self):
        self.assertEqual(release_scope_hint('[Trix] Cyberpunk Edgerunners S02 (Season S2) (Batch)').kind,
                         'season_pack')
        self.assertEqual(release_scope_hint('Show S02E03').kind, 'single_episode')
        self.assertEqual(release_scope_hint('Show S02E03').season_hint, 2)
        self.assertEqual(release_scope_hint('Show S02E03').episode_hint, 3)

    def test_ambiguous_and_special_titles_are_not_regular_episodes(self):
        for title in ('Show S01E01 + S02E01', 'Show S01E01E02', 'Show S01E01-02'):
            with self.subTest(title=title):
                self.assertEqual(release_scope_hint(title).kind, 'ambiguous')
        self.assertEqual(release_scope_hint('Show S00E05 OVA').kind, 'special')
        self.assertEqual(release_scope_hint('Shiki OVA').kind, 'special')


class ManifestSelectionTests(unittest.TestCase):
    def test_shiki_season_with_ova_and_sidecars(self):
        names = tuple(f'Shiki/Season 01/Shiki S01E{i:02d}.mkv' for i in range(1, 13)) + (
            'Shiki/OVA/Shiki OVA 01.mkv', 'Shiki/Season 01/info.nfo')
        plan = plan_verified_batch(inventory(*names), season=1,
                                   episode_map={i: i for i in range(1, 13)})
        self.assertEqual(plan.probe_index, 0)
        self.assertEqual(plan.episode_indices, tuple((i, i-1) for i in range(1, 7)))
        self.assertEqual(plan.remaining_indices, (1, 2, 3, 4, 5))
        self.assertEqual(plan.extra_indices, (12,))
        self.assertEqual(plan.skipped_indices, tuple(range(6, 14)))

    def test_absolute_episode_mapping_requires_explicit_map(self):
        files = inventory(*[f'Show/Season 02/Show - {i:02d}.mkv' for i in range(13, 25)])
        with self.assertRaises(BatchPlanningError):
            plan_verified_batch(files, season=2, episode_map={i: i for i in range(1, 13)})
        plan = plan_verified_batch(files, season=2,
                                   episode_map={i: i-12 for i in range(13, 25)})
        self.assertEqual(plan.episode_indices, tuple((i, i-1) for i in range(1, 7)))

    def test_unsafe_ambiguity_stops_entire_plan(self):
        cases = (
            ('Show/Season 01/Show S01E01.mkv', 'Show/Season 01/Show S01E01 alt.mkv'),
            ('Show/Season 01/Show S01E01.mkv', 'Show/Season 02/Show S02E02.mkv'),
            ('Show/Season 01/Show S01E01.mkv', 'Show/Season 01/Show S01E01E02.mkv'),
            ('Show/Season 01/Show S01E01.mkv', 'Show/Season 01/Unknown.mkv'),
            ('Show/Season 01/Show S01E01.mkv', 'Show/Season 01/Show - 2026.mkv'),
            ('Show/Season 01/Show S01E01.mkv', 'Show/Season 01/Show S01E02 OVA.mkv'),
        )
        for names in cases:
            with self.subTest(names=names), self.assertRaises(BatchPlanningError):
                plan_verified_batch(inventory(*names), season=1, episode_map={1: 1, 2: 2})

    def test_no_first_episode_or_bogus_mapping_never_produces_plan(self):
        with self.assertRaises(BatchPlanningError):
            plan_verified_batch(inventory('Show/Season 01/Show E03.mkv'), season=1,
                                episode_map={3: 3})
        with self.assertRaises(ValueError):
            plan_verified_batch(inventory('Show/Season 01/Show E01.mkv'), season=1,
                                episode_map={1: 1, 2: 1})


if __name__ == '__main__':
    unittest.main()
