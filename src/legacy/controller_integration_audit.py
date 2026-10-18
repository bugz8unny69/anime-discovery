#!/usr/bin/env python3
"""Read-only AST inventory of the anime discovery controller. No source execution."""
import argparse
import ast
import json
from pathlib import Path

METHODS = {'get','post','put','patch','delete'}
SENSITIVE = ('secret','password','token','api_key','apikey','cookie','authorization','credential')
DB_TERMS = ('sqlite3','connect','execute','commit','rollback','begin','transaction')


def _name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return None


def _literal_path(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else '<dynamic>'


def audit_source(source):
    tree = ast.parse(source)
    functions = {}
    routes = []
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split('.')[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [_name(x.func) for x in ast.walk(node) if isinstance(x, ast.Call)]
        call_names = sorted({c for c in calls if c})
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call): continue
            method = _name(decorator.func)
            if not method or method.split('.')[-1].lower() not in METHODS: continue
            method = method.split('.')[-1].upper()
            path = _literal_path(decorator.args[0]) if decorator.args else '<dynamic>'
            dependency_markers = []
            for expr in (node.args.defaults + node.args.kw_defaults + decorator.keywords):
                if expr is None: continue
                for x in ast.walk(expr):
                    if isinstance(x, ast.Call) and _name(x.func) in ('Depends','Security','fastapi.Depends','fastapi.Security'):
                        dependency_markers.append('dependency-call')
            routes.append({'method':method,'path':path,'handler':node.name,'line':node.lineno,
                           'dependency_markers':sorted(set(dependency_markers)),
                           'auth_status':'UNVERIFIED',
                           'database_call_markers':sorted(c for c in call_names if any(t in c.lower() for t in DB_TERMS)),
                           'integration_status':'NOT_VERIFIED'})
    routes.sort(key=lambda r:(r['path'],r['method']))
    auth_names = sorted(name for name in functions if any(t in name.lower() for t in ('auth','admin','verify','permission')))
    return {'format':'anime-controller-audit-v1','source_parsed':True,'route_count':len(routes),
            'routes':routes,'authentication_functions':auth_names,
            'sqlite_import_detected':'sqlite3' in imports,
            'required_integration_checks':[
                {'id':'route_authentication','status':'NEEDS_MANUAL_CODE_REVIEW'},
                {'id':'admin_separation','status':'NEEDS_MANUAL_CODE_REVIEW'},
                {'id':'db_transaction_boundaries','status':'NEEDS_MANUAL_CODE_REVIEW'},
                {'id':'trusted_provider_attestation','status':'NOT_IMPLEMENTED_IN_PROTOTYPE'},
                {'id':'verified_episode1','status':'NOT_CONNECTED_TO_LIVE_API'},
                {'id':'safe_qb_cancellation','status':'NOT_CONNECTED_TO_LIVE_API'},
                {'id':'migration_backup_rollback','status':'NOT_REHEARSED_ON_PRODUCTION_COPY'}],
            'production_ready':False,'dry_run_only':True,
            'limitations':'AST inventory only; no authentication or security properties proven.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api',default='/opt/anime-discovery/api.py')
    parser.add_argument('--output',default='anime-controller-audit.json')
    args=parser.parse_args()
    source=Path(args.api).read_text(encoding='utf-8')
    result=audit_source(source)
    destination=Path(args.output)
    if destination.resolve() == Path(args.api).resolve():
        parser.error('output cannot overwrite the inspected source')
    destination.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'Wrote {destination} ({result["route_count"]} routes; production_ready=false)')

if __name__=='__main__': main()
