
import os
import sqlite3
import tempfile
from pathlib import Path

import api


def main():
    original_db = api.DB

    with tempfile.TemporaryDirectory() as tmp:
        test_db = Path(tmp) / "controller.db"

        # Copy the real database into an isolated test database.
        source = sqlite3.connect(original_db)
        target = sqlite3.connect(test_db)

        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        api.DB = str(test_db)

        try:
            with api.database(write=True) as db:
                # Use a unique test series.
                db.execute("""
                    INSERT INTO series
                        (source, external_id, title, status)
                    VALUES
                        ('test', 'TEST-CONTINUITY-009',
                         'Import Continuity Test', 'ACQUIRING')
                """)

                sid = db.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]

                for episode in (1, 2):
                    db.execute("""
                        INSERT INTO episodes
                            (series_id, season, episode, status)
                        VALUES (?, 1, ?, 'RESERVED')
                    """, (sid, episode))

                    torrent_hash = f"{sid:08x}{episode:032x}"

                    cursor = db.execute("""
                        INSERT INTO download_attempts
                            (series_id, season, episode,
                             torrent_hash, release_title,
                             status, progress)
                        VALUES (?, 1, ?, ?, ?,
                                'COMPLETED', 1.0)
                    """, (
                        sid,
                        episode,
                        torrent_hash,
                        f"Synthetic Episode {episode}",
                    ))

                    attempt_id = cursor.lastrowid

                    db.execute("""
                        INSERT INTO staged_episodes
                            (series_id, season, episode,
                             attempt_id, status,
                             staged_path, imported_path,
                             imported_at)
                        VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                    """, (
                        sid,
                        episode,
                        attempt_id,
                        "IMPORTED" if episode == 1 else "STAGED",
                        f"/tmp/synthetic-episode-{episode}.mkv",
                        (
                            "/mnt/media/Anime-Trial/"
                            "missing-episode-1.mkv"
                            if episode == 1 else None
                        ),
                        (
                            "2026-10-15 00:00:00"
                            if episode == 1 else None
                        ),
                    ))

            result = api.import_plan(sid)

            print("Series:", sid)
            print("Ready:", result["ready_to_import"])
            print("Blocked:", result["blocked"])

            assert result["ready_to_import"] == [], (
                "Unsafe: planner authorized a later episode"
            )

            reasons = {
                item["episode"]: item["reason"]
                for item in result["blocked"]
            }

            assert reasons[1] == (
                "IMPORTED_FILE_VERIFICATION_FAILED"
            ), reasons

            assert reasons[2] == (
                "PREVIOUS_EPISODE_MISSING"
            ), reasons

            print("PASS: missing Episode 1 blocks Episode 2")

        finally:
            api.DB = original_db


if __name__ == "__main__":
    main()
