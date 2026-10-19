"""Launch the homelab dashboard and acquisition daemon together."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run Anime Discovery web and worker")
    parser.add_argument("--db", type=Path, default=Path("/var/lib/anime-discovery/anime-discovery.db"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("ANIME_WEB_TOKEN"))
    parser.add_argument("--qb-url", required=True)
    parser.add_argument("--download-root", type=Path, required=True)
    parser.add_argument("--trial-root", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    if not args.token:
        parser.error("Set ANIME_WEB_TOKEN or pass --token")
    if not os.environ.get("ANIME_QB_USER") or not os.environ.get("ANIME_QB_PASSWORD"):
        parser.error("Set ANIME_QB_USER and ANIME_QB_PASSWORD")
    if not args.db.is_file():
        parser.error("Database missing; initialize with anime-discovery-admin.py new-database")
    base = Path(__file__).resolve().parent
    web = [sys.executable, str(base / "anime-discovery-web.py"),
           "--db", str(args.db), "--host", args.host, "--port", str(args.port),
           "--token", args.token]
    worker = [sys.executable, str(base / "anime-discovery-worker.py"),
              "--db", str(args.db), "--qb-url", args.qb_url,
              "--download-root", str(args.download_root),
              "--trial-root", str(args.trial_root),
              "--concurrency", str(args.concurrency)]
    processes = []
    try:
        for command in (web, worker):
            processes.append(subprocess.Popen(command))
        print(f"Anime Discovery running at http://{args.host}:{args.port}/", flush=True)
        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    raise RuntimeError(f"Anime Discovery component exited with status {code}")
            import time
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
