
import sqlite3
import tempfile
from pathlib import Path

import api


def main():
    original_db = api.DB

    with tempfile.TemporaryDirectory() as tmp:
        test_db = Path(tmp) / "controller.db"

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
                cursor = db.execute("""
                    INSERT INTO series
                        (source, external_id, title, status)
                    VALUES
                        ('test', 'TEST-IDENTITY-010',
                         'Attempt Identity Test', 'ACQUIRING')
                """)

                sid = cursor.lastrowid

                for episode in (1, 2):
                    db.execute("""
                        INSERT INTO episodes
                            (series_id, season, episode, status)
                        VALUES (?, 1, ?, 'RESERVED')
                    """, (sid, episode))

                cursor = db.execute("""
                    INSERT INTO download_attempts
                        (series_id, season, episode,
                         torrent_hash, release_title,
                         status, progress)
                    VALUES (?, 1, 2, ?, ?,
                            'COMPLETED', 1.0)
                """, (
                    sid,
                    f"{sid:08x}{2:032x}",
                    "Synthetic Episode 2",
                ))

                wrong_attempt_id = cursor.lastrowid

                # Deliberately associate Episode 1 with
                # Episode 2's completed attempt.
                db.execute("""
                    INSERT INTO staged_episodes
                        (series_id, season, episode,
                         attempt_id, status, staged_path)
                    VALUES (?, 1, 1, ?, 'STAGED', ?)
                """, (
                    sid,
                    wrong_attempt_id,
                    "/tmp/fictional-episode-1.mkv",
                ))

            result = api.import_plan(sid)

            print("Ready:", result["ready_to_import"])
            print("Blocked:", result["blocked"])

            assert result["ready_to_import"] == [], (
                "Unsafe: mismatched attempt was accepted"
            )

            reasons = {
                item["episode"]: item["reason"]
                for item in result["blocked"]
            }

            assert reasons[1] == "STAGED_ATTEMPT_MISMATCH", (
                reasons
            )

            print("PASS: mismatched attempt rejected")

        finally:
            api.DB = original_db


if __name__ == "__main__":
    main()
