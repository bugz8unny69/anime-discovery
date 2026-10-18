"""Read-only schema report for identifying legacy V10-V12 operational tables.

Produces structural evidence only; never guesses legacy table mappings.
"""
import sqlite3
from pathlib import Path

KEYWORDS=("queue","history","dispatch","rejection","action","torrent","download","claim")

def operational_schema_report(path):
    source=Path(path)
    if not source.is_file() or source.is_symlink():
        raise ValueError("A regular, non-symlink SQLite snapshot is required")
    with sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("SQLite integrity failure")
        report=[]
        for name,kind in db.execute("""SELECT name,type FROM sqlite_master
                WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'
                ORDER BY name"""):
            if kind!="table" or not any(word in name.lower() for word in KEYWORDS):
                continue
            quoted='"'+name.replace('"','""')+'"'
            columns=[{"name":row[1],"type":row[2],"not_null":bool(row[3]),
                      "default":row[4],"primary_key_order":row[5]}
                     for row in db.execute("PRAGMA table_info("+quoted+")")]
            indexes=[]
            for index in db.execute("PRAGMA index_list("+quoted+")"):
                idx='"'+index[1].replace('"','""')+'"'
                indexes.append({"name":index[1],"unique":bool(index[2]),
                                "origin":index[3],
                                "columns":[row[2] for row in db.execute(
                                    "PRAGMA index_info("+idx+")")]})
            foreign_keys=[{"from":row[3],"references_table":row[2],
                           "references_column":row[4],"on_update":row[5],
                           "on_delete":row[6]}
                          for row in db.execute("PRAGMA foreign_key_list("+quoted+")")]
            report.append({"table":name,"rows":db.execute(
                "SELECT count(*) FROM "+quoted).fetchone()[0],
                "columns":columns,"indexes":indexes,"foreign_keys":foreign_keys})
        return {"tables":report,"read_only":True,"mapping_verified":False}
