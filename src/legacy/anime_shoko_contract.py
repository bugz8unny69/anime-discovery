"""Read-only Shoko API contract validation.

A reachable status endpoint is not evidence that an episode-link write API
exists. Require a pinned API specification and explicitly verified contract.
No HTTP mutation is performed.
"""
import hashlib
import json
from pathlib import Path

def validate_episode_link_contract(spec_path, *, expected_sha256, method, path,
                                   request_schema, response_schema):
    path_obj=Path(spec_path)
    if not path_obj.is_file() or path_obj.is_symlink():
        raise ValueError("Missing safe Shoko API specification")
    raw=path_obj.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected_sha256:
        raise ValueError("Shoko API specification hash mismatch")
    spec=json.loads(raw)
    if not isinstance(spec,dict) or not isinstance(spec.get("paths"),dict):
        raise ValueError("Invalid Shoko OpenAPI specification")
    if method.upper() not in ("POST","PUT","PATCH"):
        raise ValueError("Expected explicit mutation method")
    operation=spec["paths"].get(path,{}).get(method.lower())
    if not isinstance(operation,dict):
        raise ValueError("Episode-link endpoint absent from pinned specification")
    if not isinstance(operation.get("requestBody"),dict) or not isinstance(operation.get("responses"),dict):
        raise ValueError("Episode-link request/response contract missing")
    # Requiring explicit reviewed schemas prevents an endpoint name alone
    # from being mistaken for safe file-to-episode linkage semantics.
    if operation["requestBody"]!=request_schema or operation["responses"]!=response_schema:
        raise ValueError("Episode-link contract differs from reviewed schemas")
    return {"validated":True,"spec_sha256":digest,"method":method.upper(),
            "path":path,"writes_enabled":False}
