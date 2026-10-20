"""Offline regressions for AniDB/TVDB search pollution from Nyaa release names."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from anime_identification_probe import (
    anidb_matches, release_title, tvdb_candidates)
from anime_unified_identity_monitor import investigate


CYBERPUNK=("[Trix] Cyberpunk Edgerunners S02 1080p NF WEB-DL "
           "Opus2.0 AV1 (Dual-Audio, Multi-Subs) (Season S2) (Batch)")
KONOSUBA=("[Anime Time] KonoSuba - God's Blessing On This "
          "Wonderful World - S00E05 - Movie Legend Of Crimson "
          "(Fixed Subs Fonts) [BD] [Dual Audio][1080p]")


class ReleaseTitleTests(unittest.TestCase):
    def test_clean_cyberpunk_batch_aliases(self):
        aliases, episode=release_title(CYBERPUNK)
        self.assertEqual(aliases, ["Cyberpunk Edgerunners"])
        self.assertIsNone(episode)
        for pollution in ("Batch","Season S2","1080p","WEB-DL","AV1"):
            self.assertTrue(all(pollution not in x for x in aliases))

    def test_season_zero_special_is_parsed_without_relabeling(self):
        aliases, episode=release_title(KONOSUBA)
        self.assertEqual(aliases,
                         ["KonoSuba - God's Blessing On This Wonderful World"])
        self.assertEqual(episode,5)

    def test_existing_fansub_episode_form(self):
        self.assertEqual(release_title("[Group] Example Show - 02 (1080p)"),
                         (["Example Show"],2))
        self.assertEqual(release_title("[Group] Example.Show.S01E06.mkv"),
                         (["Example Show"],6))

    def test_parenthetical_true_alternate_title_is_preserved(self):
        aliases,ep=release_title("[Group] Test Show (Alternate Title) - 02")
        self.assertIn("Test Show (Alternate Title)",aliases)
        self.assertIn("Test Show",aliases)
        self.assertIn("Alternate Title",aliases)
        self.assertEqual(ep,2)

    def test_episode_label_without_season(self):
        self.assertEqual(release_title("Show Episode 05 [1080p]"),
                         (["Show"],5))

    def test_clean_queries_only_to_tvdb(self):
        queries=[]
        def request(url,bearer=None):
            queries.append(parse_qs(urlsplit(url).query)["query"][0])
            return {"data":[]}
        with patch("anime_identification_probe.tvdb_token",
                   return_value="safe-token"), patch(
                     "anime_identification_probe.request_json",
                     side_effect=request):
            candidates,errors=tvdb_candidates(release_title(CYBERPUNK)[0],
                                               "test-key")
        self.assertEqual(queries,["Cyberpunk Edgerunners"])
        self.assertEqual(candidates,[])
        self.assertEqual(errors,[])

    def test_clean_title_can_match_anidb_punctuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"titles.xml"
            path.write_text('<animetitles><anime aid="123">'
                            '<title>Cyberpunk: Edgerunners</title>'
                            '</anime></animetitles>',encoding="utf-8")
            rows,truncated=anidb_matches(path,release_title(CYBERPUNK)[0])
        self.assertFalse(truncated)
        self.assertEqual(rows[0]["anidb_id"],"123")

    def test_no_ambiguous_flag_for_irrelevant_tvdb_noise(self):
        clean=release_title(CYBERPUNK)[0]
        noise=[{"tvdb_id":str(i+10000), "name":"Other show %s"%i,
                "candidate_titles":["Other show %s"%i]}
               for i in range(16)]
        match={"tvdb_id":"123","name":"Cyberpunk: Edgerunners",
               "candidate_titles":["Cyberpunk: Edgerunners"]}
        candidates=noise+[match]
        fetched=[]
        def fetch(url,bearer=None):
            fetched.append(url)
            return {"data":{"id":123,
                    "remoteIds":[{"sourceName":"AniDB","id":"456"}]}}
        settings={"identity":{"match_threshold_pct":90},
                  "anidb":{"enabled":True},
                  "tvdb":{"enabled":True}}
        with patch("anime_unified_identity_monitor.anidb_matches",
                   return_value=([{"anidb_id":"456",
                       "matched_titles":["Cyberpunk: Edgerunners"]}],False)):
            report=investigate(CYBERPUNK,settings,
                {"tvdb_api_key":"offline-token"},None,
                search=lambda aliases,key:(candidates,[]),
                login=lambda key:"session",fetch=fetch)
        self.assertEqual(report["title_queries"],clean)
        self.assertEqual(report["tvdb_results_count"],17)
        self.assertEqual(len(report["matching_pairs"]),1)
        self.assertEqual(report["matching_pairs"][0]["tvdb_id"],"123")
        self.assertNotIn("AMBIGUOUS_TVDB_CANDIDATES",report["issues"])
        self.assertIn("BATCH_FILE_MANIFEST_REQUIRED",report["issues"])
        self.assertNotEqual(report["decision"],"AUTO_VERIFIED")
        self.assertEqual(len(fetched),1)


if __name__=="__main__":
    unittest.main()
