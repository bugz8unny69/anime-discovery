import unittest
from dataclasses import replace
from cancellation_preflight import Attempt, CancellationIntent, Torrent, PreflightError, plan

H = 'a' * 40
G = 'b' * 40

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.intent = CancellationIntent(10, 7, H, 3, 22)
        self.attempt = Attempt(10, 7, H, 'DOWNLOADING', 3)
        self.inventory = [Torrent(H, 'downloading'), Torrent(G, 'paused')]

    def check(self, **kwargs):
        args = dict(intent=self.intent, attempt=self.attempt, inventory=self.inventory,
                    decision_active=True, fresh_inventory=True, current_generation=3)
        args.update(kwargs)
        return plan(**args)

    def test_matching(self):
        p = self.check()
        self.assertEqual(p.result, 'WOULD_REMOVE_TORRENT_ONLY')
        self.assertFalse(p.delete_files)
        self.assertFalse(p.executable)

    def test_absent(self):
        self.assertEqual(self.check(inventory=[]).result, 'ALREADY_ABSENT')

    def test_completed(self):
        self.assertEqual(self.check(attempt=replace(self.attempt, status='COMPLETED')).result, 'WOULD_REMOVE_TORRENT_ONLY')

    def test_other_hash_not_targeted(self):
        self.assertEqual(self.check(inventory=[Torrent(G, 'downloading')]).result, 'ALREADY_ABSENT')

    def test_identity_mismatches(self):
        for changes in ({'attempt_id':11}, {'series_id':8}, {'torrent_hash':G}, {'generation':4}):
            with self.subTest(changes=changes), self.assertRaises(PreflightError):
                self.check(attempt=replace(self.attempt, **changes))

    def test_stale_generation(self):
        with self.assertRaises(PreflightError): self.check(current_generation=4)

    def test_revoked_decision(self):
        with self.assertRaises(PreflightError): self.check(decision_active=False)

    def test_stale_inventory(self):
        with self.assertRaises(PreflightError): self.check(fresh_inventory=False)

    def test_duplicate_inventory(self):
        with self.assertRaises(PreflightError): self.check(inventory=[Torrent(H, 'downloading'), Torrent(H.upper(), 'paused')])

    def test_invalid_hashes(self):
        for bad in ('abc', '', 'x'*40, 'a'*39, 'a'*65):
            with self.subTest(bad=bad), self.assertRaises(PreflightError):
                self.check(intent=replace(self.intent, torrent_hash=bad))

    def test_invalid_attempt_status(self):
        with self.assertRaises(PreflightError): self.check(attempt=replace(self.attempt, status='REPLACED'))

    def test_invalid_inventory(self):
        for bad in (None, {}, [object()], [Torrent('x', 'paused')], [Torrent(H, '')]):
            with self.subTest(bad=bad), self.assertRaises(PreflightError): self.check(inventory=bad)

    def test_invalid_identifiers(self):
        for bad in (0, -1, True, '1'):
            with self.subTest(bad=bad), self.assertRaises(PreflightError):
                self.check(intent=replace(self.intent, decision_id=bad))

    def test_case_insensitive_hash(self):
        self.assertEqual(self.check(inventory=[Torrent(H.upper(), 'paused')]).result, 'WOULD_REMOVE_TORRENT_ONLY')

    def test_no_side_effects(self):
        before = list(self.inventory)
        self.check()
        self.assertEqual(before, self.inventory)

if __name__ == '__main__':
    unittest.main(verbosity=2)
