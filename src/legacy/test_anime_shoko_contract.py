import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from anime_shoko_contract import validate_episode_link_contract

class ShokoContractTests(unittest.TestCase):
    def test_pinned_contract_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"api.json"
            request={"required":True}
            responses={"200":{"description":"ok"}}
            path.write_text(json.dumps({"paths":{"/api/example/link":{"post":{
                "requestBody":request,"responses":responses}}}}))
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            result=validate_episode_link_contract(path,expected_sha256=digest,
                method="POST",path="/api/example/link",
                request_schema=request,response_schema=responses)
            self.assertTrue(result["validated"])
            self.assertFalse(result["writes_enabled"])
            with self.assertRaisesRegex(ValueError,"hash"):
                validate_episode_link_contract(path,expected_sha256="0"*64,
                    method="POST",path="/api/example/link",
                    request_schema=request,response_schema=responses)

if __name__=="__main__":
    unittest.main()
