"""Regression tests for multilingual candidate title evidence."""
import unittest
from unittest.mock import patch
from anime_identification_probe import norm, release_title, tvdb_candidates
from anime_unified_identity_monitor import title_diagnostics

class MultilingualTitleTests(unittest.TestCase):
    def test_unicode_normalization(self):
        self.assertEqual(norm("カタカナ"), "カタカナ")
        self.assertEqual(norm("日本語"), "日本語")
        self.assertEqual(norm("한글"), "한글")
        self.assertEqual(norm("ＳＯＬＯ Leveling!"), "sololeveling")
        self.assertEqual(norm("Ore dake Level Up na Ken"), "oredakelevelupnaken")

    def test_dual_named_release(self):
        names, episode = release_title("[MiniDual] Ore dake Level Up na Ken (Solo Leveling) - 01 (Dual-Audio) [1080p] [Jpn,Eng dub]")
        self.assertEqual(episode, 1)
        self.assertIn("Solo Leveling", names)

    def test_provider_aliases_survive_and_queries_are_not_evidence(self):
        data={"data":[{"tvdb_id":"389597","name":"俺だけレベルアップな件",
                       "aliases":[{"name":"Solo Leveling"},"Ore dake Level Up na Ken"]},
                      {"tvdb_id":"446883","name":"The Leveling of Solo Leveling"},
                      {"tvdb_id":"465668","name":"나 혼자만 레벨업"}]}
        with patch("anime_identification_probe.tvdb_token",return_value="token"), patch(
                "anime_identification_probe.request_json",return_value=data):
            records, errors = tvdb_candidates(["Solo Leveling"],"secret")
        self.assertFalse(errors)
        scored=title_diagnostics(["Solo Leveling"],records,90)
        by_id={x["tvdb_id"]:x for x in scored}
        self.assertEqual(by_id["389597"]["score_pct"],100)
        self.assertEqual(by_id["389597"]["best_candidate_title"],"Solo Leveling")
        self.assertFalse(by_id["446883"]["passed"])
        self.assertFalse(by_id["465668"]["passed"])
        self.assertEqual(by_id["465668"]["reason"],"BELOW_TITLE_THRESHOLD")

    def test_empty_evidence_not_false_positive(self):
        scores=title_diagnostics(["Solo Leveling"],[
            {"tvdb_id":"1","matched_query":"Solo Leveling","name":""}],90)
        self.assertEqual(scores[0]["reason"],"NO_USABLE_CANDIDATE_TITLES")
        self.assertEqual(scores[0]["score_pct"],0)
        self.assertFalse(scores[0]["passed"])

if __name__=="__main__":
    unittest.main()
