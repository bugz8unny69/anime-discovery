"""Read-only inventory of legacy database table counts."""
import sqlite3
from pathlib import Path

def inventory(path):
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Database integrity check failed")
        names=[row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts={}
        for name in names:
            quoted='"'+name.replace('"','""')+'"'
            counts[name]=db.execute("SELECT count(*) FROM "+quoted).fetchone()[0]
        return counts
