"""Run the configured Anime Discovery web and acquisition processes together."""
import subprocess
import sys
import time
from pathlib import Path
from anime_flat_config import load_config


def main():
    config = load_config()
    db_path = Path(config["settings"]["daemon"]["database_path"])
    if not db_path.is_file():
        raise RuntimeError("Database missing: " + str(db_path))
    base = Path(__file__).resolve().parent
    processes = []
    try:
        for script in ("anime-discovery-web.py", "anime-discovery-worker.py"):
            processes.append(subprocess.Popen([sys.executable, str(base / script)]))
        # Monitor reloads config each cycle, including enablement changes.
        # Always launch it so Save & Apply can enable NTFY without a daemon restart.
        processes.append(subprocess.Popen([sys.executable, str(base / "anime_ntfy_monitor.py")]))
        if config["settings"]["sonarr"]["enabled"]:
            processes.append(subprocess.Popen([sys.executable, str(base / "anime_sonarr_import_monitor.py")]))
        if config["settings"]["sonarr"]["enabled"] and config["settings"]["shoko"]["enabled"]:
            processes.append(subprocess.Popen([sys.executable, str(base / "anime_shoko_handoff_monitor.py")]))
        web = config["settings"]["web"]
        print(f"Anime Discovery running at http://{web['host']}:{web['port']}/", flush=True)
        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    raise RuntimeError(f"Anime Discovery component exited with status {code}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
