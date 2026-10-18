"""Read-only row-level comparison for operational migration snapshots.

Compares canonical row multisets only when source and destination table
schemas match exactly. Never treats a matching row count as sufficient.
"""
import collections
import hashlib
import sqlite3
from pathlib import Path

def _open(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing or unsafe database snapshot")
    return sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)

def _table(db,name):
    row=db.execute("SELECT type FROM sqlite_master WHERE name=?",(name,)).fetchone()
    if row is None or row[0]!="table":
        return None
    return db.execute("PRAGMA table_info("+_quote(name)+")").fetchall()

def _quote(name):
    return '"'+name.replace('"','""')+'"'

def compare_operational_table(source_path,target_path,table):
    if not isinstance(table,str) or not table or table.startswith("sqlite_"):
        raise ValueError("Invalid table")
    with _open(source_path) as source, _open(target_path) as target:
        for db in (source,target):
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("SQLite integrity failure")
        src=_table(source,table)
        dst=_table(target,table)
        if src is None or dst is None:
            return {"table":table,"equal":False,"reason":"Table missing",
                    "source_present":src is not None,"target_present":dst is not None}
        source_columns=[(r[1],r[2],r[3],r[4],r[5]) for r in src]
        target_columns=[(r[1],r[2],r[3],r[4],r[5]) for r in dst]
        if source_columns!=target_columns:
            return {"table":table,"equal":False,"reason":"Schema differs"}
        columns=",".join(_quote(r[1]) for r in src)
        sql="SELECT "+columns+" FROM "+_quote(table)
        def rows(db):
            # Counter preserves duplicate multiplicity and BLOB identity.
            return collections.Counter(tuple(row) for row in db.execute(sql))
        source_rows=rows(source)
        target_rows=rows(target)
        return {"table":table,"equal":source_rows==target_rows,
                "source_rows":sum(source_rows.values()),
                "target_rows":sum(target_rows.values()),
                "missing_rows":sum((source_rows-target_rows).values()),
                "extra_rows":sum((target_rows-source_rows).values()),
                "reason":"Exact row multiset match" if source_rows==target_rows else "Rows differ"}
