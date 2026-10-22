"""ReleaseRecord v1 contract regression tests: no network, database or files written."""
import json
import unittest
from dataclasses import fields, replace
from pathlib import Path

from src.nextgen.contracts.release_record import (
    ReleaseRecord, Intake, Identity, Acquisition, Staging, Evaluation, Export)

FIXTURES=Path(__file__).parent/"fixtures"

class ReleaseRecordContractTests(unittest.TestCase):
    def fixture(self,name):
        return json.loads((FIXTURES/name).read_text(encoding="utf-8"))

    def test_persistent_v1_fixtures_round_trip(self):
        for filename in ("release_record_v1_intake.json","release_record_v1_verified.json"):
            with self.subTest(filename=filename):
                source=self.fixture(filename)
                record=ReleaseRecord.from_dict(source)
                self.assertEqual(record.to_dict(),source)
                self.assertEqual(ReleaseRecord.from_json(record.to_json()),record)

    def test_all_fields_have_machine_readable_documentation(self):
        required={"meaning","reason","owner","available","trust"}
        for cls in (ReleaseRecord,Intake,Identity,Acquisition,Staging,Evaluation,Export):
            for f in fields(cls):
                with self.subTest(cls=cls.__name__,field=f.name):
                    self.assertEqual(set(f.metadata),required)
                    self.assertTrue(all(isinstance(f.metadata[key],str) and f.metadata[key]
                                        for key in required))

    def test_schema_rejects_incompatible_version_or_unknown_fields(self):
        data=self.fixture("release_record_v1_intake.json")
        with self.assertRaises(ValueError):
            ReleaseRecord.from_dict({**data,"schema_version":2})
        with self.assertRaises(ValueError):
            ReleaseRecord.from_dict({**data,"not_documented":1})
        with self.assertRaises(ValueError):
            ReleaseRecord.from_dict({**data,"trace_id":"AD-999"})
        with self.assertRaises(ValueError):
            ReleaseRecord.from_dict({**data,"intake":{**data["intake"],"secret":"leak"}})

    def test_no_implicit_identity_or_staging(self):
        record=ReleaseRecord.from_dict(self.fixture("release_record_v1_intake.json"))
        with self.assertRaises(ValueError):
            replace(record,acquisition=Acquisition(1,True,True))
        with self.assertRaises(ValueError):
            replace(record,staging=Staging("/trial/file.mkv",True))
        with self.assertRaises(ValueError):
            replace(record,export=Export("DONE"))

    def test_keep_requires_staging_and_explicit_review(self):
        record=ReleaseRecord.from_dict(self.fixture("release_record_v1_verified.json"))
        record=replace(record,acquisition=Acquisition(3,True,True),
                       staging=Staging("/trial/file.mkv",True))
        with self.assertRaises(ValueError):
            replace(record,export=Export("DONE"))
        record=replace(record,evaluation=Evaluation("KEEP"),export=Export("DONE"))
        self.assertEqual(record.evaluation.decision,"KEEP")

    def test_reject_is_not_export(self):
        with self.assertRaises(ValueError):
            Evaluation("AUTO_KEEP")
        record=ReleaseRecord.from_dict(self.fixture("release_record_v1_verified.json"))
        record=replace(record,acquisition=Acquisition(3,True,True),
                       staging=Staging("/trial/file.mkv",True),evaluation=Evaluation("REJECT"))
        with self.assertRaises(ValueError):
            replace(record,export=Export("DONE"))

if __name__=="__main__":
    unittest.main()
