"""
Tests for the resolve_duplicate_instance route handler itself — both of its
branches (drop-the-other-row, and adopt-dates-only), not just the db methods
underneath it.
"""
import asyncio

import pytest
from fastapi import HTTPException

from api.routes import resolve_duplicate_instance
from api.models import DuplicateResolveRequest


def test_resolve_default_drops_other_instance_entirely(db):
    db.upsert_movie_dates("tt7000000", released="2020-01-01", dateadded="2021-01-01T00:00:00",
                          source="radarr", title="X", year=2020, instance="radarr")

    result = asyncio.run(resolve_duplicate_instance(
        DuplicateResolveRequest(media_type="movie", imdb_id="tt7000000",
                                 keep_instance="radarr_strm", other_instance="radarr"),
        {"db": db},
    ))

    assert result == {"moved": True}
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM movies WHERE imdb_id = %s AND instance = %s", ("tt7000000", "radarr_strm"))
        assert cursor.fetchone() is not None
        cursor.execute("SELECT 1 FROM movies WHERE imdb_id = %s AND instance = %s", ("tt7000000", "radarr"))
        assert cursor.fetchone() is None


def test_resolve_adopt_dates_keeps_instance_and_backfills_date(db):
    db.upsert_movie_dates("tt7000001", released="2020-01-01", dateadded="2021-01-01T00:00:00",
                          source="radarr", title="Stale", year=2020, instance="radarr")
    db.upsert_movie_dates("tt7000001", released="2020-01-01", dateadded="2026-11-10T00:00:00",
                          source="radarr", title="Fresh", year=2020, instance="radarr_strm")

    result = asyncio.run(resolve_duplicate_instance(
        DuplicateResolveRequest(media_type="movie", imdb_id="tt7000001",
                                 keep_instance="radarr_strm", other_instance="radarr", adopt_dates=True),
        {"db": db},
    ))

    assert result == {"resolved": True}
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT dateadded, title FROM movies WHERE imdb_id = %s AND instance = %s",
                        ("tt7000001", "radarr_strm"))
        row = cursor.fetchone()
        assert row["dateadded"] == "2021-01-01T00:00:00"
        assert row["title"] == "Fresh"  # kept row's own data otherwise untouched


def test_resolve_rejects_same_instance_on_both_sides(db):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resolve_duplicate_instance(
            DuplicateResolveRequest(media_type="movie", imdb_id="tt1", keep_instance="radarr", other_instance="radarr"),
            {"db": db},
        ))
    assert exc.value.status_code == 400
