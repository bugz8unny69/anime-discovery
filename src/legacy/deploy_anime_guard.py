#!/usr/bin/env python3
"""Deploy the guarded controller candidate with backup, health check, rollback.
Does not migrate database, enable torrent writes, or install offline-only trial routes.
Run on the torrents VM from /opt/anime-discovery.
"""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

BASE = Path("/opt/anime-discovery")
LIVE = BASE / "api.py"
CANDIDATE = BASE / "api.guarded.candidate.py"
DB = Path("/var/lib/anime-discovery/controller.db")
SERVICE = "anime-discovery.service"

def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true", help="Explicitly deploy guard candidate")
    args = ap.parse_args()
    if not args.deploy:
        ap.error("Pass --deploy to authorize service replacement")
    if os.geteuid() != 0:
        sys.exit("Run with sudo")
    for path in (LIVE, CANDIDATE, DB):
        if not path.is_file():
            sys.exit("Missing required file: " + str(path))
    if LIVE.resolve() == CANDIDATE.resolve():
        sys.exit("Candidate must differ from live path")
    live_text = LIVE.read_text()
    candidate_text = CANDIDATE.read_text()
    if "def guard_trial_decision" not in candidate_text or "guard_trial_decision(db" not in candidate_text:
        sys.exit("Candidate missing acquisition guard; refusing deployment")
    compile(candidate_text, str(CANDIDATE), "exec")
    run("systemctl", "is-active", "--quiet", SERVICE)
    # Save actual live database through SQLite's online backup API.
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BASE / ("production-backup-" + stamp)
    backup.mkdir(mode=0o700)
    db_copy = backup / "controller.db"
    source = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True, timeout=20)
    dest = sqlite3.connect(str(db_copy))
    try:
        source.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            sys.exit("Backup integrity check failed")
    finally:
        dest.close()
        source.close()
    shutil.copystat(DB, db_copy)
    shutil.copy2(LIVE, backup / "api.py")
    tmp = LIVE.with_name("api.py.deploy-tmp")
    shutil.copy2(CANDIDATE, tmp)
    os.chmod(tmp, LIVE.stat().st_mode)
    os.chown(tmp, LIVE.stat().st_uid, LIVE.stat().st_gid)
    try:
        os.replace(tmp, LIVE)
        run("systemctl", "restart", SERVICE)
        for _ in range(12):
            time.sleep(1)
            check = subprocess.run(
                ["curl", "--fail", "--silent", "--show-error", "--max-time", "2",
                 "http://127.0.0.1:8765/health"],
                capture_output=True, text=True)
            if check.returncode == 0 and '"status":"ok"' in check.stdout.replace(" ", ""):
                print("DEPLOYED: acquisition guard is active")
                print("Backup:", backup)
                print("Note: no new discovery automation or live torrent actions enabled.")
                return
        raise RuntimeError("Health check failed")
    except Exception as e:
        print("Deploy failed, rolling back:", e, file=sys.stderr)
        shutil.copy2(backup / "api.py", tmp)
        os.replace(tmp, LIVE)
        run("systemctl", "restart", SERVICE)
        print("Original api.py restored; DB was not modified by deployment script.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
