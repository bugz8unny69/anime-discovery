"""Offline deployment safety preflight. Never opens or writes the live database.

Usage: python deployment_safety_pass2.py --api api.py --fixture disposable.db --output report.json
Fixture is opened read-only, backed up into memory, and migrations run only there.
"""
import argparse
import ast
import json
import os
import sqlite3
from pathlib import Path
from trial_integration_sprint import install, PRODUCTION_DB

REQUIRED = {'series','episodes','download_attempts','staged_episodes','file_observations'}

def audit_source(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    routes = []
    for node in tree.body:
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec,ast.Call) or not isinstance(dec.func,ast.Attribute):
                continue
            if not isinstance(dec.func.value,ast.Name) or dec.func.value.id!='app' or dec.func.attr not in ('get','post','put','patch','delete'):
                continue
            if not dec.args or not isinstance(dec.args[0],ast.Constant) or not isinstance(dec.args[0].value,str):
                continue
            deps = next((kw.value for kw in dec.keywords if kw.arg=='dependencies'),None)
            protected = bool(deps and any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='Depends' and x.args and isinstance(x.args[0],ast.Name) and x.args[0].id=='authenticate' for x in (deps.elts if isinstance(deps,(ast.List,ast.Tuple)) else [])))
            routes.append({'method':dec.func.attr.upper(),'path':dec.args[0].value,'discovery_auth_declared':protected})
    return {'route_count':len(routes),'unprotected_non_health':[r['path'] for r in routes if r['path']!='/health' and not r['discovery_auth_declared']], 'legacy_review_uses_discovery_token':any(r['path']=='/series/{sid}/review' and r['discovery_auth_declared'] for r in routes), 'routes':routes}

def check_fixture(path):
    p=Path(path).resolve()
    prod=Path(PRODUCTION_DB).resolve()
    if p==prod or not p.is_file() or p.suffix!='.db' or (prod.exists() and os.path.samefile(p,prod)):
        raise ValueError('Only an existing disposable .db fixture is accepted')
    # Open source read-only and use SQLite's backup API into memory.
    src=sqlite3.connect(f'file:{p}?mode=ro',uri=True)
    clone=sqlite3.connect(':memory:',isolation_level=None)
    try:
        src.backup(clone)
        clone.execute('PRAGMA foreign_keys=ON')
        before=clone.execute('PRAGMA quick_check').fetchone()[0]
        tables={r[0] for r in clone.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED.issubset(tables):
            raise ValueError('Fixture lacks controller schema')
        counts={t:clone.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in REQUIRED}
        install(clone)
        install(clone)
        after=clone.execute('PRAGMA quick_check').fetchone()[0]
        fk=clone.execute('PRAGMA foreign_key_check').fetchall()
        counts_after={t:clone.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in REQUIRED}
        new_tables={r[0] for r in clone.execute("SELECT name FROM sqlite_master WHERE type='table'")}-tables
        return {'quick_check_before':before,'quick_check_after':after,'foreign_key_violations':len(fk),'existing_rows_preserved':counts==counts_after,'added_tables':sorted(new_tables),'migration_repeated':True,'source_opened_read_only':True}
    finally:
        clone.close();src.close()

def build_report(api,fixture):
    source=audit_source(api)
    rehearsal=check_fixture(fixture)
    checks={'source_auth_declared':source['route_count']==17 and not source['unprotected_non_health'], 'schema_integrity':rehearsal['quick_check_before']=='ok' and rehearsal['quick_check_after']=='ok' and rehearsal['foreign_key_violations']==0 and rehearsal['existing_rows_preserved']}
    return {'format':'anime-deployment-safety-v1','source':source,'disposable_migration':rehearsal,'offline_checks_passed':all(checks.values()),'checks':checks,'production_ready':False,'live_writes_enabled':False,'live_cancellation_enabled':False,'auto_mapping_approval_enabled':False,'remaining_blockers':['Authenticated independent canonical mapping provenance','Fresh race-resistant Episode 1 media verification wired into real controller','Live qB inventory and fenced cancellation worker with confirmation','Backup and restore tested using real production snapshot','Separate production decision credential and legacy review authorization hardening','Operator-approved staged deployment']}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--api',required=True)
    ap.add_argument('--fixture',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    report=build_report(args.api,args.fixture)
    dest=Path(args.output)
    dest.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Offline checks:', 'PASS' if report['offline_checks_passed'] else 'FAIL', '| production_ready=false | report:',dest)
    return 0 if report['offline_checks_passed'] else 2
if __name__=='__main__':
    raise SystemExit(main())
