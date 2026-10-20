"""Offline zero-touch alternate season-pack fallback tests. No real torrents."""
import sqlite3
import unittest
from urllib.parse import parse_qs, urlsplit

from anime_batch_fallback import batch_candidates, try_batch_candidates
from anime_qb_ownership import OWNED, ownership

HASH_A = "a" * 40
HASH_B = "b" * 40
HASH_C = "c" * 40
IDENTITY = {"title": "Cyberpunk Edgerunners", "tvdb_id": "123",
            "anidb_id": "456"}


def release(infohash, *, seeders=12, title=None):
    return {"title": title or
            "[Group] Cyberpunk Edgerunners S02 1080p (Season S2) (Batch)",
            "magnetUrl": "magnet:?xt=urn:btih:" + infohash,
            "seeders": seeders}


def episode_files(*, episode_start=1):
    return [{"index": i,
             "name": "Season 02/Cyberpunk Edgerunners S02E%02d.mkv" % (i + episode_start),
             "priority": 1, "size": 1000, "progress": 0.0}
            for i in range(12)]


class QB:
    def __init__(self, *, episode_starts=None, metadata_delay=None):
        self.episodes = episode_starts or {HASH_A:13, HASH_B:1, HASH_C:1}
        self.metadata_delay = metadata_delay or {}
        self.records = {}
        self.files = {}
        self.adds = []
        self.stops = []
        self.starts = []
        self.prioritizations = []
        self.reads = {}

    def contains_hash(self, key):
        return key in self.records

    def torrent_identity(self, key):
        return self.records.get(key)

    def add_magnet(self, uri, *, category, tag):
        h = parse_qs(urlsplit(uri).query)["xt"][0].split(":")[-1].lower()
        self.adds.append(h)
        self.records[h] = {"hash":h, "category":category, "tags":tag,
                           "state":"metaDL"}
        self.files[h] = episode_files(episode_start=self.episodes[h])
        self.reads[h] = 0

    def torrent_files(self, key):
        self.reads[key] = self.reads.get(key, 0) + 1
        if self.reads[key] <= self.metadata_delay.get(key, 0):
            return []
        return [row.copy() for row in self.files[key]]

    def stop_owned_torrent(self, key):
        self.stops.append(key)
        self.records[key]["state"] = "pausedDL"

    def resume_owned_metadata(self, key):
        if self.records[key]["state"] != "pausedDL":
            raise AssertionError("not stopped")
        self.records[key]["state"] = "metaDL"

    def apply_stopped_file_selection(self, key, *, wanted_indices, skip_indices):
        if self.records[key]["state"] != "pausedDL":
            raise AssertionError("Cannot set priorities while active")
        if sorted(wanted_indices + skip_indices) != list(range(len(self.files[key]))):
            raise ValueError("Incomplete selection")
        self.prioritizations.append(key)
        for row in self.files[key]:
            row["priority"] = 1 if row["index"] in wanted_indices else 0

    def start_selected_torrent(self, key, *, wanted_indices, skip_indices):
        if self.records[key]["state"] != "pausedDL":
            raise AssertionError("Cannot resume non-paused torrent")
        if any(row["priority"] != (1 if row["index"] in wanted_indices else 0)
               for row in self.files[key]):
            raise AssertionError("Priorities did not match")
        self.starts.append(key)
        self.records[key]["state"] = "downloading"


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)

    def run_fallback(self, qb, releases=None, **options):
        return try_batch_candidates(self.db, qb, releases if releases is not None
            else [release(HASH_A, seeders=22), release(HASH_B, seeders=12)],
            identity=IDENTITY, season=2, sleep=lambda _: None, attempts=3, **options)

    def test_first_unmappable_pack_is_skipped_and_second_starts_e01_only(self):
        qb = QB()
        result = self.run_fallback(qb)
        self.assertEqual(result["state"], "PROBE_DOWNLOADING")
        self.assertEqual(result["infohash"], HASH_B)
        self.assertEqual(result["file_index"], 0)
        self.assertEqual(qb.adds, [HASH_A, HASH_B])
        self.assertEqual(qb.stops, [HASH_A, HASH_B])
        self.assertEqual(qb.starts, [HASH_B])
        self.assertEqual(qb.prioritizations, [HASH_B])
        self.assertEqual([f["priority"] for f in qb.files[HASH_B]],
                         [1] + [0] * 11)
        self.assertEqual(qb.records[HASH_A]["state"], "pausedDL")
        self.assertEqual(ownership(self.db, HASH_A), OWNED)
        self.assertEqual(ownership(self.db, HASH_B), OWNED)
        rows = self.db.execute("""SELECT infohash,decision FROM batch_candidate_decisions
            ORDER BY infohash""").fetchall()
        self.assertEqual(rows, [(HASH_A,"UNMAPPABLE"),(HASH_B,"PROBE_STARTED")])

    def test_restart_does_not_add_or_pause_another_torrent(self):
        qb = QB()
        self.run_fallback(qb)
        result = self.run_fallback(qb)
        self.assertEqual(result["state"], "PROBE_ALREADY_SELECTED")
        self.assertEqual(result["infohash"], HASH_B)
        self.assertEqual(qb.adds, [HASH_A, HASH_B])
        self.assertEqual(qb.stops, [HASH_A, HASH_B])
        self.assertEqual(qb.starts, [HASH_B])

    def test_metadata_delay_never_initiates_second_candidate(self):
        qb = QB(metadata_delay={HASH_A:100})
        result = self.run_fallback(qb)
        self.assertEqual(result["state"], "DEFERRED")
        self.assertEqual(qb.adds, [HASH_A])
        self.assertEqual(qb.stops, [HASH_A])
        self.assertEqual(qb.records[HASH_A]["state"], "pausedDL")
        self.assertEqual(qb.starts, [])

    def test_skip_record_prevents_repeat_of_known_unmappable_source(self):
        qb = QB()
        self.run_fallback(qb, releases=[release(HASH_A)])
        self.assertEqual(self.run_fallback(qb,
                         releases=[release(HASH_A)])["state"], "NO_MAPPABLE_BATCH")
        self.assertEqual(qb.adds, [HASH_A])

    def test_no_candidate_if_release_not_exact_title_and_season(self):
        choices = [
            release(HASH_A, title="[Group] Other Show S02 (Batch)"),
            release(HASH_B, title="[Group] Cyberpunk Edgerunners S01 (Batch)"),
            release(HASH_C, title="[Group] Cyberpunk Edgerunners S02E01"),
        ]
        self.assertEqual(batch_candidates(choices,
              verified_title="Cyberpunk Edgerunners",season=2), [])
        qb=QB()
        self.assertEqual(self.run_fallback(qb, releases=choices)["state"],
                         "NO_MAPPABLE_BATCH")
        self.assertEqual(qb.adds, [])

    def test_rank_by_seeders_and_deduplicate_same_hash(self):
        records=[release(HASH_A,seeders=3),
                 release(HASH_B,seeders=14),
                 release(HASH_A,seeders=20),
                 release(HASH_C,seeders=10)]
        listed=batch_candidates(records,verified_title=IDENTITY["title"],season=2)
        self.assertEqual([x["infohash"] for x in listed], [HASH_A,HASH_B,HASH_C])
        self.assertEqual(len(listed),3)

    def test_unverified_identity_does_not_add_torrents(self):
        qb=QB()
        for broken in ({"title":"Cyberpunk Edgerunners","tvdb_id":0,"anidb_id":456},
                       {"title":"Cyberpunk Edgerunners","tvdb_id":123},
                       {"title":"","tvdb_id":123,"anidb_id":456}):
            with self.assertRaises(ValueError):
                try_batch_candidates(self.db,qb,[release(HASH_A)],
                        identity=broken,season=2)
        self.assertEqual(qb.adds, [])

    def test_existing_probe_with_modified_priorities_never_falls_back(self):
        qb=QB()
        self.run_fallback(qb)
        qb.files[HASH_B][1]["priority"]=1
        result=self.run_fallback(qb)
        self.assertEqual(result["state"],"DEFERRED")
        self.assertIn("priorities changed",result["reason"])
        self.assertEqual(qb.adds,[HASH_A,HASH_B])


if __name__=="__main__":
    unittest.main()
