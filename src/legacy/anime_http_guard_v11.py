"""Process-scoped urllib pacing for Anime Discovery identity lookups.

One file lock + persistent next request slot across invocations. Not a global
urllib policy: enable only inside the identity worker. Never log credentials.
"""
import contextlib
import email.utils
import fcntl
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = {'api4.thetvdb.com', 'anidb.net', 'www.anidb.net', 'raw.githubusercontent.com'}

class RateLimited(Exception):
    def __init__(self, wait_seconds):
        super().__init__('Provider rate limited; retry later')
        self.wait_seconds = wait_seconds


def retry_after_seconds(value, now=None):
    if not value:
        return None
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            dt = email.utils.parsedate_to_datetime(value)
            return max(0, int(dt.timestamp() - (time.time() if now is None else now)))
        except (TypeError, ValueError, OverflowError):
            return None


class Guard:
    def __init__(self, state, min_interval=2.0, max_wait=90.0, sleeper=time.sleep, clock=time.time):
        self.state = Path(state)
        self.interval = float(min_interval)
        self.max_wait = float(max_wait)
        self.sleep = sleeper
        self.clock = clock
        if self.interval < 0.5 or self.max_wait < 0:
            raise ValueError('Unsafe request interval or wait')
        self.count = 0

    def _slot(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state, 'a+', encoding='utf-8') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            try:
                record = json.loads(handle.read() or '{}')
            except json.JSONDecodeError:
                raise RuntimeError('Invalid rate-limit state; refusing network access')
            now = self.clock()
            due = max(now, float(record.get('next_at', 0)))
            wait = due - now
            if wait > self.max_wait:
                raise RateLimited(wait)
            # Reserve the slot while locked, so concurrent processes cannot burst.
            handle.seek(0)
            handle.truncate()
            json.dump({'next_at': due + self.interval}, handle)
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle, fcntl.LOCK_UN)
        if wait > 0:
            self.sleep(wait)
        self.count += 1

    def _defer(self, delay):
        with open(self.state, 'a+', encoding='utf-8') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            try:
                record = json.loads(handle.read() or '{}')
            except json.JSONDecodeError:
                raise RuntimeError('Invalid rate-limit state')
            due = max(float(record.get('next_at', 0)), self.clock() + delay)
            handle.seek(0)
            handle.truncate()
            json.dump({'next_at': due}, handle)
            handle.flush()
            os.fsync(handle.fileno())

    def open(self, original, url, *args, **kwargs):
        target = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED:
            raise ValueError('Identity worker refused unapproved outbound destination')
        self._slot()
        try:
            return original(url, *args, **kwargs)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                delay = retry_after_seconds(exc.headers.get('Retry-After'))
                if delay is None:
                    delay = 60 + random.uniform(0, 10)
                self._defer(max(self.interval, delay))
                raise RateLimited(max(self.interval, delay)) from None
            raise


@contextlib.contextmanager
def protected(state, interval=2.0):
    guard = Guard(state, min_interval=interval)
    original = urllib.request.urlopen
    urllib.request.urlopen = lambda url, *args, **kwargs: guard.open(original, url, *args, **kwargs)
    try:
        yield guard
    finally:
        urllib.request.urlopen = original
