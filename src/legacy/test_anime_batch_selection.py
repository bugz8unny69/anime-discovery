import unittest

from anime_batch_selection import SelectionNeedsReview, plan_first_six


def video(index, name):
    return {"index": index, "name": name, "progress": 0}


class BatchSelectionTests(unittest.TestCase):
    def test_single_episode_preserved(self):
        result = plan_first_six([video(0, "Example Show S01E01.mkv")], season=1)
        self.assertEqual(result["wanted_episodes"], {1: 0})
        self.assertEqual(result["skip_indices"], [])

    def test_full_season_only_first_six(self):
        files = [video(i - 1, "Season 02/Example Show S02E%02d.mkv" % i)
                 for i in range(1, 13)]
        files.append(video(12, "Season 02/readme.txt"))
        result = plan_first_six(files, season=2)
        self.assertEqual(result["wanted_indices"], list(range(6)))
        self.assertEqual(result["skip_indices"], list(range(6, 13)))
        self.assertEqual(result["out_of_window_episodes"], list(range(7, 13)))

    def test_partial_batch_has_no_invented_episodes(self):
        result = plan_first_six(
            [video(i, "Show - %02d.mkv" % (i + 1)) for i in range(4)], season=1)
        self.assertEqual(list(result["wanted_episodes"]), [1, 2, 3, 4])

    def test_already_satisfied_skips_every_file(self):
        result = plan_first_six(
            [video(i, "Show S01E%02d.mkv" % (i + 1)) for i in range(6)],
            season=1, already_satisfied=range(1, 7))
        self.assertEqual(result["wanted_indices"], [])
        self.assertEqual(result["skip_indices"], list(range(6)))

    def test_discovered_sequel_never_crosses_season(self):
        result = plan_first_six([video(5, "Show S02E03.mkv")], season=2)
        self.assertEqual(result["wanted_episodes"], {3: 5})
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([video(0, "Show S01E01.mkv"),
                            video(1, "Show S02E01.mkv")], season=2)

    def test_outside_window_is_never_wanted(self):
        result = plan_first_six([video(0, "Show S01E09.mkv")], season=1)
        self.assertEqual(result["wanted_indices"], [])
        self.assertEqual(result["skip_indices"], [0])

    def test_unmapped_video_fails_closed(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([video(0, "Show Special.mkv")], season=1)

    def test_same_episode_duplicates_fail_closed(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([video(0, "Show S01E01.mkv"),
                            video(1, "Show S01E01 AV1.mkv")], season=1)

    def test_multi_episode_file_requires_review(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([video(0, "Show S01E01E02.mkv")], season=1)

    def test_unsafe_path_fails_closed(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([video(0, "../Season 01/Show S01E01.mkv")], season=1)

    def test_folder_season_can_resolve_episode(self):
        result = plan_first_six([video(0, "Season 02/Show - 01.mkv")], season=2)
        self.assertEqual(result["wanted_episodes"], {1: 0})

    def test_incomplete_manifest_requires_review(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([], season=1)


if __name__ == "__main__":
    unittest.main()
