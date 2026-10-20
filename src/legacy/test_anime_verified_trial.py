"""Provider-verified numbering maps: relative, absolute, split cours, continuous."""
import unittest
from anime_batch_selection import plan_verified_trial, SelectionNeedsReview


def files(names):
    return [{"index":i,"name":n,"priority":1,"size":1000}
            for i,n in enumerate(names)]


class VerifiedTrialTests(unittest.TestCase):
    def test_second_season_starts_at_one(self):
        names=["Season 02/Anime S02E%02d.mkv"%x for x in range(1,13)]
        mapping={x:x for x in range(1,13)}
        plan=plan_verified_trial(files(names),season=2,start_episode=1,
                                 episode_map=mapping)
        self.assertEqual(plan["wanted_indices"],[0])
        self.assertEqual(plan["skip_indices"],list(range(1,12)))
        unlocked=plan_verified_trial(files(names),season=2,start_episode=1,
                            episode_map=mapping,probe_verified=True)
        self.assertEqual(unlocked["wanted_indices"],list(range(6)))
        self.assertEqual(unlocked["out_of_window_episodes"],list(range(7,13)))

    def test_second_season_absolute_thirteen_becomes_canonical_one(self):
        names=["Season 02/Anime S02E%02d.mkv"%x for x in range(13,25)]
        mapping={x:x-12 for x in range(13,25)}  # must be provider-confirmed
        plan=plan_verified_trial(files(names),season=2,start_episode=1,
                                 episode_map=mapping)
        self.assertEqual(plan["wanted_episodes"],{1:0})
        unlocked=plan_verified_trial(files(names),season=2,start_episode=1,
                            episode_map=mapping,probe_verified=True)
        self.assertEqual(unlocked["wanted_indices"],list(range(6)))
        self.assertEqual(unlocked["skip_indices"],list(range(6,12)))

    def test_season_one_part_two_resets_release_episode_to_one(self):
        names=["Season 01/Anime S01 Part 2 - %02d.mkv"%x for x in range(1,13)]
        mapping={x:x+12 for x in range(1,13)}
        selected=plan_verified_trial(files(names),season=1,start_episode=13,
                            episode_map=mapping)
        self.assertEqual(selected["wanted_episodes"],{13:0})
        after=plan_verified_trial(files(names),season=1,start_episode=13,
                            episode_map=mapping,probe_verified=True)
        self.assertEqual(list(after["wanted_episodes"]),list(range(13,19)))
        self.assertEqual(after["skip_indices"],list(range(6,12)))

    def test_part_two_continues_absolute_13(self):
        names=["Season 01/Anime S01 Part 2 - %02d.mkv"%x for x in range(13,25)]
        mapping={x:x for x in range(13,25)}
        selected=plan_verified_trial(files(names),season=1,start_episode=13,
                            episode_map=mapping)
        self.assertEqual(selected["wanted_episodes"],{13:0})

    def test_ongoing_series_1001_window(self):
        names=["Anime - %04d.mkv"%x for x in range(1001,1013)]
        mapping={x:x for x in range(1001,1013)}
        first=plan_verified_trial(files(names),season=1,start_episode=1001,
                            episode_map=mapping)
        self.assertEqual(first["wanted_indices"],[0])
        unlocked=plan_verified_trial(files(names),season=1,start_episode=1001,
                            episode_map=mapping,probe_verified=True)
        self.assertEqual(unlocked["wanted_indices"],list(range(6)))
        self.assertEqual(unlocked["out_of_window_episodes"],list(range(1007,1013)))

    def test_file_order_not_assumed_to_equal_episode_order(self):
        names=["Anime - 1003.mkv","Anime - 1001.mkv",
               "Anime - 1002.mkv","Anime - 1007.mkv"]
        mapping={x:x for x in range(1001,1008)}
        p=plan_verified_trial(files(names),season=1,start_episode=1001,
                              episode_map=mapping)
        self.assertEqual(p["wanted_indices"],[1])
        self.assertEqual(p["skip_indices"],[0,2,3])

    def test_missing_verified_map_or_first_episode_fails_closed(self):
        names=["Anime - 13.mkv","Anime - 14.mkv"]
        with self.assertRaisesRegex(SelectionNeedsReview,"lacks verified mapping"):
            plan_verified_trial(files(names),season=2,start_episode=1,
                                episode_map={13:1})
        with self.assertRaisesRegex(SelectionNeedsReview,"First trial episode"):
            plan_verified_trial(files(names),season=2,start_episode=1,
                                episode_map={13:2,14:3})
        with self.assertRaises(ValueError):
            plan_verified_trial(files(names),season=2,start_episode=1,
                                episode_map={13:1,14:1})

    def test_release_year_is_not_episode_one(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_verified_trial(files(["Anime [2026].mkv"]),season=1,
                                start_episode=1,episode_map={2026:1})

    def test_multi_episode_file_stays_rejected(self):
        with self.assertRaises(SelectionNeedsReview):
            plan_verified_trial(files(["Anime - 1001-1002.mkv"]),season=1,
                                start_episode=1001,episode_map={1001:1001})


if __name__=="__main__":
    unittest.main()
