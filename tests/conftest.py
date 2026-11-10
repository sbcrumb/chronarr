"""
Test fixtures. No real Postgres required: ChronarrDatabase's psycopg2-style
methods (%s placeholders, dict-like RealDictCursor rows) are run against an
in-memory sqlite3 connection instead, via a thin adapter that only
translates paramstyle. This works because the database methods exercised
here (the migrate_* functions) use no Postgres-specific SQL — no
ON CONFLICT, JSONB operators, or RETURNING — so nothing else needs
adapting.
"""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# utils/logging.py creates its log directory at import time, hardcoded to
# /app/data/logs when LOG_DIR isn't set — fine inside the production
# container, not writable (or even present) anywhere else. Redirect it
# before anything that pulls that module in gets imported, so tests can run
# outside the container at all.
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="chronarr-test-logs-"))

from core.database import ChronarrDatabase

_SCHEMA = """
CREATE TABLE movies (
    imdb_id TEXT NOT NULL,
    instance TEXT NOT NULL DEFAULT 'radarr',
    title TEXT,
    year INTEGER,
    path TEXT NOT NULL DEFAULT 'unknown',
    released TEXT,
    dateadded TEXT,
    source TEXT,
    last_updated TEXT NOT NULL,
    has_video_file INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    skip_reason TEXT,
    missing_from_source_since TEXT DEFAULT NULL,
    PRIMARY KEY (imdb_id, instance)
);

CREATE TABLE series (
    imdb_id TEXT NOT NULL,
    instance TEXT NOT NULL DEFAULT 'sonarr',
    path TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    metadata TEXT,
    missing_from_source_since TEXT DEFAULT NULL,
    PRIMARY KEY (imdb_id, instance)
);

CREATE TABLE episodes (
    imdb_id TEXT NOT NULL,
    instance TEXT NOT NULL DEFAULT 'sonarr',
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    aired TEXT,
    dateadded TEXT,
    source TEXT,
    last_updated TEXT NOT NULL,
    has_video_file INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    skip_reason TEXT,
    PRIMARY KEY (imdb_id, season, episode, instance)
);
"""


class _SqliteCursorAdapter:
    def __init__(self, real_cursor):
        self._cursor = real_cursor

    def execute(self, sql, params=()):
        return self._cursor.execute(sql.replace("%s", "?"), params)

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._cursor.fetchall()]


class _SqliteConnAdapter:
    def __init__(self, real_conn):
        self._conn = real_conn

    def cursor(self):
        return _SqliteCursorAdapter(self._conn.cursor())


@pytest.fixture
def db():
    """A ChronarrDatabase instance whose connection is an in-memory sqlite3
    database instead of Postgres. __init__ is deliberately bypassed (it runs
    Postgres-only DDL via _init_database) — this fixture creates the three
    tables these tests actually touch itself, then monkeypatches
    get_connection() so the real, unmodified migrate_* methods run against
    it."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)

    instance = ChronarrDatabase.__new__(ChronarrDatabase)

    @contextmanager
    def _get_connection():
        yield _SqliteConnAdapter(conn)

    instance.get_connection = _get_connection
    yield instance
    conn.close()
