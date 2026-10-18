"""Read-only reconciliation of archived legacy operational records."""
from collections import Counter
import sqlite3
from pathlib import Path

PAIRS=(("download_attempts","legacy_download_attempts"),
       ("identity_queue","legacy_identity_queue_v10"))

def reconcile_archive(source_path, target_path, source_table, archive_table):
    if (source_table,archive_table) not in PAIRS:
        raise ValueError("Unreviewed archive mapping")
    source_path,target_path=Path(source_path),Path(target_path)
    if source_path.resolve()==target_path.resolve():
        raise ValueError("Distinct snapshots required")
    if any(not p.is_file() or p.is_symlink() for p in (source_path,target_path)):
        raise ValueError("Safe snapshots required")
    results=[]
    for path,table in ((source_path,source_table),(target_path,archive_table)):
        with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("Integrity failure")
            quoted='"'+table.replace('"','""')+'"'
            schema=db.execute("PRAGMA table_info("+quoted+")").fetchall()
            if not schema:
                return {"equal":False,"reason":"Missing table"}
            columns=tuple(row[1] for row in schema)
            rows=Counter(db.execute("SELECT * FROM "+quoted).fetchall())
            results.append((columns,rows))
    same=results[0]==results[1]
    return {"equal":same,"source_rows":sum(results[0][1].values()),
            "target_rows":sum(results[1][1].values()),
            "reason":"Exact archived rows" if same else "Archived rows differ"}
