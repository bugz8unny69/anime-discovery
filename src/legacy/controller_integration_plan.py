#!/usr/bin/env python3
"""Phase 2X-AJ: deterministic, offline-only controller integration plan.

Consumes the sanitized AST audit, never imports api.py, opens SQLite, or uses network.
"""
import argparse
import json
from pathlib import Path

FORMAT = 'anime-controller-audit-v1'
REQUIRED = {
    ('POST', '/series/{sid}/review'),
    ('GET', '/series/{sid}/verify-staged'),
    ('POST', '/series/{sid}/observe-stability'),
    ('POST', '/series/{sid}/attempts'),
    ('POST', '/attempts/{attempt_id}/update'),
    ('GET', '/series/{sid}/import-plan'),
}
WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


def build_plan(audit):
    if not isinstance(audit, dict) or audit.get('format') != FORMAT:
        raise ValueError('Unsupported or missing audit format')
    routes = audit.get('routes')
    if not isinstance(routes, list) or not routes or audit.get('route_count') != len(routes):
        raise ValueError('Incomplete route inventory')
    seen = set()
    for route in routes:
        if not isinstance(route, dict):
            raise ValueError('Invalid route')
        key = (route.get('method'), route.get('path'))
        if key in seen or not all(isinstance(x, str) and x for x in key):
            raise ValueError('Duplicate or malformed route')
        seen.add(key)
        if route.get('auth_status') not in ('UNVERIFIED', 'VERIFIED', 'UNAUTHENTICATED'):
            raise ValueError('Unknown auth status')
    missing = sorted(REQUIRED - seen)
    if missing:
        raise ValueError('Missing critical integration routes: ' + repr(missing))
    if audit.get('source_parsed') is not True:
        raise ValueError('Source was not parsed')
    findings = []
    for route in sorted(routes, key=lambda r: (r['path'], r['method'])):
        method, path = route['method'], route['path']
        risk = 'WRITE_REQUIRES_AUTH_REVIEW' if method in WRITE_METHODS else 'READ_REQUIRES_ACCESS_REVIEW'
        if path == '/health':
            risk = 'HEALTH_INFORMATION_DISCLOSURE_REVIEW'
        findings.append({
            'method': method, 'path': path, 'handler': route.get('handler'),
            'auth_observed': route['auth_status'], 'review': risk,
            'db_markers': route.get('database_call_markers', []),
            'note': 'AST markers are not proof of effective authorization or transaction safety',
        })
    stages = [
        {'id': 'A', 'name': 'Read-only source review', 'requires': ['Inspect api.py auth dependency and route decorators', 'Inspect db connection lifecycle and transaction scopes', 'Verify existing review endpoint semantics']},
        {'id': 'B', 'name': 'Trusted evidence integration', 'requires': ['Authenticated Sonarr/AniDB cross-reference or manual admin approval', 'Never accept caller-provided trusted flag', 'Version and revoke mapping evidence']},
        {'id': 'C', 'name': 'Decision and media integration', 'requires': ['Bind current attempt ID to real ffprobe and stable-file evidence', 'Authenticate Keep/Reject separately from discovery token', 'Commit decision and outbox atomically']},
        {'id': 'D', 'name': 'External cancellation safety', 'requires': ['Fresh qB inventory and attempt fencing', 'No deleteFiles=true', 'Post-action confirmation and crash reconciliation']},
        {'id': 'E', 'name': 'Deployment rehearsal', 'requires': ['Snapshot/backup with verified restore on disposable clone', 'Migration upgrade and rollback on production copy', 'Negative authorization and fault-injection tests', 'Explicit human go/no-go before any live write']},
    ]
    return {
        'format': 'anime-integration-plan-v1',
        'source_route_count': len(routes),
        'production_ready': False,
        'dry_run_only': True,
        'auto_mapping_approval_enabled': False,
        'live_cancellation_enabled': False,
        'route_reviews': findings,
        'stages': stages,
        'release_blockers': [
            'AST cannot verify authentication, including 17 existing routes',
            'No production-backed trusted mapping evidence',
            'No live authenticated Episode 1 decision integration',
            'No verified external cancellation protocol',
            'No production-copy migration/restore rehearsal',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit', type=Path, help='Sanitized anime-controller-audit.json')
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()
    result = build_plan(json.loads(args.audit.read_text(encoding='utf-8')))
    rendered = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
        print(f'Wrote {args.output} ({result["source_route_count"]} routes; production_ready=false)')
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
