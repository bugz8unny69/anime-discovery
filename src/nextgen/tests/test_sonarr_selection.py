"""Small SQLite tests for Sonarr's immutable discovery selection receipt."""
import sqlite3
import unittest

from src.nextgen.acquisition.sonarr_search import DiscoveryPolicy, Release, SearchResult
from src.nextgen.sonarr_episode import VerifiedEpisode
from src.nextgen.storage.sonarr_selection import SelectionConflict, select

HASH = 'a' * 40
OTHER = 'b' * 40
EP = VerifiedEpisode(100, 200, 1, 10)


def release(digest=HASH, *, approved=False, scope='exact', seeders=10):
    return Release('Example S01E10', 'Nyaa', 'torrent', '1080p', 1080, 0,
                   seeders, 0, 123456789, approved, ('Sonarr rejected',),
                   (22,), scope, digest, 'magnet:?xt=urn:btih:' + digest,
                   scope == 'exact')


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE trial_plans (
              plan_id INTEGER PRIMARY KEY, anidb_id INTEGER,
              tvdb_series_id INTEGER, tvdb_season INTEGER, tvdb_order TEXT,
              anchor_episode INTEGER, backfill_count INTEGER, following_count INTEGER);
            CREATE TABLE recognized_episodes (
              anidb_id INTEGER, tvdb_series_id INTEGER, tvdb_season INTEGER,
              tvdb_episode INTEGER, tvdb_episode_id INTEGER);
            CREATE TABLE episode_reservations (
              state TEXT, tvdb_series_id INTEGER, tvdb_season INTEGER, tvdb_episode INTEGER);
            CREATE TABLE batch_episode_reservations (
              state TEXT, tvdb_series_id INTEGER, tvdb_season INTEGER, tvdb_episode INTEGER);
            CREATE TABLE sonarr_episode_selections (
              plan_id INTEGER, tvdb_episode INTEGER, tvdb_episode_id INTEGER,
              info_hash TEXT, selected_at_ms INTEGER,
              PRIMARY KEY(plan_id,tvdb_episode), UNIQUE(plan_id,info_hash));
            INSERT INTO trial_plans VALUES (1,50,100,1,'official',10,6,1);
            INSERT INTO recognized_episodes VALUES (50,100,1,10,200);
        """)
        self.db.commit()

    def choose(self, selected=None, *, result=None, identity=EP):
        chosen = selected or release()
        results = result or SearchResult(11, 22, (chosen,))
        return select(self.db,plan_id=1,identity=identity,result=results,
                      release=chosen,policy=DiscoveryPolicy())

    def test_unapproved_candidate_allowed_and_idempotent(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.assertTrue(self.choose())
            self.assertFalse(self.choose())
        self.assertEqual(self.db.execute(
            'SELECT tvdb_episode,tvdb_episode_id,info_hash FROM sonarr_episode_selections'
        ).fetchall(), [(10,200,HASH)])

    def test_conflict_does_not_replace_prior_selection(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.choose()
        with self.db, self.assertRaises(SelectionConflict):
            self.db.execute('BEGIN IMMEDIATE')
            self.choose(release(OTHER))
        self.assertEqual(self.db.execute(
            'SELECT info_hash FROM sonarr_episode_selections').fetchone()[0],HASH)

    def test_unrecognized_or_reserved_is_refused(self):
        with self.db, self.assertRaises(SelectionConflict):
            self.db.execute('BEGIN IMMEDIATE')
            self.choose(identity=VerifiedEpisode(100,201,1,10))
        self.db.execute("INSERT INTO episode_reservations VALUES ('ACTIVE',100,1,10)")
        with self.db, self.assertRaises(SelectionConflict):
            self.choose()
        self.db.execute("DELETE FROM episode_reservations")
        self.db.execute("INSERT INTO batch_episode_reservations VALUES ('ACTIVE',100,1,10)")
        with self.db, self.assertRaises(SelectionConflict):
            self.choose()

    def test_unbound_wrong_scope_and_low_seeders_rejected(self):
        for item in (release(scope='pack'), release(seeders=0), release(OTHER)):
            with self.subTest(item=item.scope), self.db, self.assertRaises(SelectionConflict):
                self.db.execute('BEGIN IMMEDIATE')
                self.choose(selected=item, result=SearchResult(11,22,(release(),)))

    def test_requires_transaction(self):
        with self.assertRaises(SelectionConflict):
            self.choose()


if __name__ == '__main__':
    unittest.main()
