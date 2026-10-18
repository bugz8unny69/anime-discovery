"""Read-only static readiness audit of offline anime-discovery prototypes.
No imports of project modules, no DB connections, no network, no side effects.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHECKS = (
    ('approval_gateway.py', 'approve_pinned_revision', 'approval gateway exists'),
    ('transactional_approval.py', 'approve_revision', 'legacy direct approval function exists'),
    ('trusted_evidence.py', 'preflight', 'pinned evidence preflight exists'),
    ('source_provenance.py', 'fetch_sonarr_catalog', 'Sonarr catalog adapter exists'),
    ('qb_inventory_adapter.py', 'fetch_inventory', 'qBittorrent inventory reader exists'),
    ('trial_transition.py', 'commit_decision', 'trial decision writer exists'),
    ('cancellation_claims.py', 'claim', 'durable job claim exists'),
    ('cancellation_orchestration.py', 'simulate_one', 'simulated orchestrator exists'),
)

GATES = (
    ('P0', 'Admin identity/authentication and permission checks at HTTP boundary', 'NOT_IMPLEMENTED'),
    ('P0', 'Authenticated provider-to-series cross-reference, independently fetched and pinned', 'NOT_IMPLEMENTED'),
    ('P0', 'Mandatory trusted evidence verification on every approval entrypoint', 'NOT_ENFORCED_GLOBALLY'),
    ('P0', 'Production schema migration, rollback and backup restore rehearsal', 'NOT_IMPLEMENTED'),
    ('P0', 'Verified qBittorrent cancellation with post-action inventory confirmation', 'NOT_IMPLEMENTED'),
    ('P0', 'Safe atomic-ish attempt ownership and cancellation race protocol', 'NOT_IMPLEMENTED'),
    ('P0', 'User Keep/Reject authentication and real Episode 1 watchability verification', 'NOT_INTEGRATED'),
    ('P1', 'Secrets, service privileges, and network allowlists reviewed', 'NOT_REVIEWED'),
    ('P1', 'Production service integration and failure recovery rehearsal', 'NOT_IMPLEMENTED'),
)

def audit(root=ROOT):
    inventory = []
    for filename, function, description in CHECKS:
        path = root / filename
        if not path.is_file():
            inventory.append({'file':filename,'check':description,'status':'MISSING'})
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=filename)
            present = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function for n in tree.body)
            status = 'FOUND' if present else 'MISSING_FUNCTION'
        except (SyntaxError, UnicodeError, OSError) as exc:
            status = f'UNREADABLE:{type(exc).__name__}'
        inventory.append({'file':filename,'check':description,'status':status})
    return {'scope':'static offline prototype inventory; NOT a security certification',
            'inventory':inventory,
            'release_gates':[{'priority':p,'requirement':r,'status':s} for p,r,s in GATES],
            'production_ready':False,
            'dry_run_only':True}

if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
