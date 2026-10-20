import unittest

from anime_batch_selection import SelectionNeedsReview, plan_first_six, plan_gated_first_six, release_scope_hint


def video(index, name):
    return {"index": index, "name": name, "progress": 0}


class BatchSelectionTests(unittest.TestCase):

    def test_cyberpunk_s2_batch_release_is_hint_not_episode(self):
        title=("[Trix] Cyberpunk Edgerunners S02 1080p NF WEB-DL "
               "Opus2.0 AV1 (Dual-Audio, Multi-Subs) (Season S2) (Batch)")
        hint=release_scope_hint(title)
        self.assertEqual(hint["kind"], "season_pack")
        self.assertEqual(hint["season_hint"], 2)
        self.assertIsNone(hint["episode_hint"])

    def test_konosuba_s00e05_is_a_special_not_regular_e05(self):
        title=("[Anime Time] KonoSuba - God's Blessing On This "
               "Wonderful World - S00E05 - Movie Legend Of Crimson "
               "(Fixed Subs Fonts) [BD] [Dual Audio][1080p]")
        hint=release_scope_hint(title)
        self.assertEqual(hint, {"kind":"special", "season_hint":0,
                                "episode_hint":5})
        with self.assertRaises(SelectionNeedsReview):
            plan_first_six([video(0, "KonoSuba S00E05.mkv")],season=1)

    def test_mixed_season_release_hints_are_not_trusted(self):
        hint=release_scope_hint("Show S01E01 + S02E01 Batch")
        self.assertEqual(hint["kind"], "ambiguous_season")


    def test_probe_downloads_only_e01_then_unblocks_five(self):
        files=[video(i-1,"Season 02/Anime S02E%02d.mkv" % i)
               for i in range(1,13)]
        probe=plan_gated_first_six(files,season=2)
        self.assertEqual(probe["phase"],"PROBE_E01")
        self.assertEqual(probe["wanted_episodes"],{1:0})
        self.assertEqual(probe["wanted_indices"],[0])
        self.assertEqual(probe["skip_indices"],list(range(1,12)))
        unlocked=plan_gated_first_six(files,season=2,probe_verified=True)
        self.assertEqual(unlocked["phase"],"UNLOCK_E02_E06")
        self.assertEqual(unlocked["wanted_indices"],list(range(6)))
        self.assertEqual(unlocked["skip_indices"],list(range(6,12)))

    def test_failed_probe_does_not_unlock_remaining_files(self):
        files=[video(i,"Anime S01E%02d.mkv"%(i+1)) for i in range(10)]
        failed=plan_gated_first_six(files,season=1,probe_verified=False)
        self.assertEqual(failed["wanted_indices"],[0])
        self.assertNotIn(1,failed["wanted_indices"])
        self.assertEqual(failed["skip_indices"],list(range(1,10)))

    def test_verified_existing_e01_allows_remaining_without_redownload(self):
        files=[video(i,"Anime S01E%02d.mkv"%(i+1)) for i in range(10)]
        held=plan_gated_first_six(files,season=1,
                                  already_satisfied=[1])
        self.assertEqual(held["wanted_indices"],[])
        unlocked=plan_gated_first_six(files,season=1,
                    already_satisfied=[1],probe_verified=True)
        self.assertEqual(unlocked["wanted_indices"],list(range(1,6)))
        self.assertEqual(unlocked["skip_indices"],[0,6,7,8,9])

    def test_batch_without_e01_requires_separate_episode_search(self):
        files=[video(0,"Anime S01E03.mkv"),video(1,"Anime S01E04.mkv")]
        with self.assertRaisesRegex(SelectionNeedsReview,"E01"):
            plan_gated_first_six(files,season=1)

    def test_invalid_probe_evidence_flag_fails_closed(self):
        with self.assertRaises(ValueError):
            plan_gated_first_six([video(0,"Anime S01E01.mkv")],
                                 season=1,probe_verified="yes")


    def test_common_group_episode_one_formats(self):
        for filename in (
            "[Group] Anime [01][Dual Audio].mkv",
            "[Group] Anime (01) [1080p].mkv",
            "Anime 2x01.mkv",
            "Anime S02 - 01 [HEVC].mkv",
            "[Group] Anime 第01話.mkv",
            "Season 02/01.mkv",
            "S02/Anime - 01.mkv",
            "Anime - 01v2 [1080p].mkv",
        ):
            with self.subTest(filename=filename):
                result = plan_gated_first_six([video(0, filename)],season=2)
                self.assertEqual(result["wanted_episodes"],{1:0})

    def test_unknown_file_number_not_assumed_e01_from_order(self):
        for filename in (
            "Anime 01.mkv", "Anime Special.mkv",
            "Anime [Dual Audio].mkv", "Anime - 1080p.mkv"
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(SelectionNeedsReview):
                    plan_gated_first_six([video(0, filename)], season=2)

    def test_ranged_episodes_are_not_accepted_as_single_e01(self):
        for filename in (
            "Anime - 01-02.mkv", "Anime - 01+02.mkv",
            "Anime - 01 to 02.mkv", "Anime S02E01-02.mkv",
            "Anime S02E01E02.mkv", "Anime [01][02].mkv",
            "Anime 2x01-02.mkv",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(SelectionNeedsReview):
                    plan_gated_first_six([video(0, filename)], season=2)

    def test_conflicting_season_hints_never_select_e01(self):
        for filename in (
            "Anime S01 - 01.mkv",
            "Season 01/Anime S02E01.mkv",
            "Season 02/Anime 1x01.mkv",
            "S01/Anime [01].mkv",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(SelectionNeedsReview):
                    plan_gated_first_six([video(0, filename)], season=2)

    def test_absolute_13_not_assumed_to_be_season_two_e01(self):
        files=[video(i, "Anime - %02d.mkv" % (i + 13))
               for i in range(12)]
        with self.assertRaisesRegex(SelectionNeedsReview,"E01"):
            plan_gated_first_six(files,season=2)

    def test_group_format_all_first_six_then_skips_later_episodes(self):
        files=[video(i,"[Group] Anime [%02d] [1080p].mkv"%(i+1))
               for i in range(12)]
        plan=plan_gated_first_six(files,season=2)
        self.assertEqual(plan["wanted_indices"],[0])
        self.assertEqual(plan["skip_indices"],list(range(1,12)))
        after=plan_gated_first_six(files,season=2,probe_verified=True)
        self.assertEqual(after["wanted_indices"],list(range(6)))
        self.assertEqual(after["skip_indices"],list(range(6,12)))

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
