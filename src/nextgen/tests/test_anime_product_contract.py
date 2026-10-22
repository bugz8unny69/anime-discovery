"""AnimeProduct v1 contract / identity-completion gate tests; offline-only."""
import copy
import json
import unittest
from dataclasses import fields
from pathlib import Path

from src.nextgen.contracts.anime_product import (
    AnimeProduct, Anime, Episode, TVDBPlacement, FIELD_DOC_KEYS
)

FIXTURES = Path(__file__).parent / "fixtures"


class AnimeProductContractTests(unittest.TestCase):
    def fixture(self, name="anime_product_v1_verified.json"):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_complete_identity_roundtrip_is_stable(self):
        for name in ("anime_product_v1_verified.json",
                     "anime_product_v1_continuous.json"):
            with self.subTest(name=name):
                original = self.fixture(name)
                product = AnimeProduct.from_dict(original)
                self.assertEqual(product.to_dict(), original)
                self.assertEqual(AnimeProduct.from_json(product.to_json()), product)

    def test_every_field_has_documentation(self):
        for cls in (AnimeProduct, Anime, Episode, TVDBPlacement):
            for f in fields(cls):
                with self.subTest(cls=cls.__name__, field=f.name):
                    self.assertEqual(set(f.metadata), FIELD_DOC_KEYS)
                    self.assertTrue(all(isinstance(f.metadata[k], str) and
                                        f.metadata[k] for k in FIELD_DOC_KEYS))

    def test_completion_gate_must_have_all_required_product_identity(self):
        data = self.fixture()
        invalids = [
            lambda x: x["anime"].update(anidb_id=None),
            lambda x: x["anime"].update(tvdb_series_id=0),
            lambda x: x["anime"].update(title="  "),
            lambda x: x["anime"].pop("title"),
            lambda x: x.update(episodes=[]),
            lambda x: x["episodes"][0].update(anidb_episode_id=None),
            lambda x: x["episodes"][0].pop("anidb_episode_id"),
        ]
        for i, mutate in enumerate(invalids):
            with self.subTest(case=i), self.assertRaises(ValueError):
                candidate = copy.deepcopy(data)
                mutate(candidate)
                AnimeProduct.from_dict(candidate)

    def test_optional_data_missing_does_not_break_completed_identity(self):
        data = self.fixture("anime_product_v1_continuous.json")
        for field in ("english_title", "original_title", "type", "year"):
            del data["anime"][field]
        for episode in data["episodes"]:
            episode.pop("tvdb_placement")
            episode.pop("anidb_episode_number")
            episode.pop("title")
            episode.pop("type")
        data.pop("attributes")
        product = AnimeProduct.from_dict(data)
        self.assertEqual(product.episodes[0].tvdb_placement, None)
        self.assertEqual(product.to_dict()["episodes"][0]["tvdb_placement"], None)
        self.assertEqual(product.to_dict()["attributes"], {})
        self.assertEqual(product.episodes[1].anidb_episode_id, 90002)

    def test_no_forced_tvdb_season_and_no_automatic_numbering(self):
        data = self.fixture("anime_product_v1_continuous.json")
        product = AnimeProduct.from_dict(data)
        self.assertIsNone(product.episodes[0].tvdb_placement)
        self.assertEqual(product.episodes[0].anidb_episode_number, 1000)

    def test_same_episode_number_allowed_across_distinct_anidb_anime(self):
        first = self.fixture()
        sequel = copy.deepcopy(first)
        sequel["anime"]["anidb_id"] = 67890
        sequel["episodes"][0]["anidb_episode_id"] = 99999
        sequel["episodes"][0]["anidb_episode_number"] = 1
        first["episodes"][0]["anidb_episode_number"] = 1
        self.assertEqual(AnimeProduct.from_dict(first).anime.tvdb_series_id,
                         AnimeProduct.from_dict(sequel).anime.tvdb_series_id)
        self.assertNotEqual(AnimeProduct.from_dict(first).anime.anidb_id,
                            AnimeProduct.from_dict(sequel).anime.anidb_id)

    def test_duplicate_episode_ids_within_one_product_rejected(self):
        candidate = self.fixture()
        candidate["episodes"].append(copy.deepcopy(candidate["episodes"][0]))
        with self.assertRaises(ValueError):
            AnimeProduct.from_dict(candidate)

    def test_reject_invalid_optional_mapping_but_accept_null(self):
        candidate = self.fixture()
        for placement in ({"season": 1}, {"season": None, "episode": 1},
                          {"season": -1, "episode": 1},
                          {"season": 1, "episode": 0},
                          {"season": 1, "episode": 1, "invented": 9}):
            with self.subTest(placement=placement), self.assertRaises(ValueError):
                candidate["episodes"][0]["tvdb_placement"] = placement
                AnimeProduct.from_dict(candidate)

    def test_reject_schema_drift_and_non_json_attributes(self):
        candidate = self.fixture()
        for update in ({"schema_version": 2}, {"job_id": 5},
                       {"intake": {"notification_id": 99}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                AnimeProduct.from_dict({**candidate, **update})
        with self.assertRaises(ValueError):
            AnimeProduct.from_dict({**candidate, "attributes": {"unsafe": float("nan")}})
        with self.assertRaises(ValueError):
            AnimeProduct.from_dict({**candidate, "attributes": {"bad": object()}})

    def test_received_release_is_not_product_field(self):
        data = self.fixture()
        data["anime"]["release_name"] = "[Group] not the identified title"
        with self.assertRaises(ValueError):
            AnimeProduct.from_dict(data)


if __name__ == "__main__":
    unittest.main()
