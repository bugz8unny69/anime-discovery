"""Offline controller candidate with descriptor-backed Episode 1 decision verification.

Never mounts on the running controller. Does not execute cancellations or approve metadata.
"""
import sqlite3
from pathlib import Path
from fastapi import HTTPException, Header
from controller_integrated_offline import load_candidate
from trial_integration_sprint import assert_disposable, install, make_router
from live_boundary_patch import verified_episode1_snapshot, verify_unchanged
import secrets


def create_app(*, candidate_path, disposable_db, decision_token, discovery_token,
               staging_root, library_root):
    path = assert_disposable(disposable_db)
    if not decision_token or not discovery_token or secrets.compare_digest(decision_token, discovery_token):
        raise ValueError('Distinct nonempty credentials required')
    roots = [Path(staging_root).resolve(strict=True), Path(library_root).resolve(strict=True)]
    if any(not r.is_dir() or r == Path('/mnt/media') or Path('/mnt/media') in r.parents for r in roots):
        raise ValueError('Only disposable media roots allowed')
    controller = load_candidate(candidate_path)
    controller.DB = path
    controller.TRIAL_STAGING_ROOT, controller.TRIAL_LIBRARY_ROOT = roots

    def discovery_auth(authorization: str | None = Header(default=None)):
        if not authorization or not secrets.compare_digest(authorization, 'Bearer ' + discovery_token):
            raise HTTPException(401, 'Unauthorized')
    controller.app.dependency_overrides[controller.authenticate] = discovery_auth

    with sqlite3.connect(path, isolation_level=None) as db:
        db.execute('PRAGMA foreign_keys=ON')
        install(db)

    def verify(db, sid, attempt_id):
        evidence = verified_episode1_snapshot(controller, db, sid, attempt_id)
        if evidence is None:
            return False
        try:
            # Must still name the same object immediately before the decision
            # transaction writes its outbox; no persistent evidence trust flag.
            root = (controller.TRIAL_STAGING_ROOT if
                    Path(evidence['path']).is_relative_to(controller.TRIAL_STAGING_ROOT)
                    else controller.TRIAL_LIBRARY_ROOT)
            return verify_unchanged(evidence['path'], root, evidence)
        finally:
            evidence.close()

    controller.app.include_router(make_router(db_path=path, decision_token=decision_token,
                                               discovery_token=discovery_token, verify_episode1=verify))
    return controller.app
