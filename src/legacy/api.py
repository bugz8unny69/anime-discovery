
import time
import stat
import json
import subprocess
import os
import sqlite3
import secrets
from contextlib import contextmanager

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field

from anime_config_runtime import data_path
DB = str(data_path('controller.db'))
LIMIT = 6  # Hard safety ceiling, independent of configuration.

def trial_limit():
    """Read configured trial cap per reservation; never exceed hard limit."""
    from anime_config_runtime import get
    return min(LIMIT, get("discovery.max_trial_episodes"))


app = FastAPI(
    title="Anime Discovery Controller",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

class Discovery(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    external_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)

class Reservation(BaseModel):
    season: int = Field(ge=1)
    episode: int = Field(ge=1)

class Review(BaseModel):
    status: str

def authenticate(authorization: str | None = Header(None)):
    # Shared protected config, with legacy environment fallback.
    try:
        from anime_config_runtime import get as config_get
        token = config_get("controller.api_token") or os.environ.get("ANIME_DISCOVERY_TOKEN")
    except (ImportError, KeyError):
        token = os.environ.get("ANIME_DISCOVERY_TOKEN")
    if not token:
        raise HTTPException(503, "API token not configured")

    expected = f"Bearer {token}"
    if not authorization or not secrets.compare_digest(
        authorization, expected
    ):
        raise HTTPException(401, "Unauthorized")

@contextmanager
def database(write=False):
    db = sqlite3.connect(DB, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        if write:
            db.execute("COMMIT")
    except Exception:
        if write and db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()

def series_row(db, sid):
    row = db.execute(
        "SELECT * FROM series WHERE id=?", (sid,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Series not found")
    return row


def evaluate_review_readiness(db, sid):
    series = series_row(db, sid)

    if series["status"] not in ("DISCOVERED", "ACQUIRING"):
        return False

    if not series["initial_search_complete"]:
        return False

    counts = db.execute("""
        SELECT
            SUM(CASE WHEN status='RESERVED' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status='DOWNLOADED' THEN 1 ELSE 0 END)
        FROM episodes
        WHERE series_id=?
    """, (sid,)).fetchone()

    reserved = counts[0] or 0
    downloaded = counts[1] or 0

    if reserved == 0 and downloaded > 0:
        db.execute("""
            UPDATE series
            SET status='PENDING_REVIEW'
            WHERE id=?
        """, (sid,))
        return True

    return False

@app.get("/health")
def health():
    with database() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok", "dry_run": True}

@app.get("/series", dependencies=[Depends(authenticate)])
def list_series():
    with database() as db:
        rows = db.execute("""
            SELECT s.id, s.source, s.external_id,
                   s.title, s.status,
                   COUNT(e.episode) AS slots_used
            FROM series s
            LEFT JOIN episodes e
              ON e.series_id = s.id
            GROUP BY s.id
            ORDER BY s.id
        """).fetchall()
        return [dict(row) for row in rows]

@app.post("/discover", dependencies=[Depends(authenticate)])
def discover(data: Discovery):
    with database(write=True) as db:
        db.execute("""
            INSERT OR IGNORE INTO series
            (source, external_id, title)
            VALUES (?, ?, ?)
        """, (data.source, data.external_id, data.title))
        row = db.execute("""
            SELECT id, title, status FROM series
            WHERE source=? AND external_id=?
        """, (data.source, data.external_id)).fetchone()
        return dict(row)

@app.post(
    "/series/{sid}/reserve",
    dependencies=[Depends(authenticate)]
)
def reserve(sid: int, data: Reservation):
    with database(write=True) as db:
        row = series_row(db, sid)

        if row["status"] not in (
            "DISCOVERED",
            "ACQUIRING",
            "PENDING_REVIEW",
        ):
            raise HTTPException(
                409, f"Acquisition blocked: {row['status']}"
            )

        existing = db.execute("""
            SELECT status FROM episodes
            WHERE series_id=? AND season=? AND episode=?
        """, (sid, data.season, data.episode)).fetchone()

        if existing:
            raise HTTPException(409, "Episode already tracked")

        # Every tracked episode occupies its position, including FAILED.
        count = db.execute("""
            SELECT COUNT(*) FROM episodes
            WHERE series_id=?
        """, (sid,)).fetchone()[0]

        if count >= trial_limit():
            raise HTTPException(409, "Six-episode limit reached")

        # Only allow the next consecutive episode.
        expected_episode = db.execute("""
            SELECT COALESCE(MAX(episode), 0) + 1
            FROM episodes
            WHERE series_id=? AND season=1
        """, (sid,)).fetchone()[0]

        if data.season != 1 or data.episode != expected_episode:
            raise HTTPException(
                409,
                f"Expected Season 1 Episode {expected_episode}; "
                "cannot skip episodes"
            )

        if count >= trial_limit():
            raise HTTPException(409, "Six-episode limit reached")

        db.execute("""
            INSERT INTO episodes
            (series_id, season, episode)
            VALUES (?, ?, ?)
        """, (sid, data.season, data.episode))

        if row["status"] == "DISCOVERED":
            db.execute("""
                UPDATE series SET status='ACQUIRING'
                WHERE id=?
            """, (sid,))

        return {
            "result": "reserved",
            "dry_run": True,
            "slots_used": count + 1,
            "limit": trial_limit()
        }

@app.post(
    "/series/{sid}/review",
    dependencies=[Depends(authenticate)]
)
def review(sid: int, data: Review):
    allowed = {
        "DISCOVERED": {"PENDING_REVIEW", "NEEDS_REVIEW"},
        "ACQUIRING": {"PENDING_REVIEW", "NEEDS_REVIEW"},
        "PENDING_REVIEW": {"APPROVED", "REJECTED"},
        "NEEDS_REVIEW": {"PENDING_REVIEW"},
    }

    with database(write=True) as db:
        row = series_row(db, sid)
        current = row["status"]

        if data.status not in allowed.get(current, set()):
            raise HTTPException(
                409,
                f"Invalid transition: {current} -> {data.status}"
            )

        db.execute(
            "UPDATE series SET status=? WHERE id=?",
            (data.status, sid)
        )

        return {
            "series_id": sid,
            "previous": current,
            "status": data.status,
            "dry_run": True
        }


class EpisodeResult(BaseModel):
    season: int = Field(ge=1)
    episode: int = Field(ge=1)
    status: str

@app.post(
    "/series/{sid}/episode-result",
    dependencies=[Depends(authenticate)]
)
def episode_result(sid: int, data: EpisodeResult):
    if data.status not in ("DOWNLOADED", "FAILED"):
        raise HTTPException(
            422, "Status must be DOWNLOADED or FAILED"
        )

    with database(write=True) as db:
        series = series_row(db, sid)

        if series["status"] not in (
            "ACQUIRING", "PENDING_REVIEW"
        ):
            raise HTTPException(
                409, "Series is not accepting download results"
            )

        episode = db.execute("""
            SELECT status FROM episodes
            WHERE series_id=? AND season=? AND episode=?
        """, (sid, data.season, data.episode)).fetchone()

        if episode is None:
            raise HTTPException(404, "Episode not reserved")

        current = episode["status"]

        # A repeated completion event is harmless.
        if current == data.status:
            return {
                "result": "unchanged",
                "status": current
            }

        if current != "RESERVED":
            raise HTTPException(
                409,
                f"Invalid episode transition: "
                f"{current} -> {data.status}"
            )

        db.execute("""
            UPDATE episodes SET status=?
            WHERE series_id=? AND season=? AND episode=?
        """, (
            data.status, sid,
            data.season, data.episode
        ))
        # Check whether all selected downloads have finished.
        entered_review = evaluate_review_readiness(db, sid)

        return {
            "result": "updated",
            "series_id": sid,
            "season": data.season,
            "episode": data.episode,
            "status": data.status,
            "dry_run": True,
            "entered_review": entered_review
        }

@app.get(
    "/series/{sid}/episodes",
    dependencies=[Depends(authenticate)]
)
def list_episodes(sid: int):
    with database() as db:
        series_row(db, sid)

        rows = db.execute("""
            SELECT season, episode, status
            FROM episodes
            WHERE series_id=?
            ORDER BY season, episode
        """, (sid,)).fetchall()

        return [dict(row) for row in rows]


@app.post(
    "/series/{sid}/search-complete",
    dependencies=[Depends(authenticate)]
)
def search_complete(sid: int):
    with database(write=True) as db:
        series = series_row(db, sid)

        if series["status"] not in ("DISCOVERED", "ACQUIRING"):
            raise HTTPException(
                409, f"Cannot finish search: {series['status']}"
            )

        db.execute("""
            UPDATE series
            SET initial_search_complete=1
            WHERE id=?
        """, (sid,))

        ready = evaluate_review_readiness(db, sid)

        return {
            "series_id": sid,
            "initial_search_complete": True,
            "entered_review": ready
        }


@app.post(
    "/series/{sid}/episodes/{season}/{episode}/retry",
    dependencies=[Depends(authenticate)]
)
def retry_episode(sid: int, season: int, episode: int):
    if season < 1 or episode < 1:
        raise HTTPException(422, "Invalid episode number")

    with database(write=True) as db:
        series = series_row(db, sid)

        if series["status"] not in (
            "ACQUIRING",
            "PENDING_REVIEW",
        ):
            raise HTTPException(
                409,
                f"Retry blocked: {series['status']}"
            )

        row = db.execute("""
            SELECT status FROM episodes
            WHERE series_id=? AND season=? AND episode=?
        """, (sid, season, episode)).fetchone()

        if row is None:
            raise HTTPException(404, "Episode not tracked")

        if row["status"] != "FAILED":
            raise HTTPException(
                409,
                f"Only FAILED episodes can be retried; "
                f"current status: {row['status']}"
            )

        used = db.execute("""
            SELECT COUNT(*) FROM episodes
            WHERE series_id=?
        """, (sid,)).fetchone()[0]

        db.execute("""
            UPDATE episodes
            SET status='RESERVED'
            WHERE series_id=? AND season=? AND episode=?
        """, (sid, season, episode))

        return {
            "result": "retry_reserved",
            "series_id": sid,
            "season": season,
            "episode": episode,
            "slots_used": used,
            "limit": trial_limit(),
            "dry_run": True
        }


class AttemptRegistration(BaseModel):
    season: int = Field(ge=1)
    episode: int = Field(ge=1)
    torrent_hash: str = Field(
        min_length=40, max_length=40,
        pattern=r"^[a-fA-F0-9]{40}$"
    )
    release_title: str = Field(min_length=1, max_length=500)


class AttemptUpdate(BaseModel):
    status: str
    progress: float = Field(ge=0, le=1)


ATTEMPT_STATUSES = {
    "QUEUED", "DOWNLOADING", "STALLED",
    "COMPLETED", "FAILED", "CANCELLED"
}

ATTEMPT_TRANSITIONS = {
    "QUEUED": {"DOWNLOADING", "STALLED", "FAILED", "CANCELLED"},
    "DOWNLOADING": {"STALLED", "COMPLETED", "FAILED", "CANCELLED"},
    "STALLED": {"DOWNLOADING", "COMPLETED", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}


@app.post(
    "/series/{sid}/attempts",
    dependencies=[Depends(authenticate)]
)
def register_attempt(sid: int, data: AttemptRegistration):
    torrent_hash = data.torrent_hash.lower()

    with database(write=True) as db:
        series = series_row(db, sid)

        if series["status"] not in (
            "ACQUIRING", "PENDING_REVIEW"
        ):
            raise HTTPException(
                409, f"Attempts blocked: {series['status']}"
            )

        episode = db.execute("""
            SELECT status FROM episodes
            WHERE series_id=? AND season=? AND episode=?
        """, (sid, data.season, data.episode)).fetchone()

        if episode is None:
            raise HTTPException(404, "Episode not reserved")

        if episode["status"] != "RESERVED":
            raise HTTPException(
                409,
                f"Episode status is {episode['status']}; "
                "expected RESERVED"
            )

        existing = db.execute("""
            SELECT id, series_id, season, episode
            FROM download_attempts
            WHERE torrent_hash=?
        """, (torrent_hash,)).fetchone()

        if existing:
            if (
                existing["series_id"] == sid
                and existing["season"] == data.season
                and existing["episode"] == data.episode
            ):
                return {
                    "result": "already_registered",
                    "attempt_id": existing["id"]
                }

            raise HTTPException(
                409, "Torrent hash belongs to another episode"
            )

        result = db.execute("""
            INSERT INTO download_attempts
            (series_id, season, episode,
             torrent_hash, release_title)
            VALUES (?, ?, ?, ?, ?)
        """, (
            sid, data.season, data.episode,
            torrent_hash, data.release_title
        ))

        return {
            "result": "registered",
            "attempt_id": result.lastrowid,
            "series_id": sid,
            "season": data.season,
            "episode": data.episode,
            "status": "QUEUED",
            "dry_run": True
        }


@app.get(
    "/series/{sid}/attempts",
    dependencies=[Depends(authenticate)]
)
def list_attempts(sid: int):
    with database() as db:
        series_row(db, sid)

        rows = db.execute("""
            SELECT id, season, episode, torrent_hash,
                   release_title, status, progress,
                   last_progress_at, created_at, updated_at
            FROM download_attempts
            WHERE series_id=?
            ORDER BY id
        """, (sid,)).fetchall()

        return [dict(row) for row in rows]


@app.post(
    "/attempts/{attempt_id}/update",
    dependencies=[Depends(authenticate)]
)
def update_attempt(attempt_id: int, data: AttemptUpdate):
    if data.status not in ATTEMPT_STATUSES:
        raise HTTPException(422, "Invalid attempt status")

    if data.status == "COMPLETED" and data.progress != 1:
        raise HTTPException(
            422, "COMPLETED requires progress=1"
        )

    with database(write=True) as db:
        attempt = db.execute("""
            SELECT * FROM download_attempts WHERE id=?
        """, (attempt_id,)).fetchone()

        if attempt is None:
            raise HTTPException(404, "Attempt not found")

        series = series_row(db, attempt["series_id"])

        if series["status"] not in (
            "ACQUIRING", "PENDING_REVIEW"
        ):
            raise HTTPException(
                409, f"Updates blocked: {series['status']}"
            )

        episode = db.execute("""
            SELECT status FROM episodes
            WHERE series_id=? AND season=? AND episode=?
        """, (
            attempt["series_id"],
            attempt["season"],
            attempt["episode"]
        )).fetchone()

        if episode is None or episode["status"] != "RESERVED":
            raise HTTPException(
                409, "Episode is no longer awaiting a download"
            )

        old_status = attempt["status"]
        old_progress = attempt["progress"]

        if (
            old_status == data.status
            and old_progress == data.progress
        ):
            return {
                "result": "unchanged",
                "attempt_id": attempt_id,
                "status": old_status,
                "progress": old_progress
            }

        if (
            data.status != old_status
            and data.status not in
                ATTEMPT_TRANSITIONS[old_status]
        ):
            raise HTTPException(
                409,
                f"Invalid attempt transition: "
                f"{old_status} -> {data.status}"
            )

        if old_status in (
            "COMPLETED", "FAILED", "CANCELLED"
        ):
            raise HTTPException(
                409, "Attempt is in a terminal state"
            )

        if data.progress < old_progress:
            raise HTTPException(
                409, "Progress cannot decrease"
            )

        progress_increased = data.progress > old_progress

        db.execute("""
            UPDATE download_attempts
            SET status=?,
                progress=?,
                updated_at=CURRENT_TIMESTAMP,
                last_progress_at=CASE
                    WHEN ? THEN CURRENT_TIMESTAMP
                    ELSE last_progress_at
                END
            WHERE id=?
        """, (
            data.status,
            data.progress,
            int(progress_increased),
            attempt_id
        ))

        return {
            "result": "updated",
            "attempt_id": attempt_id,
            "status": data.status,
            "progress": data.progress,
            "dry_run": True
        }


from datetime import datetime, timezone, timedelta

STALL_HOURS = 12


@app.get(
    "/attempts/stall-candidates",
    dependencies=[Depends(authenticate)]
)
def stall_candidates():
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=STALL_HOURS)
    )

    with database() as db:
        rows = db.execute("""
            SELECT
                a.id,
                a.series_id,
                a.season,
                a.episode,
                a.torrent_hash,
                a.release_title,
                a.status,
                a.progress,
                a.last_progress_at,
                a.created_at
            FROM download_attempts a
            JOIN series s ON s.id = a.series_id
            JOIN episodes e
              ON e.series_id = a.series_id
             AND e.season = a.season
             AND e.episode = a.episode
            WHERE a.status IN ('DOWNLOADING', 'STALLED')
              AND s.status IN ('ACQUIRING', 'PENDING_REVIEW')
              AND e.status = 'RESERVED'
            ORDER BY a.id
        """).fetchall()

        candidates = []

        for row in rows:
            # SQLite CURRENT_TIMESTAMP uses UTC.
            timestamp = (
                row["last_progress_at"]
                or row["created_at"]
            )

            last_activity = datetime.strptime(
                timestamp, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)

            idle_hours = (
                datetime.now(timezone.utc) - last_activity
            ).total_seconds() / 3600

            if last_activity <= cutoff:
                candidates.append({
                    "attempt_id": row["id"],
                    "series_id": row["series_id"],
                    "season": row["season"],
                    "episode": row["episode"],
                    "status": row["status"],
                    "progress": row["progress"],
                    "idle_hours": round(idle_hours, 2),
                    "replacement_candidate": True
                })

        return {
            "threshold_hours": STALL_HOURS,
            "candidate_count": len(candidates),
            "candidates": candidates
        }


@app.get(
    "/series/{sid}/reconciliation",
    dependencies=[Depends(authenticate)]
)
def reconcile_series(sid: int):
    with database() as db:
        series = series_row(db, sid)

        episodes = db.execute("""
            SELECT season, episode, status
            FROM episodes
            WHERE series_id=?
            ORDER BY season, episode
        """, (sid,)).fetchall()

        results = []

        for episode in episodes:
            attempts = db.execute("""
                SELECT id, status, progress
                FROM download_attempts
                WHERE series_id=? AND season=? AND episode=?
                ORDER BY id
            """, (
                sid,
                episode["season"],
                episode["episode"]
            )).fetchall()

            statuses = [a["status"] for a in attempts]
            completed = [
                a["id"] for a in attempts
                if a["status"] == "COMPLETED"
            ]
            active = [
                a["id"] for a in attempts
                if a["status"] in (
                    "QUEUED", "DOWNLOADING", "STALLED"
                )
            ]

            if episode["status"] == "DOWNLOADED":
                action = "EPISODE_ALREADY_DOWNLOADED"
            elif episode["status"] == "FAILED":
                action = "EPISODE_RETRY_REQUIRED"
            elif completed:
                action = "VERIFY_AND_IMPORT"
            elif active:
                action = "WAIT_FOR_DOWNLOAD"
            elif statuses:
                action = "ALL_ATTEMPTS_TERMINAL"
            else:
                action = "NO_ATTEMPTS_REGISTERED"

            results.append({
                "season": episode["season"],
                "episode": episode["episode"],
                "episode_status": episode["status"],
                "attempt_count": len(attempts),
                "completed_attempt_ids": completed,
                "active_attempt_ids": active,
                "recommended_action": action
            })

        return {
            "series_id": sid,
            "series_status": series["status"],
            "dry_run": True,
            "episodes": results
        }

def check_file_stability(db, sid, season, episode, path_string):
    path = Path(path_string)

    observation = db.execute("""
        SELECT staged_path, size_bytes, mtime_ns,
               first_observed_at, last_observed_at
        FROM file_observations
        WHERE series_id=? AND season=? AND episode=?
    """, (sid, season, episode)).fetchone()

    if observation is None:
        return {
            "stable": False,
            "reason": "NO_STABILITY_OBSERVATION"
        }

    try:
        root = TRIAL_STAGING_ROOT.resolve(strict=True)
        resolved = path.resolve(strict=True)

        if not resolved.is_relative_to(root):
            return {
                "stable": False,
                "reason": "OUTSIDE_STAGING_ROOT"
            }

        info = path.lstat()

        if not stat.S_ISREG(info.st_mode):
            return {
                "stable": False,
                "reason": "NOT_REGULAR_FILE"
            }

    except (OSError, RuntimeError):
        return {
            "stable": False,
            "reason": "FILE_NOT_ACCESSIBLE"
        }

    if (
        observation["staged_path"] != str(path)
        or observation["size_bytes"] != info.st_size
        or observation["mtime_ns"] != info.st_mtime_ns
    ):
        return {
            "stable": False,
            "reason": "FILE_CHANGED_SINCE_OBSERVATION"
        }

    now = int(time.time())
    elapsed = now - observation["first_observed_at"]

    if (
        elapsed < STABILITY_SECONDS
        or observation["last_observed_at"]
           - observation["first_observed_at"]
           < STABILITY_SECONDS
    ):
        return {
            "stable": False,
            "reason": "STABILITY_WINDOW_INCOMPLETE",
            "observed_seconds": elapsed
        }

    return {
        "stable": True,
        "observed_seconds": elapsed
    }

@app.get(
    "/series/{sid}/import-plan",
    dependencies=[Depends(authenticate)]
)

def import_plan(sid: int):
    with database() as db:
        series = series_row(db, sid)

        episodes = db.execute("""
            SELECT
                e.season,
                e.episode,
                e.status AS episode_status,
                st.status AS staging_status,
                st.attempt_id,
                st.staged_path,
                st.imported_path,
                a.status AS attempt_status,
                a.series_id AS attempt_series_id,
                a.season AS attempt_season,
                a.episode AS attempt_episode
            FROM episodes e
            LEFT JOIN staged_episodes st
              ON st.series_id = e.series_id
             AND st.season = e.season
             AND st.episode = e.episode
            LEFT JOIN download_attempts a
              ON a.id = st.attempt_id
            WHERE e.series_id=?
            ORDER BY e.season, e.episode
        """, (sid,)).fetchall()

        expected = 1
        gap_found = False

        ready = []
        imported = []
        blocked = []

        for row in episodes:
            season = row["season"]
            episode = row["episode"]
            staging_status = row["staging_status"]

            if season != 1 or episode > 6:
                blocked.append({
                    "season": season,
                    "episode": episode,
                    "reason": "OUTSIDE_TRIAL_LIMIT"
                })
                continue

            if episode != expected:
                gap_found = True

            if gap_found:
                blocked.append({
                    "season": season,
                    "episode": episode,
                    "reason": "PREVIOUS_EPISODE_MISSING"
                })
                continue

            
            if staging_status == "IMPORTED":
                attempt_matches = (
                    row["attempt_id"] is not None
                    and row["attempt_series_id"] == sid
                    and row["attempt_season"] == season
                    and row["attempt_episode"] == episode
                )

                if not attempt_matches:
                    gap_found = True
                    blocked.append({
                        "season": season,
                        "episode": episode,
                        "reason": "IMPORTED_ATTEMPT_MISMATCH",
                    })
                    continue

                verification = imported_file_check(
                    row["imported_path"],
                    row["attempt_status"],
                )

                if not verification["verified"]:
                    gap_found = True
                    blocked.append({
                        "season": season,
                        "episode": episode,
                        "reason": "IMPORTED_FILE_VERIFICATION_FAILED",
                        "details": verification["reasons"],
                    })
                    continue

                imported.append({
                    "season": season,
                    "episode": episode,
                    "path": row["imported_path"],
                })
                expected += 1
                continue
            
            if staging_status != "STAGED":
                gap_found = True
                blocked.append({
                    "season": season,
                    "episode": episode,
                    "reason": "NOT_STAGED",
                })
                continue

            # Confirm this download attempt belongs to
            # the exact series and episode being imported.
            attempt_matches = (
                row["attempt_id"] is not None
                and row["attempt_series_id"] == sid
                and row["attempt_season"] == season
                and row["attempt_episode"] == episode
            )

            if not attempt_matches:
                gap_found = True
                blocked.append({
                    "season": season,
                    "episode": episode,
                    "reason": "STAGED_ATTEMPT_MISMATCH",
                })
                continue

            verification = staged_file_check(
                row["staged_path"],
                row["attempt_status"]
            )

            if not verification["verified"]:
                gap_found = True
                blocked.append({
                    "season": season,
                    "episode": episode,
                    "reason": "FILE_VERIFICATION_FAILED",
                    "details": verification["reasons"]
                })
                continue

            stability = check_file_stability(
                db,
                sid,
                season,
                episode,
                row["staged_path"]
            )

            if not stability["stable"]:
                gap_found = True
                blocked.append({
                    "season": season,
                    "episode": episode,
                    "reason": "FILE_NOT_STABLE",
                    "details": stability["reason"]
                })
                continue
    
            ready.append({
                "season": season,
                "episode": episode,
                "attempt_id": row["attempt_id"],
                "staged_path": row["staged_path"],
                "size_bytes": verification["size_bytes"]
            })

            expected += 1

        return {
            "series_id": sid,
            "series_status": series["status"],
            "dry_run": True,
            "already_imported": imported,
            "ready_to_import": ready,
            "blocked": blocked
        }

from pathlib import Path
import os
import stat

TRIAL_STAGING_ROOT = Path(
    "/mnt/media/Torrents/anime-trial"
)

MIN_MEDIA_BYTES = 50 * 1024 * 1024

ALLOWED_MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".m4v"
}

def probe_media(path: Path):
    try:
        result = subprocess.run(
            [
                "/usr/bin/ffprobe",
                "-v", "error",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-show_entries",
                "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "valid": False,
            "reasons": ["FFPROBE_FAILED"],
        }

    if result.returncode != 0:
        return {
            "valid": False,
            "reasons": ["FFPROBE_FAILED"],
        }

    try:
        metadata = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {
            "valid": False,
            "reasons": ["INVALID_PROBE_OUTPUT"],
        }

    streams = metadata.get("streams", [])

    has_video = any(
        stream.get("codec_type") == "video"
        for stream in streams
    )

    has_audio = any(
        stream.get("codec_type") == "audio"
        for stream in streams
    )

    reasons = []

    if not has_video:
        reasons.append("NO_VIDEO_STREAM")

    if not has_audio:
        reasons.append("NO_AUDIO_STREAM")

    try:
        duration = float(
            metadata.get("format", {}).get("duration", 0)
        )
    except (ValueError, TypeError):
        duration = 0

    if duration <= 0:
        reasons.append("INVALID_DURATION")

    return {
        "valid": len(reasons) == 0,
        "reasons": reasons,
        "duration_seconds": duration,
        "video": has_video,
        "audio": has_audio,
    }


DUAL_AUDIO_LANGUAGES = {
    "japanese": {"ja", "jpn"},
    "english": {"en", "eng"},
}


def probe_dual_audio(path: Path):
    try:
        result = subprocess.run(
            [
                "/usr/bin/ffprobe",
                "-v", "error",
                "-show_entries",
                "stream=index,codec_type:stream_tags=language,title",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "valid": False,
            "reasons": ["FFPROBE_FAILED"],
            "audio_streams": [],
        }

    if result.returncode != 0:
        return {
            "valid": False,
            "reasons": ["FFPROBE_FAILED"],
            "audio_streams": [],
        }

    try:
        metadata = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {
            "valid": False,
            "reasons": ["INVALID_PROBE_OUTPUT"],
            "audio_streams": [],
        }

    audio_streams = []

    for stream in metadata.get("streams", []):
        if stream.get("codec_type") != "audio":
            continue

        tags = stream.get("tags", {})
        language = tags.get("language", "und").lower()

        audio_streams.append({
            "index": stream.get("index"),
            "language": language,
            "title": tags.get("title", ""),
        })

    languages = {
        stream["language"]
        for stream in audio_streams
    }

    has_japanese = bool(
        languages & DUAL_AUDIO_LANGUAGES["japanese"]
    )

    has_english = bool(
        languages & DUAL_AUDIO_LANGUAGES["english"]
    )

    reasons = []

    if not has_japanese:
        reasons.append("JAPANESE_AUDIO_MISSING")

    if not has_english:
        reasons.append("ENGLISH_AUDIO_MISSING")

    return {
        "valid": len(reasons) == 0,
        "reasons": reasons,
        "audio_streams": audio_streams,
        "has_japanese": has_japanese,
        "has_english": has_english,
    }

def staged_file_check(path_string: str, attempt_status: str):
    path = Path(path_string)
    reasons = []
    size_bytes = None

    if attempt_status != "COMPLETED":
        reasons.append("ATTEMPT_NOT_COMPLETED")

    if path.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
        reasons.append("UNSUPPORTED_EXTENSION")

    try:
        root = TRIAL_STAGING_ROOT.resolve(strict=True)
        resolved = path.resolve(strict=True)

        if not resolved.is_relative_to(root):
            reasons.append("OUTSIDE_STAGING_ROOT")

        # Reject a symlink at the final file path.
        file_stat = path.lstat()

        if not stat.S_ISREG(file_stat.st_mode):
            reasons.append("NOT_REGULAR_FILE")
        else:
            size_bytes = file_stat.st_size

            if size_bytes < MIN_MEDIA_BYTES:
                reasons.append("FILE_TOO_SMALL")

            # Actually open the file instead of relying on
            # os.access(), which may behave differently under
            # root or ACL-based permissions.
            try:
                with path.open("rb") as handle:
                    handle.read(4096)
            except OSError:
                reasons.append("NOT_READABLE")

    except OSError:
        reasons.append("FILE_NOT_ACCESSIBLE")
    except RuntimeError:
        reasons.append("PATH_RESOLUTION_FAILED")

    if not reasons:
        media = probe_media(path)

        if not media["valid"]:
            reasons.extend(media["reasons"])
    
    if not reasons:
        dual_audio = probe_dual_audio(path)

        if not dual_audio["valid"]:
            reasons.extend(dual_audio["reasons"])
        
    return {
        "verified": len(reasons) == 0,
        "reasons": reasons,
        "size_bytes": size_bytes
    }


TRIAL_LIBRARY_ROOT = Path("/mnt/media/Anime-Trial")


def imported_file_check(path_string, attempt_status):
    reasons = []
    size_bytes = None

    if attempt_status != "COMPLETED":
        reasons.append("ATTEMPT_NOT_COMPLETED")

    if not path_string:
        return {
            "verified": False,
            "reasons": ["IMPORTED_PATH_MISSING"] + reasons,
            "size_bytes": None,
        }

    path = Path(path_string)

    if path.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
        reasons.append("UNSUPPORTED_EXTENSION")

    try:
        root = TRIAL_LIBRARY_ROOT.resolve(strict=True)
        resolved = path.resolve(strict=True)

        if not resolved.is_relative_to(root):
            reasons.append("OUTSIDE_TRIAL_LIBRARY")

        info = path.lstat()

        if not stat.S_ISREG(info.st_mode):
            reasons.append("NOT_REGULAR_FILE")
        else:
            size_bytes = info.st_size

            if size_bytes < MIN_MEDIA_BYTES:
                reasons.append("FILE_TOO_SMALL")

            try:
                with path.open("rb") as handle:
                    handle.read(4096)
            except OSError:
                reasons.append("NOT_READABLE")

    except (OSError, RuntimeError):
        reasons.append("FILE_NOT_ACCESSIBLE")

    if not reasons:
        media = probe_media(path)

        if not media["valid"]:
            reasons.extend(media["reasons"])

    if not reasons:
        dual_audio = probe_dual_audio(path)

        if not dual_audio["valid"]:
            reasons.extend(dual_audio["reasons"])

    return {
        "verified": len(reasons) == 0,
        "reasons": reasons,
        "size_bytes": size_bytes,
    }

@app.get(
    "/series/{sid}/verify-staged",
    dependencies=[Depends(authenticate)]
)
def verify_staged(sid: int):
    with database() as db:
        series_row(db, sid)

        rows = db.execute("""
            SELECT
                st.series_id,
                st.season,
                st.episode,
                st.attempt_id,
                st.status,
                st.staged_path,
                a.status AS attempt_status
            FROM staged_episodes st
            JOIN download_attempts a
              ON a.id = st.attempt_id
            WHERE st.series_id=?
            ORDER BY st.season, st.episode
        """, (sid,)).fetchall()

        results = []

        for row in rows:
            path = Path(row["staged_path"])
            reasons = []

            if row["status"] != "STAGED":
                reasons.append("NOT_IN_STAGED_STATE")

            if row["attempt_status"] != "COMPLETED":
                reasons.append("ATTEMPT_NOT_COMPLETED")

            if path.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
                reasons.append("UNSUPPORTED_EXTENSION")

            # Reject symlinks, missing paths and nonregular files.
            try:
                file_stat = path.lstat()

                if not stat.S_ISREG(file_stat.st_mode):
                    reasons.append("NOT_REGULAR_FILE")

                if file_stat.st_size < MIN_MEDIA_BYTES:
                    reasons.append("FILE_TOO_SMALL")

                if not os.access(path, os.R_OK):
                    reasons.append("NOT_READABLE")

                size_bytes = file_stat.st_size

            except OSError:
                reasons.append("FILE_NOT_ACCESSIBLE")
                size_bytes = None

            # Resolve the parent path so a symlinked directory
            # cannot redirect us outside the staging root.
            try:
                resolved_path = path.resolve(strict=True)
                resolved_root = TRIAL_STAGING_ROOT.resolve(
                    strict=True
                )

                if not resolved_path.is_relative_to(
                    resolved_root
                ):
                    reasons.append("OUTSIDE_STAGING_ROOT")

            except (OSError, RuntimeError):
                reasons.append("PATH_RESOLUTION_FAILED")

            results.append({
                "season": row["season"],
                "episode": row["episode"],
                "attempt_id": row["attempt_id"],
                "staged_path": str(path),
                "size_bytes": size_bytes,
                "verified": len(reasons) == 0,
                "reasons": reasons
            })

        return {
            "series_id": sid,
            "dry_run": True,
            "verification_count": len(results),
            "results": results
        }


STABILITY_SECONDS = 60


@app.post(
    "/series/{sid}/observe-stability",
    dependencies=[Depends(authenticate)]
)
def observe_stability(sid: int):
    now = int(time.time())

    with database(write=True) as db:
        series_row(db, sid)

        rows = db.execute("""
            SELECT
                st.season,
                st.episode,
                st.staged_path,
                st.status AS staging_status,
                a.status AS attempt_status
            FROM staged_episodes st
            JOIN download_attempts a
              ON a.id = st.attempt_id
             AND a.series_id = st.series_id
             AND a.season = st.season
             AND a.episode = st.episode
            WHERE st.series_id=?
            ORDER BY st.season, st.episode
        """, (sid,)).fetchall()

        results = []

        for row in rows:
            season = row["season"]
            episode = row["episode"]
            path = Path(row["staged_path"])

            if (
                row["staging_status"] != "STAGED"
                or row["attempt_status"] != "COMPLETED"
            ):
                results.append({
                    "episode": episode,
                    "stable": False,
                    "reason": "NOT_ELIGIBLE"
                })
                continue

            try:
                root = TRIAL_STAGING_ROOT.resolve(strict=True)
                resolved = path.resolve(strict=True)

                if not resolved.is_relative_to(root):
                    raise ValueError("OUTSIDE_STAGING_ROOT")

                info = path.lstat()

                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("NOT_REGULAR_FILE")

            except (OSError, RuntimeError, ValueError):
                results.append({
                    "episode": episode,
                    "stable": False,
                    "reason": "FILE_NOT_ACCESSIBLE_OR_UNSAFE"
                })
                continue

            previous = db.execute("""
                SELECT staged_path, size_bytes, mtime_ns,
                       first_observed_at
                FROM file_observations
                WHERE series_id=? AND season=? AND episode=?
            """, (sid, season, episode)).fetchone()

            unchanged = (
                previous is not None
                and previous["staged_path"] == str(path)
                and previous["size_bytes"] == info.st_size
                and previous["mtime_ns"] == info.st_mtime_ns
            )

            first_seen = (
                previous["first_observed_at"]
                if unchanged else now
            )

            db.execute("""
                INSERT INTO file_observations (
                    series_id, season, episode,
                    staged_path, size_bytes, mtime_ns,
                    first_observed_at, last_observed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, season, episode)
                DO UPDATE SET
                    staged_path=excluded.staged_path,
                    size_bytes=excluded.size_bytes,
                    mtime_ns=excluded.mtime_ns,
                    first_observed_at=excluded.first_observed_at,
                    last_observed_at=excluded.last_observed_at
            """, (
                sid, season, episode,
                str(path), info.st_size, info.st_mtime_ns,
                first_seen, now
            ))

            elapsed = now - first_seen

            results.append({
                "season": season,
                "episode": episode,
                "stable": unchanged
                          and elapsed >= STABILITY_SECONDS,
                "observed_seconds": elapsed,
                "required_seconds": STABILITY_SECONDS
            })

        return {
            "series_id": sid,
            "results": results,
            "dry_run": True
        }


@app.get('/identities', dependencies=[Depends(authenticate)])
def list_identity_suggestions():
    """Read-only dashboard-to-controller identity bridge; NEVER grants acquisition."""
    from anime_identity_catalog import read_catalog, audit, CatalogError
    path = str(data_path('identity-mappings.json'))
    try:
        result = audit(read_catalog(path))
    except (CatalogError, OSError) as exc:
        raise HTTPException(503, f'Identity catalog unavailable: {exc}') from exc
    # A conflicting or tampered catalog must fail closed.
    if result['issues']:
        raise HTTPException(409, {'message': 'Identity catalog requires review', 'issues': result['issues']})
    return result

@app.get('/identities/evidence', dependencies=[Depends(authenticate)])
def identity_evidence():
    """Read-only corroboration of stored identities; NEVER approves acquisition."""
    from anime_identity_evidence import evidence
    from anime_config_runtime import get
    path = str(data_path('identity-mappings.json'))
    try:
        key = get('tvdb.api_key') if get('tvdb.enabled') else ''
        return evidence(path, tvdb_key=key or '')
    except (OSError, ValueError) as exc:
        import logging
        logging.getLogger("uvicorn.error").exception(
            "Identity evidence dependency failed"
        )
        raise HTTPException(
            503,
            'Identity evidence unavailable; check AniDB cache and configuration'
        ) from exc


@app.get('/_internal/routes', dependencies=[Depends(authenticate)])
def internal_routes():
    """Authenticated route discovery, without enabling public OpenAPI."""
    return [{'methods': sorted(route.methods), 'path': route.path}
            for route in app.routes if hasattr(route, 'methods')]
