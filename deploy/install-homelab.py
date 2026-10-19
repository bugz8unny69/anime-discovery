"""Interactive, zero-flag Anime Discovery homelab installer.

Run with sudo from the checked-out repository. All application runtime
preferences are stored in settings.json and secrets.json, never environment
variables or worker command-line switches.
"""
import copy
import getpass
import grp
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "legacy"))
from anime_flat_config import DEFAULT_SETTINGS, validate_config
from anime_fresh_database import initialize

CONFIG_DIR = Path("/etc/anime-discovery")
DATA_DIR = Path("/var/lib/anime-discovery")
SERVICE = Path("/etc/systemd/system/anime-discovery.service")


def ask(label, default=None, *, secret=False):
    prompt = label + (f" [{default}]" if default else "") + ": "
    text = getpass.getpass(prompt) if secret else input(prompt).strip()
    value = text or default
    if not value:
        raise ValueError(label + " is required")
    return value


def write_json(path, data, *, mode, uid, gid):
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, sort_keys=True, indent=2)
        output.write("\n")
    os.chmod(path, mode)
    os.chown(path, uid, gid)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: sudo python3 deploy/install-homelab.py")
    if (CONFIG_DIR / "settings.json").exists() or (CONFIG_DIR / "secrets.json").exists():
        raise SystemExit("Existing configuration detected; edit the existing settings instead of reinstalling")
    if SERVICE.exists():
        raise SystemExit("Existing service detected; use systemctl for updates")
    if not shutil.which("systemctl"):
        raise SystemExit("systemd is required for the automatic service")
    username = pwd.getpwuid(ROOT.stat().st_uid).pw_name
    if username == "root":
        username = ask("Non-root account to run Anime Discovery")
    account = pwd.getpwnam(username)
    print("Installing Anime Discovery for account:", username)
    download = Path(ask("Existing qBittorrent download directory", "/mnt/media/Torrents/anime")).expanduser().resolve()
    trial = Path(ask("Existing Anime Discovery staging directory", "/mnt/media/Anime")).expanduser().resolve()
    if not download.is_dir() or not trial.is_dir() or download == trial:
        raise ValueError("Download and staging directories must exist and be different")
    qb_url = ask("qBittorrent API URL", "https://torrents.int.lhprojects.net")
    qb_user = ask("qBittorrent username")
    qb_password = ask("qBittorrent password",secret=True)
    web_token = ask("Private dashboard/webhook token",secret=True)
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["daemon"]["database_path"] = str(DATA_DIR / "anime-discovery.db")
    settings["storage"].update(download_root=str(download), trial_root=str(trial))
    settings["qbittorrent"].update(base_url=qb_url, username=qb_user, cleanup_source=True)
    secrets = {"qbittorrent_password": qb_password, "web_token": web_token}
    validate_config(settings,secrets)

    CONFIG_DIR.mkdir(mode=0o750,parents=True,exist_ok=True)
    os.chmod(CONFIG_DIR,0o750)
    os.chown(CONFIG_DIR,account.pw_uid,account.pw_gid)
    DATA_DIR.mkdir(mode=0o750,parents=True,exist_ok=True)
    os.chown(DATA_DIR,account.pw_uid,account.pw_gid)
    write_json(CONFIG_DIR/"settings.json",settings,mode=0o640,uid=account.pw_uid,gid=account.pw_gid)
    write_json(CONFIG_DIR/"secrets.json",secrets,mode=0o600,uid=account.pw_uid,gid=account.pw_gid)
    db_path = DATA_DIR/"anime-discovery.db"
    if not db_path.exists():
        initialize(db_path)
        os.chown(db_path,account.pw_uid,account.pw_gid)

    media_group = "SupplementaryGroups=media\\n" if any(g.gr_name=="media" for g in grp.getgrall()) else ""
    service = """[Unit]
Description=Anime Discovery dashboard, Autobrr intake and acquisition workers
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
{media_group}WorkingDirectory={root}
ExecStart={python} {root}/src/legacy/anime-discovery-live.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
""".format(user=username,group=grp.getgrgid(account.pw_gid).gr_name,
           root=ROOT,python=sys.executable,media_group=media_group)
    SERVICE.write_text(service,encoding="utf-8")
    subprocess.run(["systemctl","daemon-reload"],check=True)
    subprocess.run(["systemctl","enable","--now","anime-discovery.service"],check=True)
    print("Anime Discovery service started; open http://SERVER-IP:8765/")
    print("Dashboard username: anime ; password: your private webhook token")
    print("Use: systemctl status anime-discovery.service")


if __name__ == "__main__":
    main()
