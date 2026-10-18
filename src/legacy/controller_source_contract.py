"""Offline AST contract checks for the uploaded anime controller. Never imports api.py."""
import ast
import json
from pathlib import Path

REQUIRED = {'discover','reserve','review','episode_result','list_episodes','search_complete','retry_episode','register_attempt','list_attempts','update_attempt','stall_candidates','reconcile_series','import_plan','verify_staged','observe_stability','list_series'}

def inspect(source):
    tree = ast.parse(source)
    funcs = {n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    routes = []
    for name,node in funcs.items():
        for d in node.decorator_list:
            if not isinstance(d,ast.Call) or not isinstance(d.func,ast.Attribute) or d.func.attr not in ('get','post','put','patch','delete'):
                continue
            path = d.args[0].value if d.args and isinstance(d.args[0],ast.Constant) else None
            dependencies = next((k.value for k in d.keywords if k.arg=='dependencies'),None)
            auth = isinstance(dependencies,(ast.List,ast.Tuple)) and any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='Depends' and x.args and isinstance(x.args[0],ast.Name) and x.args[0].id=='authenticate' for x in dependencies.elts)
            routes.append({'method':d.func.attr.upper(),'path':path,'handler':name,'discovery_token_dependency':auth})
    byname={r['handler']:r for r in routes}
    def source_of(name):
        n=funcs.get(name)
        return ast.get_source_segment(source,n) if n else ''
    readiness=source_of('evaluate_review_readiness')
    review=source_of('review')
    verify=source_of('verify_staged')
    return {
      'format':'anime-controller-source-contract-v1',
      'route_count':len(routes),
      'routes':routes,
      'all_non_health_routes_declare_discovery_token':all(r['discovery_token_dependency'] for r in routes if r['handler']!='health'),
      'health_public':not byname.get('health',{}).get('discovery_token_dependency',True),
      'review_uses_discovery_token':byname.get('review',{}).get('discovery_token_dependency',False),
      'review_allows_approved_transition':"APPROVED" in review,
      'readiness_waits_for_reserved_zero':'reserved == 0' in readiness,
      'verify_staged_calls_dual_audio_probe':'probe_dual_audio(' in verify,
      'stronger_staged_check_calls_dual_audio_probe':'probe_dual_audio(' in source_of('staged_file_check'),
      'database_has_immediate_transaction':'BEGIN IMMEDIATE' in source_of('database'),
      'database_has_rollback':'ROLLBACK' in source_of('database'),
      'production_ready':False,
      'blockers':['Separate admin/decision authorization from discovery token','Do not treat legacy review as Keep/Reject','Bind Episode 1 to strong media verification and current attempt','Allow early decision independently of reserved later episodes','Integrate real trusted metadata evidence','Design and verify external cancellation protocol','Rehearse migration and rollback on a disposable production copy']
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--api',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    report=inspect(Path(a.api).read_text())
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print('Wrote',a.output,'routes:',report['route_count'],'production_ready=false')

if __name__=='__main__':main()
