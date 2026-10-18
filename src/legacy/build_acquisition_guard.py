"""Generate an OFFLINE candidate with transactional acquisition stop guards."""
from pathlib import Path
import ast

TARGETS = {'reserve':'sid','episode_result':'sid','search_complete':'sid','retry_episode':'sid','register_attempt':'sid','update_attempt':None}

def build(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.name == 'api.py' or source.name == 'api.py':
        raise ValueError('Only offline candidate-to-candidate generation allowed')
    code = source.read_text()
    if 'def guard_trial_decision(' in code:
        raise ValueError('Already patched')
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)
    inserts = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in TARGETS:
            continue
        transactions = [n for n in ast.walk(node) if isinstance(n, ast.With) and any(isinstance(i.context_expr, ast.Call) and isinstance(i.context_expr.func, ast.Name) and i.context_expr.func.id == 'database' and any(k.arg == 'write' and isinstance(k.value,ast.Constant) and k.value.value is True for k in i.context_expr.keywords) for i in n.items)]
        if len(transactions) != 1:
            raise ValueError('Expected exactly one write transaction in '+node.name)
        txn = transactions[0]
        variable = txn.items[0].optional_vars
        if not isinstance(variable, ast.Name): raise ValueError('Missing DB binding')
        if node.name == 'update_attempt':
            # Need series id from the attempt before any write; under the same lock.
            guard = f"guard_trial_decision({variable.id}, (lambda r: r[0] if r else None)({variable.id}.execute('SELECT series_id FROM download_attempts WHERE id=?', (attempt_id,)).fetchone()))"
        else:
            guard = f'guard_trial_decision({variable.id}, sid)'
        indent = ' ' * (txn.col_offset + 4)
        inserts[txn.lineno] = indent + guard + '\n'
    if len(inserts) != len(TARGETS): raise ValueError('Missing acquisition route')
    for line, insertion in sorted(inserts.items(), reverse=True):
        lines.insert(line, insertion)
    helper = '''\n\ndef guard_trial_decision(db, sid):\n    """Fail closed if a Keep/Reject decision exists; execute under BEGIN IMMEDIATE."""\n    if sid is None:\n        raise HTTPException(404, "Attempt not found")\n    present = db.execute(\n        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trial_decision_gate'"\n    ).fetchone()\n    if present and db.execute(\n        "SELECT 1 FROM trial_decision_gate WHERE series_id=?", (sid,)\n    ).fetchone():\n        raise HTTPException(409, "Trial decision already recorded; acquisition stopped")\n\n'''
    # helper before the first route, not inside any function
    text = ''.join(lines)
    marker = '@app.get("/health")'
    if text.count(marker) != 1: raise ValueError('Unexpected health route')
    text = text.replace(marker, helper + marker)
    ast.parse(text)
    destination.write_text(text)
    return destination

if __name__ == '__main__':
    build(Path(__file__).with_name('api.candidate.py'), Path(__file__).with_name('api.guarded.candidate.py'))
