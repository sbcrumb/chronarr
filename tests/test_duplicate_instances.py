"""
Tests for find_duplicate_movies/find_duplicate_series — the report behind
the Settings page's "Duplicate Titles" section, for titles moved by hand
between instances before migrate_*_instance existed to do that in place.
"""


def test_find_duplicate_movies_finds_only_titles_on_more_than_one_instance(db):
    db.upsert_movie_dates("tt3000000", released="2020-01-01", dateadded="2021-01-01T00:00:00",
                          source="radarr", title="Duplicated", year=2020, instance="radarr")
    db.upsert_movie_dates("tt3000000", released="2020-01-01", dateadded="2022-06-06T00:00:00",
                          source="radarr", title="Duplicated", year=2020, instance="radarr_strm")
    db.upsert_movie_dates("tt3000001", released="2020-01-01", dateadded="2021-01-01T00:00:00",
                          source="radarr", title="Not Duplicated", year=2020, instance="radarr")

    groups = db.find_duplicate_movies()

    assert len(groups) == 1
    group = groups[0]
    assert group["imdb_id"] == "tt3000000"
    assert group["title"] == "Duplicated"
    instances = {r["instance"]: r["dateadded"] for r in group["rows"]}
    assert instances == {"radarr": "2021-01-01T00:00:00", "radarr_strm": "2022-06-06T00:00:00"}


def test_find_duplicate_movies_empty_when_nothing_duplicated(db):
    db.upsert_movie("tt3000002", path="/mnt/nas/Movie", instance="radarr")
    assert db.find_duplicate_movies() == []


def test_find_duplicate_series_reports_episode_counts_and_seasons_per_instance(db):
    db.upsert_series("tt4000000", path="/mnt/nas/Show (2020) [imdb-tt4000000]", instance="sonarr")
    db.upsert_episode_date("tt4000000", 1, 1, aired="2020-01-01", dateadded="2021-01-01T00:00:00",
                           source="sonarr", instance="sonarr")
    db.upsert_episode_date("tt4000000", 1, 2, aired="2020-01-08", dateadded="2021-01-08T00:00:00",
                           source="sonarr", instance="sonarr")

    db.upsert_series("tt4000000", path="/mnt/strm/Show (2020) [imdb-tt4000000]", instance="sonarr_strm")
    db.upsert_episode_date("tt4000000", 1, 1, aired="2020-01-01", dateadded="2023-09-09T00:00:00",
                           source="sonarr", instance="sonarr_strm")

    groups = db.find_duplicate_series()

    assert len(groups) == 1
    group = groups[0]
    assert group["imdb_id"] == "tt4000000"
    assert group["title"] == "Show"  # extract_title_from_directory_name strips year and imdb tag
    by_instance = {r["instance"]: r for r in group["rows"]}
    assert by_instance["sonarr"]["episode_count"] == 2
    assert by_instance["sonarr"]["seasons"] == [1]
    assert by_instance["sonarr"]["earliest_dateadded"] == "2021-01-01T00:00:00"
    assert by_instance["sonarr_strm"]["episode_count"] == 1


def test_find_duplicate_series_empty_when_nothing_duplicated(db):
    db.upsert_series("tt4000001", path="/mnt/nas/Show", instance="sonarr")
    assert db.find_duplicate_series() == []
