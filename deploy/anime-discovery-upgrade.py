#!/usr/bin/env python3
"""Self-contained, root-run Git upgrade bootstrapper. No app module imports.

First install (review before running):
    sudo -H python3 deploy/anime-discovery-upgrade.py --install
Subsequent upgrades:
    sudo -H /usr/local/sbin/anime-discovery-upgrade
Only supports existing Git checkouts; archive upgrades retain their own CLI.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

SOURCE = "git@github.com:bugz8unny69/anime-discovery.git"
BRANCH = "develop"
SOURCE_FILE = "deploy/anime-discovery-upgrade.py"
DEST = Path("/usr/local/sbin/anime-discovery-upgrade")
ROOT = Path("/opt/anime-discovery")
STATE = Path("/var/lib/anime-discovery/upgrade-state.json")
CONFIG = Path("/etc/anime-discovery")
SERVICE = "anime-discovery.service"
HASH = re.compile(r"[0-9a-f]{40,64}\Z")


def call(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


def git(root, *args):
    return call("git", "-c", "safe.directory=" + str(root), *args, cwd=root)


def save_state(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".upgrade-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_state(path):
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe upgrade state file")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Invalid upgrade state")
    for key in ("healthy", "pending_from", "pending_to"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not HASH.fullmatch(value)):
            raise ValueError("Invalid stored commit hash")
    return data


def ownership(root, uid, gid):
    """Never follow symlink targets outside the checkout."""
    for directory, directories, files in os.walk(root, followlinks=False):
        os.lchown(directory, uid, gid)
        for name in directories + files:
            os.lchown(os.path.join(directory, name), uid, gid)


def verify_db(config):
    settings = json.loads((config / "settings.json").read_text())
    db_path = Path(settings["daemon"]["database_path"])
    if not db_path.is_absolute() or db_path.is_symlink() or not db_path.is_file():
        raise ValueError("Configured SQLite database not a regular absolute path")
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("SELECT version FROM schema_version").fetchone() != (1,):
            raise ValueError("Unsupported database schema")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
    return db_path


def backup_db(source, version):
    suffix = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = Path(str(source) + ".before-" + suffix + "-" + version[:8] + ".bak")
    if target.exists():
        raise FileExistsError(str(target))
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Database backup integrity failure")
    target.chmod(0o600)
    return target


def ready(service):
    for attempt in range(15):
        try:
            call("systemctl", "is-active", "--quiet", service)
            return
        except subprocess.CalledProcessError:
            if attempt == 14:
                raise RuntimeError("Service health check failed") from None
            time.sleep(1)


def recover(root, state_path, service, uid, gid):
    state = read_state(state_path)
    before, after = state.get("pending_from"), state.get("pending_to")
    if not (before and after):
        return state
    head = git(root, "rev-parse", "HEAD")
    if head not in (before, after):
        raise RuntimeError("Interrupted upgrade has unknown HEAD; inspect manually")
    if git(root, "status", "--porcelain"):
        raise RuntimeError("Interrupted upgrade has dirty files; inspect manually")
    call("systemctl", "stop", service)
    if head == after:
        git(root, "reset", "--hard", before)
    ownership(root, uid, gid)
    call("systemctl", "start", service)
    ready(service)
    save_state(state_path, {"healthy": before})
    return {"healthy": before}


def apply(root, state_path, config, service, requested):
    owner = root.stat()
    state = recover(root, state_path, service, owner.st_uid, owner.st_gid)
    current = git(root, "rev-parse", "HEAD")
    if state.get("healthy") and state["healthy"] != current:
        raise RuntimeError("HEAD differs from recorded healthy commit")
    if git(root, "status", "--porcelain"):
        raise RuntimeError("Checkout has local changes; refusing upgrade")
    if git(root, "rev-parse", "FETCH_HEAD") != requested:
        raise RuntimeError("Fetched Git revision changed")
    if git(root, "merge-base", current, requested) != current:
        raise RuntimeError("Not a fast-forward")
    if current == requested:
        ownership(root, owner.st_uid, owner.st_gid)
        save_state(state_path, {"healthy": current})
        return {"updated": False, "revision": current}
    database = verify_db(config)
    backup = backup_db(database, current)
    save_state(state_path, {"healthy": state.get("healthy", current),
                            "pending_from": current, "pending_to": requested})
    stopped = False
    try:
        call("systemctl", "stop", service)
        stopped = True
        git(root, "merge", "--ff-only", requested)
        ownership(root, owner.st_uid, owner.st_gid)
        verify_db(config)
        call("systemctl", "start", service)
        ready(service)
        save_state(state_path, {"healthy": requested})
        return {"updated": True, "previous": current, "revision": requested,
                "database_backup": str(backup)}
    except BaseException:
        if stopped:
            try:
                if git(root, "rev-parse", "HEAD") == requested and not git(root, "status", "--porcelain"):
                    git(root, "reset", "--hard", current)
                ownership(root, owner.st_uid, owner.st_gid)
                call("systemctl", "start", service)
                ready(service)
                save_state(state_path, {"healthy": current})
            except Exception:
                # Leave pending state for conservative recovery next time.
                pass
        raise


def install(source, target):
    if os.geteuid() != 0:
        raise PermissionError("Root required")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".anime-upgrade-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as out, Path(source).open("rb") as inp:
            shutil.copyfileobj(inp, out)
        os.chmod(name, 0o755)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--config-dir", type=Path, default=CONFIG)
    parser.add_argument("--service", default=SERVICE)
    parser.add_argument("--destination", type=Path, default=DEST)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--apply-fetched", metavar="COMMIT")
    args = parser.parse_args(argv)
    if args.install:
        install(Path(__file__).resolve(), args.destination)
        print("Installed:", args.destination)
        return
    if os.geteuid() != 0:
        raise PermissionError("Upgrade requires root")
    root = args.root.resolve()
    if not (root / ".git").is_dir():
        raise ValueError("Upgrade requires an existing Git checkout")
    if git(root, "branch", "--show-current") != BRANCH:
        raise ValueError("Upgrade requires develop branch")
    if args.apply_fetched:
        if not HASH.fullmatch(args.apply_fetched):
            raise ValueError("Invalid commit hash")
        print(json.dumps(apply(root, args.state, args.config_dir,
                               args.service, args.apply_fetched), sort_keys=True))
        return
    # Recovery is performed by installed code BEFORE evaluating fetched code.
    owner = root.stat()
    recover(root, args.state, args.service, owner.st_uid, owner.st_gid)
    git(root, "fetch", "--no-tags", SOURCE, BRANCH)
    new = git(root, "rev-parse", "FETCH_HEAD")
    current = git(root, "rev-parse", "HEAD")
    if git(root, "merge-base", current, new) != current:
        raise RuntimeError("Remote update cannot fast-forward")
    source = git(root, "show", new + ":" + SOURCE_FILE)
    with tempfile.TemporaryDirectory(prefix="anime-upgrader-") as tmp:
        candidate = Path(tmp) / "upgrader.py"
        candidate.write_text(source + "\n")
        candidate.chmod(0o600)
        call(sys.executable, "-m", "py_compile", str(candidate))
        result = call(sys.executable, str(candidate),
                      "--root", str(root), "--state", str(args.state),
                      "--config-dir", str(args.config_dir),
                      "--service", args.service, "--apply-fetched", new)
        # Only replace stable launcher after candidate completed successfully.
        install(candidate, args.destination)
        print(result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("anime-discovery-upgrade:", error, file=sys.stderr)
        sys.exit(1)
