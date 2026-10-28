"""Season-aware NextGen title discovery remains strict about provider identity."""
import asyncio
import json
import threading
import unittest
from unittest.mock import patch

from src.nextgen.matching import MatchingTrace
from src.nextgen.providers.http import Credentials, Options
from src.nextgen.providers.identity import explicit_sequel_alias, make_resolver
from src.nextgen.storage.sqlite import IdentityConflict, IdentityNotReady
from src.nextgen.storage.migrations import LATEST_VERSION


RELEASE = "[Dyna] Higurashi When They Cry S02 (BD 1080p AVC Opus 2.0) [Dual Audio] | Higurashi Sotsu"


class Configuration:
    def value(self, name):
        if name != "storage.database_path":
            raise AssertionError(name)
        return "/nonexistent/nextgen-test.db"


class Delivery:
    def __init__(self, name):
        self.raw_body = json.dumps({"release_name": name}).encode()


class Provider:
    def __init__(self):
        self.queries = []
        self.season_lookups = []
        self.candidates = {15105: ("Higurashi Sotsu",)}
        self.tvdb_titles = ("Higurashi Sotsu",)

    def title_candidates(self, aliases):
        self.queries.append(tuple(aliases))
        return self.candidates

    def anime(self, aid):
        if aid == 17000:
            return {"title": "Youjo Senki II", "titles": ("Youjo Senki II",)}
        return {"title": "Higurashi Sotsu", "titles": ("Higurashi Sotsu",)}

    def mapping(self, aid):
        return 12345

    def season_entry(self, tid, season, episode=None):
        self.season_lookups.append((tid, season, episode))
        return 17000


    def series(self, tid, credentials):
        return {"titles": self.tvdb_titles, "animation": True, "live": False,
                "anidb_ids": frozenset({15105})}


class SequelDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def make_resolver(self, provider):
        return make_resolver(
            Options("nextgen_tests", 1), lambda: Credentials("dummy-test-key"),
            client_factory=lambda db, opts: provider,
        )

    async def identify(self, title, provider):
        trace = MatchingTrace()
        db_patch = patch("src.nextgen.providers.identity._open")
        recognized_patch = patch(
            "src.nextgen.providers.identity.recognized_for_release",
            return_value=None,
        )
        with db_patch as opener, recognized_patch:
            opener.return_value.execute.return_value.fetchone.return_value = (LATEST_VERSION,)
            result = await self.make_resolver(provider)(
                Delivery(title), Configuration(), threading.Event(), matching=trace
            )
        return result, trace.data

    async def test_explicit_s02_title_uses_distinct_sequel_lookup(self):
        provider = Provider()
        result, trace = await self.identify(RELEASE, provider)
        self.assertEqual(provider.queries, [("Higurashi Sotsu",)])
        self.assertEqual(result["anime"]["anidb_id"], 15105)
        self.assertEqual(trace["season"], 2)
        self.assertEqual(trace["queries"], ["Higurashi Sotsu"])
        self.assertIn(
            {"step": "season_scope", "status": "passed", "note": "sequel_alias_selected"},
            trace["checks"],
        )
        self.assertEqual(trace["selected_tvdb_id"], 12345)

    async def test_s01_keeps_original_lookup(self):
        provider = Provider()
        await self.identify("[Dyna] Higurashi When They Cry S01 E01 | Higurashi Sotsu", provider)
        self.assertEqual(provider.queries, [("Higurashi When They Cry",)])

    async def test_ambiguous_candidates_cannot_be_approved(self):
        provider = Provider()
        provider.candidates = {
            15105: ("Higurashi Sotsu",),
            15106: ("Higurashi Sotsu",),
        }
        with self.assertRaises(IdentityNotReady):
            await self.identify(RELEASE, provider)

    async def test_provider_disagreement_is_still_rejected(self):
        provider = Provider()
        provider.tvdb_titles = ("A Different Show",)
        with self.assertRaises(IdentityConflict):
            await self.identify(RELEASE, provider)

    async def test_plain_s02_title_uses_anime_lists_season_entry(self):
        # No "| Sequel" suffix: identify the base series, then take its season 2 entry.
        provider = Provider()
        provider.candidates = {15105: ("Saga of Tanya the Evil",)}
        provider.anime = lambda aid: ({"title": "Youjo Senki II", "titles": ("Youjo Senki II",)}
            if aid == 17000 else {"title": "Youjo Senki", "titles": ("Youjo Senki", "Saga of Tanya the Evil")})
        provider.tvdb_titles = ("Saga of Tanya the Evil",)
        result, trace = await self.identify(
            "Saga of Tanya the Evil S02E08 Torpedo Strike 1080p CR WEB-DL DUAL AAC2.0 H.264-VARYG "
            "(Youjo Senki II, Dual-Audio, Multi-Subs)", provider)
        self.assertEqual(provider.queries, [("Saga of Tanya the Evil",)])
        self.assertEqual(provider.season_lookups, [(12345, 2, 8)])
        self.assertEqual(result["anime"], {"anidb_id": 17000, "tvdb_series_id": 12345,
                                           "title": "Youjo Senki II"})
        self.assertIn({"step": "season_scope", "status": "passed",
                       "note": "base_series_season_lookup"}, trace["checks"])

    async def test_season_lookup_still_requires_base_title_agreement(self):
        provider = Provider()
        provider.candidates = {15105: ("Saga of Tanya the Evil",)}
        provider.anime = lambda aid: {"title": "Youjo Senki", "titles": ("Saga of Tanya the Evil",)}
        provider.tvdb_titles = ("A Different Show",)
        with self.assertRaises(IdentityConflict):
            await self.identify("Saga of Tanya the Evil S02E08 1080p", provider)

    def test_anime_lists_season_entry_selection(self):
        from src.nextgen.providers.parsing import season_entry
        payload = (b'<anime-list>'
            b'<anime anidbid="100" tvdbid="5" defaulttvdbseason="1"/>'
            b'<anime anidbid="200" tvdbid="5" defaulttvdbseason="2"/>'
            b'<anime anidbid="201" tvdbid="5" defaulttvdbseason="2" episodeoffset="12"/>'
            b'<anime anidbid="300" tvdbid="5" defaulttvdbseason="a"/>'
            b'<anime anidbid="400" tvdbid="6" defaulttvdbseason="2"/>'
            b'</anime-list>')
        self.assertEqual(season_entry(payload, 5, 2, 8), 200)    # first cour
        self.assertEqual(season_entry(payload, 5, 2, 15), 201)   # split second cour
        self.assertEqual(season_entry(payload, 6, 2), 400)
        with self.assertRaises(IdentityNotReady):
            season_entry(payload, 5, 3, 1)
        with self.assertRaises(IdentityConflict):
            season_entry(payload.replace(b'episodeoffset="12"', b''), 5, 2, 8)

    def test_no_distinct_sequel_title_is_not_first_season_proof(self):
        self.assertIsNone(explicit_sequel_alias(
            "[Dyna] Higurashi When They Cry S02 (BD 1080p)",
            ["Higurashi When They Cry"],
        ))
        self.assertIsNone(explicit_sequel_alias(
            "Higurashi When They Cry S02 | BD 1080p",
            ["Higurashi When They Cry"],
        ))


if __name__ == "__main__":
    unittest.main()
