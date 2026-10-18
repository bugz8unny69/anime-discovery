
import sqlite3

SCHEMA = """
CREATE TABLE series (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE canonical_mapping_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    series_id INTEGER NOT NULL UNIQUE
        REFERENCES series(id) ON DELETE RESTRICT,

    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'APPROVED', 'REVOKED')),

    revision INTEGER NOT NULL DEFAULT 1
        CHECK(revision >= 1),

    approved_by TEXT,
    approved_at TEXT,
    revoked_at TEXT,

    CHECK (
        (status = 'APPROVED'
         AND approved_by IS NOT NULL
         AND approved_at IS NOT NULL
         AND revoked_at IS NULL)
        OR
        (status = 'REVOKED'
         AND revoked_at IS NOT NULL)
        OR
        (status = 'PENDING'
         AND approved_at IS NULL
         AND revoked_at IS NULL)
    )
);

CREATE TABLE canonical_mapping_entries (
    approval_id INTEGER NOT NULL
        REFERENCES canonical_mapping_approvals(id)
        ON DELETE RESTRICT,

    release_episode INTEGER NOT NULL
        CHECK(release_episode >= 1),

    canonical_season INTEGER NOT NULL
        CHECK(canonical_season = 1),

    canonical_episode INTEGER NOT NULL
        CHECK(canonical_episode BETWEEN 1 AND 6),

    PRIMARY KEY(approval_id, release_episode),

    UNIQUE(approval_id, canonical_season, canonical_episode)
);

CREATE TABLE canonical_mapping_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    approval_id INTEGER NOT NULL
        REFERENCES canonical_mapping_approvals(id)
        ON DELETE RESTRICT,

    action TEXT NOT NULL
        CHECK(action IN ('CREATE', 'APPROVE', 'REVOKE', 'REPLACE')),

    actor TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),

    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER protect_mapping_entries_update
BEFORE UPDATE ON canonical_mapping_entries
WHEN (
    SELECT status
    FROM canonical_mapping_approvals
    WHERE id = OLD.approval_id
) != 'PENDING'
BEGIN
    SELECT RAISE(ABORT, 'Approved mapping entries are immutable');
END;

CREATE TRIGGER protect_mapping_entries_delete
BEFORE DELETE ON canonical_mapping_entries
WHEN (
    SELECT status
    FROM canonical_mapping_approvals
    WHERE id = OLD.approval_id
) != 'PENDING'
BEGIN
    SELECT RAISE(ABORT, 'Approved mapping entries are immutable');
END;

CREATE TRIGGER protect_mapping_entries_insert
BEFORE INSERT ON canonical_mapping_entries
WHEN (
    SELECT status
    FROM canonical_mapping_approvals
    WHERE id = NEW.approval_id
) != 'PENDING'
BEGIN
    SELECT RAISE(ABORT, 'Approved mapping entries are immutable');
END;
"""


def expect_integrity_error(name, action):
    try:
        action()
    except sqlite3.IntegrityError:
        print(f"PASS {name}")
    else:
        raise AssertionError(f"Expected constraint failure: {name}")


db = sqlite3.connect(":memory:")
db.execute("PRAGMA foreign_keys = ON")
db.executescript(SCHEMA)

db.execute(
    "INSERT INTO series(id, source, external_id, title) "
    "VALUES (7, 'test', 'TEST-007', 'Example Anime')"
)

db.execute(
    """
    INSERT INTO canonical_mapping_approvals
        (series_id, status, revision)
    VALUES (7, 'PENDING', 1)
    """
)

approval_id = db.execute(
    "SELECT id FROM canonical_mapping_approvals "
    "WHERE series_id = 7"
).fetchone()[0]

db.execute(
    """
    INSERT INTO canonical_mapping_entries
        (approval_id, release_episode,
         canonical_season, canonical_episode)
    VALUES (?, 1, 1, 1)
    """,
    (approval_id,),
)

db.execute(
    """
    INSERT INTO canonical_mapping_entries
        (approval_id, release_episode,
         canonical_season, canonical_episode)
    VALUES (?, 2, 1, 2)
    """,
    (approval_id,),
)

db.execute(
    """
    UPDATE canonical_mapping_approvals
    SET status = 'APPROVED',
        approved_by = 'local-admin',
        approved_at = CURRENT_TIMESTAMP
    WHERE id = ?
      AND status = 'PENDING'
    """,
    (approval_id,),
)

print("PASS Valid approved mapping")

expect_integrity_error(
    "Duplicate series approval",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_approvals
            (series_id, status)
        VALUES (7, 'PENDING')
        """
    ),
)

expect_integrity_error(
    "Unknown series",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_approvals
            (series_id, status)
        VALUES (999, 'PENDING')
        """
    ),
)

expect_integrity_error(
    "Duplicate canonical destination",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_entries
            (approval_id, release_episode,
             canonical_season, canonical_episode)
        VALUES (?, 3, 1, 2)
        """,
        (approval_id,),
    ),
)

expect_integrity_error(
    "Canonical episode outside trial",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_entries
            (approval_id, release_episode,
             canonical_season, canonical_episode)
        VALUES (?, 3, 1, 7)
        """,
        (approval_id,),
    ),
)

expect_integrity_error(
    "Wrong canonical season",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_entries
            (approval_id, release_episode,
             canonical_season, canonical_episode)
        VALUES (?, 3, 2, 3)
        """,
        (approval_id,),
    ),
)

expect_integrity_error(
    "Approval without approver",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_approvals
            (series_id, status, approved_at)
        VALUES (7, 'APPROVED', CURRENT_TIMESTAMP)
        """
    ),
)

# An approved mapping must not be editable in place.
# This is expected to FAIL until immutability is enforced.
expect_integrity_error(
    "Approved mapping cannot be modified",
    lambda: db.execute(
        """
        UPDATE canonical_mapping_entries
        SET canonical_episode = 3
        WHERE approval_id = ?
          AND release_episode = 2
        """,
        (approval_id,),
    ),
)

# Approved mappings must not accept additional entries.
expect_integrity_error(
    "Approved mapping cannot accept new entries",
    lambda: db.execute(
        """
        INSERT INTO canonical_mapping_entries
            (approval_id, release_episode,
             canonical_season, canonical_episode)
        VALUES (?, 3, 1, 3)
        """,
        (approval_id,),
    ),
)

# Approved mappings must not lose existing entries.
expect_integrity_error(
    "Approved mapping entries cannot be deleted",
    lambda: db.execute(
        """
        DELETE FROM canonical_mapping_entries
        WHERE approval_id = ?
          AND release_episode = 1
        """,
        (approval_id,),
    ),
)

# Verify the original approved mapping remains unchanged.
entries = db.execute(
    """
    SELECT release_episode, canonical_season, canonical_episode
    FROM canonical_mapping_entries
    WHERE approval_id = ?
    ORDER BY release_episode
    """,
    (approval_id,),
).fetchall()

assert entries == [
    (1, 1, 1),
    (2, 1, 2),
], entries

print("PASS Approved mapping remains unchanged")

db.close()
print("\nAll temporary approval schema tests passed.")
