"""Offline-only CLI for collecting structural V10-V12 migration evidence.

Reports schema and row counts, never row values. No database writes.
"""
import argparse
import json
from pathlib import Path
from anime_legacy_schema_report import operational_schema_report

def main(argv=None):
    parser=argparse.ArgumentParser(description="Inspect offline legacy SQLite snapshots")
    parser.add_argument("--snapshot",type=Path,action="append",required=True)
    args=parser.parse_args(argv)
    if len(set(p.resolve() for p in args.snapshot))!=len(args.snapshot):
        parser.error("Duplicate snapshot path")
    reports={}
    for path in args.snapshot:
        reports[str(path)]=operational_schema_report(path)
    print(json.dumps(reports,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
