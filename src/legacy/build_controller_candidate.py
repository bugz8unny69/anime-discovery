"""Generate a fail-closed candidate from an explicit api.py; never edit source in place."""
from pathlib import Path
import argparse, ast

GUARD = '''\n    # Legacy review is discovery-token authenticated. It cannot authorize\n    # trusted trial Keep/Reject; preserve only nonterminal review transitions.\n    if data.status in ("APPROVED", "REJECTED"):\n        raise HTTPException(403, "Trusted trial decisions require separate authorization")\n'''

def build(source: Path, target: Path):
    if source.resolve() == target.resolve():
        raise ValueError('Refusing in-place edit')
    code=source.read_text()
    tree=ast.parse(code)
    fn=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review'),None)
    if not fn:
        raise ValueError('Legacy review endpoint not found')
    if 'Trusted trial decisions require separate authorization' in code:
        raise ValueError('Source already patched')
    marker='    with database(write=True) as db:\n'
    start=code.index('def review(sid: int, data: Review):')
    pos=code.find(marker,start)
    if pos<0 or pos>code.find('def episode_result(',start):
        raise ValueError('Review transaction marker missing')
    code=code[:pos]+GUARD+'\n'+code[pos:]
    ast.parse(code)
    target.write_text(code)
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(build(Path(a.source),Path(a.output)))
