"""
Tests for migrate_movie_instance / migrate_series_instance — moving a
tracked title from one instance to another in place, instead of letting the
destination's next import create a fresh (imdb_id, instance) row and lose
dateadded/metadata/history. See core/database.py for the full docstrings.
"""
from datetime import datetime


# --- movies -------------------------------------------------------------

def test_migrate_movie_instance_moves_row_and_preserves_data(db):
    db.upsert_movie_dates("tt1000000", released="2020-01-01", dateadded="2021-06-01T00:00:00",
                          source="radarr", has_video_file=True, title="Old Movie", year=2020,
                          instance="radarr")

    assert db.migrate_movie_instance("tt1000000", "radarr", "radarr_strm") is True

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", ("tt1000000", "radarr"))
        assert cursor.fetchone() is None  # source gone

        cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", ("tt1000000", "radarr_strm"))
        row = cursor.fetchone()
        assert row is not None
        assert row["title"] == "Old Movie"
        assert row["dateadded"] == "2021-06-01T00:00:00"  # preserved, not reset


def test_migrate_movie_instance_no_source_returns_false(db):
    assert db.migrate_movie_instance("tt9999999", "radarr", "radarr_strm") is False


def test_migrate_movie_instance_destination_collision_keeps_destination(db):
    # The manual "I already moved this by hand before this existed" case:
    # both instances already have a row. The destination's own (presumably
    # more current) data wins; the stale source just gets dropped.
    db.upsert_movie_dates("tt1000001", released="2020-01-01", dateadded="2021-01-01T00:00:00",
                          source="radarr", title="Stale", year=2020, instance="radarr")
    db.upsert_movie_dates("tt1000001", released="2020-01-01", dateadded="2022-03-03T00:00:00",
                          source="radarr", title="Current", year=2020, instance="radarr_strm")

    assert db.migrate_movie_instance("tt1000001", "radarr", "radarr_strm") is True

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", ("tt1000001", "radarr"))
        assert cursor.fetchone() is None

        cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", ("tt1000001", "radarr_strm"))
        row = cursor.fetchone()
        assert row["dateadded"] == "2022-03-03T00:00:00"  # destination's own data untouched


def test_migrate_movie_instance_new_path_override(db):
    db.upsert_movie("tt1000002", path="/mnt/nas/Movie", instance="radarr")

    db.migrate_movie_instance("tt1000002", "radarr", "radarr_strm", new_path="/mnt/strm/Movie")

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT path FROM movies WHERE imdb_id = %s AND instance = %s", ("tt1000002", "radarr_strm"))
        assert cursor.fetchone()["path"] == "/mnt/strm/Movie"


# --- series: whole-title moves -------------------------------------------

def test_migrate_series_instance_whole_series_moves_series_and_episodes(db):
    db.upsert_series("tt2000000", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt2000000", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", has_video_file=True, instance="sonarr")
    db.upsert_episode_date("tt2000000", 1, 2, aired="2020-01-08", dateadded="2021-01-08T00:00:00",
                           source="sonarr", has_video_file=True, instance="sonarr")

    assert db.migrate_series_instance("tt2000000", "sonarr", "sonarr_strm") is True

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM series WHERE imdb_id = %s AND instance = %s", ("tt2000000", "sonarr"))
        assert cursor.fetchone() is None  # source series row gone

        cursor.execute("SELECT * FROM series WHERE imdb_id = %s AND instance = %s", ("tt2000000", "sonarr_strm"))
        assert cursor.fetchone() is not None

        cursor.execute("SELECT * FROM episodes WHERE imdb_id = %s AND instance = %s", ("tt2000000", "sonarr"))
        assert cursor.fetchall() == []

        cursor.execute("""
            SELECT season, episode, dateadded FROM episodes
            WHERE imdb_id = %s AND instance = %s ORDER BY episode
        """, ("tt2000000", "sonarr_strm"))
        rows = cursor.fetchall()
        assert [(r["season"], r["episode"]) for r in rows] == [(1, 1), (1, 2)]
        assert rows[0]["dateadded"] == "2021-01-01T00:00:00"  # preserved


def test_migrate_series_instance_no_source_returns_false(db):
    assert db.migrate_series_instance("tt2999999", "sonarr", "sonarr_strm") is False


def test_migrate_series_instance_whole_series_handles_per_episode_collision(db):
    # Regression test: a blind bulk UPDATE here would violate the
    # (imdb_id, season, episode, instance) primary key the moment it hit an
    # episode the destination already has (e.g. partially moved by hand
    # already). Every episode must go through the same collision check the
    # partial-episode path uses.
    db.upsert_series("tt2000001", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt2000001", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", instance="sonarr")
    db.upsert_episode_date("tt2000001", 1, 2, aired="2020-01-08", dateadded="2021-01-08T00:00:00",
                           source="sonarr", instance="sonarr")

    # Destination already independently has S01E01 (e.g. a stray prior sync).
    db.upsert_series("tt2000001", path="/mnt/strm/Show", instance="sonarr_strm")
    db.upsert_episode_date("tt2000001", 1, 1, aired="2020-01-01", dateadded="2099-12-31T00:00:00",
                           source="sonarr", instance="sonarr_strm")

    assert db.migrate_series_instance("tt2000001", "sonarr", "sonarr_strm") is True  # must not raise

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dateadded FROM episodes
            WHERE imdb_id = %s AND instance = %s AND season = 1 AND episode = 1
        """, ("tt2000001", "sonarr_strm"))
        assert cursor.fetchone()["dateadded"] == "2099-12-31T00:00:00"  # destination's own row untouched

        cursor.execute("""
            SELECT 1 FROM episodes WHERE imdb_id = %s AND instance = %s AND season = 1 AND episode = 2
        """, ("tt2000001", "sonarr_strm"))
        assert cursor.fetchone() is not None  # the non-colliding episode still moved

        cursor.execute("SELECT * FROM episodes WHERE imdb_id = %s AND instance = %s", ("tt2000001", "sonarr"))
        assert cursor.fetchall() == []  # nothing left behind on the source


# --- series: partial (season, episode) moves -----------------------------

def test_migrate_series_instance_partial_episodes_leaves_series_row_on_source(db):
    db.upsert_series("tt2000002", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt2000002", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", instance="sonarr")
    db.upsert_episode_date("tt2000002", 1, 2, aired="2020-01-08", dateadded="2021-01-08T00:00:00",
                           source="sonarr", instance="sonarr")

    assert db.migrate_series_instance("tt2000002", "sonarr", "sonarr_strm", episodes=[(1, 1)]) is True

    with db.get_connection() as conn:
        cursor = conn.cursor()
        # Only the one requested episode moved.
        cursor.execute("SELECT season, episode FROM episodes WHERE imdb_id = %s AND instance = %s",
                       ("tt2000002", "sonarr_strm"))
        assert [(r["season"], r["episode"]) for r in cursor.fetchall()] == [(1, 1)]

        cursor.execute("SELECT season, episode FROM episodes WHERE imdb_id = %s AND instance = %s",
                       ("tt2000002", "sonarr"))
        assert [(r["season"], r["episode"]) for r in cursor.fetchall()] == [(1, 2)]

        # Series still has an episode on the source — its row must survive.
        cursor.execute("SELECT 1 FROM series WHERE imdb_id = %s AND instance = %s", ("tt2000002", "sonarr"))
        assert cursor.fetchone() is not None
        # A destination series row was created so the moved episode has a parent.
        cursor.execute("SELECT 1 FROM series WHERE imdb_id = %s AND instance = %s", ("tt2000002", "sonarr_strm"))
        assert cursor.fetchone() is not None


def test_migrate_series_instance_last_episode_leaving_drops_source_series_row(db):
    db.upsert_series("tt2000003", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt2000003", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", instance="sonarr")

    db.migrate_series_instance("tt2000003", "sonarr", "sonarr_strm", episodes=[(1, 1)])

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM series WHERE imdb_id = %s AND instance = %s", ("tt2000003", "sonarr"))
        assert cursor.fetchone() is None  # nothing left under it — the row is a phantom now


def test_migrate_series_instance_episode_collision_keeps_destinations_row(db):
    db.upsert_series("tt2000004", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt2000004", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", instance="sonarr")
    db.upsert_series("tt2000004", path="/mnt/strm/Show", instance="sonarr_strm")
    db.upsert_episode_date("tt2000004", 1, 1, aired="2020-01-01", dateadded="2099-01-01T00:00:00",
                           source="sonarr", instance="sonarr_strm")

    db.migrate_series_instance("tt2000004", "sonarr", "sonarr_strm", episodes=[(1, 1)])

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dateadded FROM episodes WHERE imdb_id = %s AND instance = %s AND season = 1 AND episode = 1
        """, ("tt2000004", "sonarr_strm"))
        assert cursor.fetchone()["dateadded"] == "2099-01-01T00:00:00"  # untouched, not overwritten

        cursor.execute("SELECT * FROM episodes WHERE imdb_id = %s AND instance = %s", ("tt2000004", "sonarr"))
        assert cursor.fetchall() == []  # the colliding source row was dropped, not left orphaned


def test_migrate_series_instance_reverse_call_moves_episode_back(db):
    # The phase-2 "verification found this one never actually arrived"
    # correction: calling the same primitive with instances swapped.
    db.upsert_series("tt2000005", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt2000005", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", instance="sonarr")

    db.migrate_series_instance("tt2000005", "sonarr", "sonarr_strm", episodes=[(1, 1)])
    db.migrate_series_instance("tt2000005", "sonarr_strm", "sonarr", episodes=[(1, 1)])  # revert

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM episodes WHERE imdb_id = %s AND instance = %s", ("tt2000005", "sonarr"))
        assert cursor.fetchone() is not None
        cursor.execute("SELECT * FROM episodes WHERE imdb_id = %s AND instance = %s", ("tt2000005", "sonarr_strm"))
        assert cursor.fetchall() == []


# --- adopt-dates (keep an instance's location, but take the other's dates) ---

def test_adopt_dates_movie_backfills_date_and_keeps_instance(db):
    db.upsert_movie_dates("tt5000000", released="2020-01-01", dateadded="2021-01-01T00:00:00",
                          source="radarr", title="Stale", year=2020, instance="radarr")
    db.upsert_movie_dates("tt5000000", released="2020-01-01", dateadded="2026-11-10T00:00:00",
                          source="radarr", title="Fresh reimport", year=2020, instance="radarr_strm")

    assert db.adopt_dates_movie("tt5000000", keep_instance="radarr_strm", source_instance="radarr") is True

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", ("tt5000000", "radarr_strm"))
        kept = cursor.fetchone()
        assert kept["dateadded"] == "2021-01-01T00:00:00"  # adopted from the stale row
        assert kept["title"] == "Fresh reimport"  # everything else about the kept row is untouched

        cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", ("tt5000000", "radarr"))
        assert cursor.fetchone() is None  # the stale source row is gone


def test_adopt_dates_movie_missing_either_side_returns_false(db):
    db.upsert_movie("tt5000001", path="/mnt/strm/Movie", instance="radarr_strm")
    assert db.adopt_dates_movie("tt5000001", keep_instance="radarr_strm", source_instance="radarr") is False

    db.upsert_movie("tt5000002", path="/mnt/nas/Movie", instance="radarr")
    assert db.adopt_dates_movie("tt5000002", keep_instance="radarr_strm", source_instance="radarr") is False


def test_adopt_dates_series_backfills_only_older_dates(db):
    db.upsert_series("tt6000000", path="/mnt/nas/Show", instance="sonarr")
    db.upsert_episode_date("tt6000000", 1, 1, aired="2020-01-01", dateadded="2020-10-10T02:40:00",
                           source="sonarr", instance="sonarr")
    db.upsert_episode_date("tt6000000", 1, 2, aired="2020-01-08", dateadded="2026-01-01T00:00:00",
                           source="sonarr", instance="sonarr")  # not actually older — must not overwrite

    db.upsert_series("tt6000000", path="/mnt/strm/Show", instance="sonarr_strm")
    db.upsert_episode_date("tt6000000", 1, 1, aired="2020-01-01", dateadded="2026-11-10T16:50:37",
                           source="sonarr", instance="sonarr_strm")
    db.upsert_episode_date("tt6000000", 1, 2, aired="2020-01-08", dateadded="2024-06-06T00:00:00",
                           source="sonarr", instance="sonarr_strm")

    updated = db.adopt_dates_series("tt6000000", keep_instance="sonarr_strm", source_instance="sonarr")

    assert updated == 1  # only S01E01's date was actually older on the source
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT season, episode, dateadded FROM episodes
            WHERE imdb_id = %s AND instance = %s ORDER BY episode
        """, ("tt6000000", "sonarr_strm"))
        rows = {(r["season"], r["episode"]): r["dateadded"] for r in cursor.fetchall()}
        assert rows[(1, 1)] == "2020-10-10T02:40:00"  # adopted
        assert rows[(1, 2)] == "2024-06-06T00:00:00"  # untouched — source's date wasn't older

        cursor.execute("SELECT * FROM series WHERE imdb_id = %s AND instance = %s", ("tt6000000", "sonarr"))
        assert cursor.fetchone() is None  # stale source dropped entirely

        cursor.execute("SELECT * FROM episodes WHERE imdb_id = %s AND instance = %s", ("tt6000000", "sonarr"))
        assert cursor.fetchall() == []


def test_adopt_dates_series_missing_either_side_returns_none(db):
    db.upsert_series("tt6000001", path="/mnt/strm/Show", instance="sonarr_strm")
    assert db.adopt_dates_series("tt6000001", keep_instance="sonarr_strm", source_instance="sonarr") is None
