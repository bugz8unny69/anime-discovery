"""Fail-closed offline integration of the actual controller and trial router.

Only an explicitly supplied disposable DB is allowed. No external cancellation.
"""
import importlib.util
import os
import secrets
import sqlite3
from pathlib import Path
from fastapi import HTTPException
from trial_integration_sprint import install, make_router, production_verifier_from_api, assert_disposable


def load_candidate(path):
    if Path(path) == Path('/opt/anime-discovery/api.py') or Path(path).name == 'api.py':
        raise ValueError('Refusing to import running controller source')
    source = Path(path).resolve(strict=True)
    if source.name == 'api.py':
        raise ValueError('Refusing to import running controller source')
    spec = importlib.util.spec_from_file_location('offline_controller_candidate', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_offline_app(*, candidate_path, disposable_db, decision_token, discovery_token,
                       staging_root, library_root):
    db_path = assert_disposable(disposable_db)
    if not decision_token or not discovery_token or secrets.compare_digest(decision_token, discovery_token):
        raise ValueError('Distinct credentials required')
    if not Path(staging_root).is_dir() or not Path(library_root).is_dir():
        raise ValueError('Explicit existing offline media roots required')
    controller = load_candidate(candidate_path)
    controller.DB = db_path
    controller.TRIAL_STAGING_ROOT = Path(staging_root).resolve()
    controller.TRIAL_LIBRARY_ROOT = Path(library_root).resolve()
    # No production roots, even if called from a development machine.
    for root in (controller.TRIAL_STAGING_ROOT, controller.TRIAL_LIBRARY_ROOT):
        if root == Path('/mnt/media') or Path('/mnt/media') in root.parents:
            raise ValueError('Production media mount forbidden')
    # Rebind ordinary discovery authentication to explicit, isolated credentials.
    # FastAPI dependency overrides are safer than mutating global environment.
    from fastapi import Header
    def isolated_discovery_auth(authorization: str | None = Header(default=None)):
        if not authorization or not secrets.compare_digest(authorization, 'Bearer ' + discovery_token):
            raise HTTPException(401, 'Unauthorized')
    controller.app.dependency_overrides[controller.authenticate] = isolated_discovery_auth
    with sqlite3.connect(db_path, isolation_level=None) as db:
        db.execute('PRAGMA foreign_keys=ON')
        install(db)
    controller.app.include_router(make_router(db_path=db_path, decision_token=decision_token,
        discovery_token=discovery_token, verify_episode1=production_verifier_from_api(controller)))
    return controller.app
