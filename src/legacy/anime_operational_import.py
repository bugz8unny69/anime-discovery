"""Offline import of explicitly reviewed, schema-identical operational tables.

No source writes, automatic table discovery, or service activation. A target
table must exist and be empty, or contain exactly the source rows already.
"""
import sqlite3
from pathlib import Path
from anime_migration_row_audit import compare_operational_table

def import_operational_tables(db, source_path, tables):
    if db.in_transaction:
        raise ValueError("Autocommit required")
    if not isinstance(tables,(tuple,list)) or not tables or len(set(tables))!=len(tables):
        raise ValueError("Explicit unique table list required")
    source_path=Path(source_path)
    if not source_path.is_file() or source_path.is_symlink():
        raise ValueError("Safe source snapshot required")
    target_path=db.execute("PRAGMA database_list").fetchone()[2]
    if not target_path or Path(target_path).resolve()==source_path.resolve():
        raise ValueError("Distinct on-disk destination required")
    prepared=[]
    with sqlite3.connect(source_path.resolve().as_uri()+"?mode=ro",uri=True) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Source integrity failure")
        for table in tables:
            if not isinstance(table,str) or not table or table.startswith("sqlite_"):
                raise ValueError("Invalid table")
            quoted='"'+table.replace('"','""')+'"'
            columns=src.execute("PRAGMA table_info("+quoted+")").fetchall()
            if not columns or columns!=db.execute("PRAGMA table_info("+quoted+")").fetchall():
                raise ValueError("Schema mismatch: "+table)
            records=src.execute("SELECT * FROM "+quoted).fetchall()
            if db.execute("SELECT 1 FROM "+quoted+" LIMIT 1").fetchone():
                if not compare_operational_table(source_path,target_path,table)["equal"]:
                    raise ValueError("Conflicting target rows: "+table)
                records=None
            prepared.append((quoted,len(columns),records))
    db.execute("BEGIN IMMEDIATE")
    try:
        for quoted,width,records in prepared:
            if records is not None:
                db.executemany("INSERT INTO "+quoted+" VALUES ("+
                               ",".join("?" for _ in range(width))+")",records)
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Imported state violates foreign keys")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    for table in tables:
        if not compare_operational_table(source_path,target_path,table)["equal"]:
            raise ValueError("Post-import row reconciliation failed: "+table)
    return {"verified_tables":list(tables),"source_modified":False}
