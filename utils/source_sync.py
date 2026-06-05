"""
Library sync — compare Chronarr DB against current Radarr/Sonarr libraries.

Identifies movies/series that Radarr/Sonarr no longer manages and optionally
removes them from the Chronarr DB after a configurable grace period.
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from utils.logging import _log


def _radarr_imdb_ids() -> Optional[set]:
    """Return set of IMDb IDs currently in Radarr, or None if unavailable."""
    try:
        from clients.radarr_db_client import RadarrDbClient
        client = RadarrDbClient.from_env()
        if client is None:
            return None
        movies = client.get_all_movies()
        return {m["imdb_id"] for m in movies if m.get("imdb_id")}
    except Exception as e:
        _log("WARN", f"LibrarySync :: Radarr DB unavailable: {e}")
        return None


def _sonarr_imdb_ids() -> Optional[set]:
    """Return set of IMDb IDs currently in Sonarr, or None if unavailable."""
    try:
        from clients.sonarr_db_client import SonarrDbClient
        client = SonarrDbClient.from_env()
        if client is None:
            return None
        series = client.get_all_series()
        return {s["imdb_id"] for s in series if s.get("imdb_id")}
    except Exception as e:
        _log("WARN", f"LibrarySync :: Sonarr DB unavailable: {e}")
        return None


def run_sync(db, media_type: str = "both", dry_run: bool = True,
             remove_immediately: bool = False) -> dict:
    """
    Compare Chronarr DB against Radarr/Sonarr and update missing_from_source_since.

    Args:
        db: ChronarrDatabase instance
        media_type: "movies", "tv", or "both"
        dry_run: If True, make no changes to the DB
        remove_immediately: If True and not dry_run, delete items not in source now
                            (ignores grace period days)

    Returns dict with:
        movies_not_in_radarr  — list of {imdb_id, title, missing_since}
        series_not_in_sonarr  — list of {imdb_id, title, missing_since}
        movies_deleted        — count deleted this run
        series_deleted        — count deleted this run
        radarr_available      — bool
        sonarr_available      — bool
        dry_run               — bool
    """
    result = {
        "movies_not_in_radarr": [],
        "series_not_in_sonarr": [],
        "movies_deleted": 0,
        "series_deleted": 0,
        "radarr_available": False,
        "sonarr_available": False,
        "dry_run": dry_run,
    }

    now = datetime.now(timezone.utc)

    # ── Movies ────────────────────────────────────────────────────────────────
    if media_type in ("movies", "both"):
        radarr_ids = _radarr_imdb_ids()
        result["radarr_available"] = radarr_ids is not None

        if radarr_ids is not None:
            chronarr_movies = db.get_all_movie_records()
            in_radarr = set()
            not_in_radarr = []

            for movie in chronarr_movies:
                iid = movie["imdb_id"]
                if iid in radarr_ids:
                    in_radarr.add(iid)
                else:
                    not_in_radarr.append(movie)

            if not dry_run:
                # Mark newly missing items
                newly_missing = [m["imdb_id"] for m in not_in_radarr
                                 if not m.get("missing_from_source_since")]
                if newly_missing:
                    db.mark_movies_missing_from_source(newly_missing, now)
                    _log("INFO", f"LibrarySync :: Marked {len(newly_missing)} movies as missing from Radarr")

                # Clear items that came back
                returned = [iid for iid in in_radarr
                            if any(m["imdb_id"] == iid and m.get("missing_from_source_since")
                                   for m in chronarr_movies)]
                if returned:
                    db.clear_movies_missing_from_source(returned)
                    _log("INFO", f"LibrarySync :: Cleared {len(returned)} movies that returned to Radarr")

                if remove_immediately:
                    for movie in not_in_radarr:
                        db.delete_movie(movie["imdb_id"])
                        result["movies_deleted"] += 1
                    _log("INFO", f"LibrarySync :: Deleted {result['movies_deleted']} movies not in Radarr")

            # Re-fetch to get updated missing_since for response
            refreshed = {m["imdb_id"]: m for m in db.get_all_movie_records()}
            for movie in not_in_radarr:
                iid = movie["imdb_id"]
                rec = refreshed.get(iid, movie)
                result["movies_not_in_radarr"].append({
                    "imdb_id": iid,
                    "title": movie.get("title") or iid,
                    "path": movie.get("path", ""),
                    "missing_since": rec.get("missing_from_source_since"),
                })

    # ── TV Series ─────────────────────────────────────────────────────────────
    if media_type in ("tv", "both"):
        sonarr_ids = _sonarr_imdb_ids()
        result["sonarr_available"] = sonarr_ids is not None

        if sonarr_ids is not None:
            chronarr_series = db.get_all_series_records()
            in_sonarr = set()
            not_in_sonarr = []

            for series in chronarr_series:
                iid = series["imdb_id"]
                if iid in sonarr_ids:
                    in_sonarr.add(iid)
                else:
                    not_in_sonarr.append(series)

            if not dry_run:
                newly_missing = [s["imdb_id"] for s in not_in_sonarr
                                 if not s.get("missing_from_source_since")]
                if newly_missing:
                    db.mark_series_missing_from_source(newly_missing, now)
                    _log("INFO", f"LibrarySync :: Marked {len(newly_missing)} series as missing from Sonarr")

                returned = [iid for iid in in_sonarr
                            if any(s["imdb_id"] == iid and s.get("missing_from_source_since")
                                   for s in chronarr_series)]
                if returned:
                    db.clear_series_missing_from_source(returned)
                    _log("INFO", f"LibrarySync :: Cleared {len(returned)} series that returned to Sonarr")

                if remove_immediately:
                    for series in not_in_sonarr:
                        db.delete_series(series["imdb_id"])
                        result["series_deleted"] += 1
                    _log("INFO", f"LibrarySync :: Deleted {result['series_deleted']} series not in Sonarr")

            refreshed = {s["imdb_id"]: s for s in db.get_all_series_records()}
            for series in not_in_sonarr:
                iid = series["imdb_id"]
                rec = refreshed.get(iid, series)
                title = ""
                try:
                    meta = series.get("metadata") or {}
                    title = meta.get("title") or iid
                except Exception:
                    title = iid
                result["series_not_in_sonarr"].append({
                    "imdb_id": iid,
                    "title": title,
                    "path": series.get("path", ""),
                    "missing_since": rec.get("missing_from_source_since"),
                })

    return result


def run_auto_purge(db) -> dict:
    """
    Run the auto-purge pass. Reads PURGE_MISSING_MOVIES_DAYS and
    PURGE_MISSING_TV_DAYS from environment (0 or unset = disabled).

    First updates missing_from_source_since by comparing against Radarr/Sonarr,
    then deletes items that have been missing longer than the configured threshold.
    """
    movie_days = int(os.environ.get("PURGE_MISSING_MOVIES_DAYS", "0") or 0)
    tv_days = int(os.environ.get("PURGE_MISSING_TV_DAYS", "0") or 0)

    if movie_days == 0 and tv_days == 0:
        return {"skipped": True, "reason": "auto-purge disabled (PURGE_MISSING_*_DAYS=0)"}

    media_type = "both"
    if movie_days == 0:
        media_type = "tv"
    elif tv_days == 0:
        media_type = "movies"

    # Non-destructive pass — just update missing_from_source_since
    run_sync(db, media_type=media_type, dry_run=False, remove_immediately=False)

    deleted_movies = 0
    deleted_series = 0
    now = datetime.now(timezone.utc)

    if movie_days > 0:
        cutoff = now - timedelta(days=movie_days)
        expired = db.get_movies_missing_before(cutoff)
        for movie in expired:
            db.delete_movie(movie["imdb_id"])
            deleted_movies += 1
        if deleted_movies:
            _log("INFO", f"LibrarySync :: Auto-purged {deleted_movies} movies (missing > {movie_days}d)")

    if tv_days > 0:
        cutoff = now - timedelta(days=tv_days)
        expired = db.get_series_missing_before(cutoff)
        for series in expired:
            db.delete_series(series["imdb_id"])
            deleted_series += 1
        if deleted_series:
            _log("INFO", f"LibrarySync :: Auto-purged {deleted_series} series (missing > {tv_days}d)")

    return {
        "deleted_movies": deleted_movies,
        "deleted_series": deleted_series,
        "movie_days_threshold": movie_days,
        "tv_days_threshold": tv_days,
    }
