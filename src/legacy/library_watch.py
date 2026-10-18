"""Watch new/stable Anime-Trial videos and request Jellyfin scans.

Baseline at startup avoids an unnecessary scan. Failed refreshes are retried.
No torrent access or filesystem mutations.
"""
import os
import threading
import time
from pathlib import Path

VIDEO_EXTENSIONS = {'.mkv', '.mp4'}


def snapshot(root):
    result = {}
    if not root.is_dir() or root.is_symlink():
        return result
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            path = Path(base) / name
            if path.suffix.lower() not in VIDEO_EXTENSIONS or path.is_symlink():
                continue
            try:
                stat = path.stat()
                if path.is_file():
                    result[str(path)] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
    return result


class LibraryWatcher:
    def __init__(self, root, scan_callback, interval=15):
        self.root = Path(root)
        self.scan_callback = scan_callback
        self.interval = interval
        self.status = 'Waiting for new episodes'
        self.last_scan = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name='anime-library-watch', daemon=True)
        self._thread.start()

    def _run(self):
        baseline = snapshot(self.root)
        pending = False
        while not self._stop.wait(self.interval):
            current = snapshot(self.root)
            # A new file or a changed existing video is worth refreshing.
            changed = any(current[k] != baseline.get(k) for k in current)
            if changed:
                pending = True
                self.status = 'New episode detected; waiting for stable file'
            # Require two successive observations of identical file sizes/mtimes.
            if pending and not changed:
                try:
                    self.scan_callback()
                except Exception as exc:
                    self.status = 'Jellyfin scan failed; will retry: ' + str(exc)[:160]
                else:
                    pending = False
                    self.last_scan = time.strftime('%Y-%m-%d %H:%M:%S')
                    self.status = 'Jellyfin scan requested at ' + self.last_scan
            baseline = current

    def stop(self):
        self._stop.set()
