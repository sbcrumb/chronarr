#!/usr/bin/env python3
"""
Direct Sonarr Database Client for Chronarr
Provides high-performance access to Sonarr's SQLite/PostgreSQL database
"""

import os
import sqlite3
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from urllib.parse import urlparse

from core.logging import _log


class SonarrDbClient:
    """Direct database client for Sonarr's SQLite or PostgreSQL database"""

    def __init__(self,
                 db_type: str = "sqlite",
                 db_path: Optional[str] = None,
                 db_host: Optional[str] = None,
                 db_port: Optional[int] = None,
                 db_name: Optional[str] = None,
                 db_user: Optional[str] = None,
                 db_password: Optional[str] = None):
        """
        Initialize Sonarr database client

        Args:
            db_type: "sqlite" or "postgresql"
            db_path: Path to SQLite database file
            db_host: PostgreSQL host
            db_port: PostgreSQL port
            db_name: PostgreSQL database name
            db_user: PostgreSQL username
            db_password: PostgreSQL password
        """
        self.db_type = db_type.lower()
        self.db_path = db_path
        self.db_host = db_host
        self.db_port = db_port or 5432
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password

        self._test_connection()

    @classmethod
    def from_env(cls) -> Optional['SonarrDbClient']:
        """Create client from environment variables"""
        db_type = os.environ.get("SONARR_DB_TYPE", "").lower()

        if not db_type:
            return None

        if db_type == "sqlite":
            db_path = os.environ.get("SONARR_DB_PATH")
            if not db_path or not Path(db_path).exists():
                _log("WARNING", f"SONARR_DB_PATH not found or invalid: {db_path}")
                return None
            return cls(db_type="sqlite", db_path=db_path)

        elif db_type == "postgresql":
            # Support both individual vars and connection string
            db_url = os.environ.get("SONARR_DB_URL")
            if db_url:
                parsed = urlparse(db_url)
                return cls(
                    db_type="postgresql",
                    db_host=parsed.hostname,
                    db_port=parsed.port or 5432,
                    db_name=parsed.path.lstrip('/'),
                    db_user=parsed.username,
                    db_password=parsed.password
                )
            else:
                return cls(
                    db_type="postgresql",
                    db_host=os.environ.get("SONARR_DB_HOST"),
                    db_port=int(os.environ.get("SONARR_DB_PORT", "5432")),
                    db_name=os.environ.get("SONARR_DB_NAME"),
                    db_user=os.environ.get("SONARR_DB_USER"),
                    db_password=os.environ.get("SONARR_DB_PASSWORD")
                )
        else:
            _log("ERROR", f"Unsupported database type: {db_type}")
            return None

    def _test_connection(self) -> None:
        """Test database connection on initialization"""
        try:
            conn = self._get_connection()
            if conn:
                conn.close()
                _log("INFO", f"Connected to Sonarr {self.db_type} database successfully")
            else:
                raise Exception("Failed to create connection")
        except Exception as e:
            _log("ERROR", f"Failed to connect to Sonarr database: {e}")
            raise

    def _get_connection(self) -> Union[sqlite3.Connection, psycopg2.extensions.connection]:
        """Get database connection"""
        if self.db_type == "sqlite":
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        elif self.db_type == "postgresql":
            conn = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password
            )
            return conn
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

    def get_series_by_imdb(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """
        Find series by IMDb ID using database query

        Returns:
            Dictionary with series info including id, imdb_id, title, path
        """
        imdb_id = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"

        query = """
        SELECT
            "Id" as id,
            "ImdbId" as imdb_id,
            "TvdbId" as tvdb_id,
            "Title" as title,
            "Path" as path,
            "Added" as added
        FROM "Series"
        WHERE "ImdbId" = %s
        """

        if self.db_type == "sqlite":
            query = query.replace("%s", "?")

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                cursor.execute(query, (imdb_id,))
                row = cursor.fetchone()

                if row:
                    return dict(row) if self.db_type == "sqlite" else row

        except Exception as e:
            _log("ERROR", f"Database query error for IMDb {imdb_id}: {e}")

        return None

    def get_all_series(self) -> List[Dict[str, Any]]:
        """
        Get all series from the database

        Returns:
            List of series dictionaries with id, imdb_id, title, path
        """
        query = """
        SELECT
            "Id" as id,
            "ImdbId" as imdb_id,
            "TvdbId" as tvdb_id,
            "Title" as title,
            "Path" as path,
            "Added" as added
        FROM "Series"
        ORDER BY "Title"
        """

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                cursor.execute(query)
                rows = cursor.fetchall()

                if self.db_type == "sqlite":
                    return [dict(row) for row in rows]
                else:
                    return rows

        except Exception as e:
            _log("ERROR", f"Database query error getting all series: {e}")
            return []

    def get_all_episodes_for_series(self, series_id: int) -> List[Dict[str, Any]]:
        """
        Get all episodes for a series

        Args:
            series_id: Sonarr series ID

        Returns:
            List of episode dictionaries with season, episode, air_date
        """
        query = """
        SELECT
            "Id" as id,
            "SeasonNumber" as season,
            "EpisodeNumber" as episode,
            "Title" as title,
            "AirDate" as air_date,
            "EpisodeFileId" as episode_file_id
        FROM "Episodes"
        WHERE "SeriesId" = %s
        ORDER BY "SeasonNumber", "EpisodeNumber"
        """

        if self.db_type == "sqlite":
            query = query.replace("%s", "?")

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                cursor.execute(query, (series_id,))
                rows = cursor.fetchall()

                if self.db_type == "sqlite":
                    return [dict(row) for row in rows]
                else:
                    return rows

        except Exception as e:
            _log("ERROR", f"Database query error for series {series_id}: {e}")
            return []

    def get_episode_import_date(self, episode_id: int) -> Tuple[Optional[str], str]:
        """
        Get earliest import date for an episode from History table

        Args:
            episode_id: Sonarr episode ID

        Returns:
            (date_iso, source_description)
        """
        # Query for earliest import event (EventType 3)
        import_query = """
        SELECT
            "Date" as event_date,
            "EventType" as event_type
        FROM "History"
        WHERE "EpisodeId" = %s
            AND "EventType" = 3
        ORDER BY "Date" ASC
        LIMIT 1
        """

        if self.db_type == "sqlite":
            import_query = import_query.replace("%s", "?")

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                # Try import events first
                cursor.execute(import_query, (episode_id,))
                row = cursor.fetchone()

                if row:
                    event_date = row['event_date'] if self.db_type == "postgresql" else row[0]
                    if isinstance(event_date, str):
                        dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
                    else:
                        dt = event_date.replace(tzinfo=timezone.utc)

                    date_iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                    return date_iso, "sonarr:db.history.import"

        except Exception as e:
            _log("ERROR", f"Database query error for episode {episode_id}: {e}")

        return None, "sonarr:db.no_import_found"

    def get_episode_file_date(self, series_id: int, season: int, episode: int) -> Optional[str]:
        """
        Get episode file DateAdded as fallback

        Args:
            series_id: Sonarr series ID
            season: Season number
            episode: Episode number

        Returns:
            ISO date string or None
        """
        # First get the episode ID to find the file
        episode_query = """
        SELECT "EpisodeFileId"
        FROM "Episodes"
        WHERE "SeriesId" = %s
            AND "SeasonNumber" = %s
            AND "EpisodeNumber" = %s
        """

        file_query = """
        SELECT "DateAdded"
        FROM "EpisodeFiles"
        WHERE "Id" = %s
        """

        if self.db_type == "sqlite":
            episode_query = episode_query.replace("%s", "?")
            file_query = file_query.replace("%s", "?")

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                # Get episode file ID
                cursor.execute(episode_query, (series_id, season, episode))
                row = cursor.fetchone()

                if row:
                    file_id = row['EpisodeFileId'] if self.db_type == "postgresql" else row[0]

                    if file_id:
                        # Get file date
                        cursor.execute(file_query, (file_id,))
                        file_row = cursor.fetchone()

                        if file_row:
                            date_value = file_row['DateAdded'] if self.db_type == "postgresql" else file_row[0]

                            if isinstance(date_value, str):
                                dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                            else:
                                dt = date_value.replace(tzinfo=timezone.utc)

                            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

        except Exception as e:
            _log("ERROR", f"Database query error for episode file: {e}")

        return None

    def bulk_import_dates_for_series(self, series_id: int) -> Dict[Tuple[int, int], Tuple[Optional[str], str]]:
        """
        Get import dates for all episodes in a series in a single query

        Args:
            series_id: Sonarr series ID

        Returns:
            Dictionary mapping (season, episode) -> (date_iso, source)
        """
        query = """
        SELECT
            e."SeasonNumber" as season,
            e."EpisodeNumber" as episode,
            e."Id" as episode_id,
            MIN(h."Date") as earliest_import
        FROM "Episodes" e
        LEFT JOIN "History" h ON e."Id" = h."EpisodeId" AND h."EventType" = 3
        WHERE e."SeriesId" = %s
        GROUP BY e."SeasonNumber", e."EpisodeNumber", e."Id"
        ORDER BY e."SeasonNumber", e."EpisodeNumber"
        """

        if self.db_type == "sqlite":
            query = query.replace("%s", "?")

        results = {}

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                cursor.execute(query, (series_id,))
                rows = cursor.fetchall()

                for row in rows:
                    if self.db_type == "postgresql":
                        season, episode, episode_id, earliest_import = row['season'], row['episode'], row['episode_id'], row['earliest_import']
                    else:
                        season, episode, episode_id, earliest_import = row[0], row[1], row[2], row[3]

                    if earliest_import:
                        if isinstance(earliest_import, str):
                            dt = datetime.fromisoformat(earliest_import.replace("Z", "+00:00"))
                        else:
                            dt = earliest_import.replace(tzinfo=timezone.utc)

                        date_iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                        results[(season, episode)] = (date_iso, "sonarr:db.bulk.import")
                    else:
                        results[(season, episode)] = (None, "sonarr:db.bulk.no_import")

        except Exception as e:
            _log("ERROR", f"Bulk query error for series {series_id}: {e}")

        return results

    def get_database_stats(self) -> Dict[str, Any]:
        """Get basic statistics about the Sonarr database"""
        stats = {}

        queries = {
            "total_series": 'SELECT COUNT(*) FROM "Series"',
            "total_episodes": 'SELECT COUNT(*) FROM "Episodes"',
            "total_episode_files": 'SELECT COUNT(*) FROM "EpisodeFiles"',
            "total_history_events": 'SELECT COUNT(*) FROM "History"',
            "import_events": 'SELECT COUNT(*) FROM "History" WHERE "EventType" = 3',
            "grab_events": 'SELECT COUNT(*) FROM "History" WHERE "EventType" = 1'
        }

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                for stat_name, query in queries.items():
                    cursor.execute(query)
                    result = cursor.fetchone()
                    stats[stat_name] = result[0] if result else 0

        except Exception as e:
            _log("ERROR", f"Stats query error: {e}")
            stats["error"] = str(e)

        return stats

    def health_check(self) -> Dict[str, Any]:
        """
        Comprehensive health check for the Sonarr database connection

        Returns:
            Dictionary with health status, connection info, and basic functionality tests
        """
        health = {
            "status": "healthy",
            "database_type": self.db_type,
            "connection": "ok",
            "readable": False,
            "tables_exist": False,
            "sample_data": False,
            "issues": [],
            "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
        }

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Test 1: Basic read
                try:
                    cursor.execute('SELECT 1')
                    result = cursor.fetchone()
                    if result and result[0] == 1:
                        health["readable"] = True
                        health["connection"] = "readable"
                    else:
                        health["issues"].append("Basic SELECT query failed")
                except Exception as e:
                    health["issues"].append(f"Read test failed: {e}")
                    health["status"] = "degraded"

                # Test 2: Check required tables
                required_tables = ["Series", "Episodes", "EpisodeFiles", "History"]
                existing_tables = []

                try:
                    if self.db_type == "postgresql":
                        cursor.execute("""
                            SELECT table_name
                            FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name IN ('Series', 'Episodes', 'EpisodeFiles', 'History')
                        """)
                    else:  # SQLite
                        cursor.execute("""
                            SELECT name
                            FROM sqlite_master
                            WHERE type='table'
                            AND name IN ('Series', 'Episodes', 'EpisodeFiles', 'History')
                        """)

                    rows = cursor.fetchall()
                    existing_tables = [row[0] for row in rows]

                    if len(existing_tables) == len(required_tables):
                        health["tables_exist"] = True
                    else:
                        missing = set(required_tables) - set(existing_tables)
                        health["issues"].append(f"Missing tables: {list(missing)}")
                        health["status"] = "degraded"

                    health["existing_tables"] = existing_tables

                except Exception as e:
                    health["issues"].append(f"Table check failed: {e}")
                    health["status"] = "degraded"

                # Test 3: Check for sample data
                if health["tables_exist"]:
                    try:
                        cursor.execute('SELECT COUNT(*) FROM "Series"')
                        series_count = cursor.fetchone()[0]

                        cursor.execute('SELECT COUNT(*) FROM "Episodes"')
                        episode_count = cursor.fetchone()[0]

                        cursor.execute('SELECT COUNT(*) FROM "History"')
                        history_count = cursor.fetchone()[0]

                        if series_count > 0 and episode_count > 0:
                            health["sample_data"] = True
                            health["series_count"] = series_count
                            health["episode_count"] = episode_count
                            health["history_count"] = history_count
                        else:
                            health["issues"].append(f"Low data counts - Series: {series_count}, Episodes: {episode_count}")

                    except Exception as e:
                        health["issues"].append(f"Sample data check failed: {e}")

                # Test 4: Test a real query
                if health["sample_data"]:
                    try:
                        cursor.execute("""
                            SELECT COUNT(*)
                            FROM "Series"
                            WHERE "ImdbId" IS NOT NULL
                        """)
                        imdb_series = cursor.fetchone()[0]
                        health["series_with_imdb"] = imdb_series

                        if imdb_series > 0:
                            health["functional"] = True
                        else:
                            health["issues"].append("No series with IMDb IDs found")

                    except Exception as e:
                        health["issues"].append(f"Functional test failed: {e}")
                        health["status"] = "degraded"

        except Exception as e:
            health["status"] = "error"
            health["connection"] = "failed"
            health["issues"].append(f"Connection failed: {e}")
            _log("ERROR", f"Database health check failed: {e}")

        # Overall status
        if health["issues"]:
            if health["status"] == "healthy":
                health["status"] = "degraded"

        # Add connection details (safe info only)
        health["connection_info"] = {
            "type": self.db_type,
            "host": self.db_host if self.db_type == "postgresql" else None,
            "port": self.db_port if self.db_type == "postgresql" else None,
            "database": self.db_name if self.db_type == "postgresql" else None,
            "path": self.db_path if self.db_type == "sqlite" else None
        }

        return health


if __name__ == "__main__":
    # Test the database client
    print("Testing SonarrDbClient...")

    # Test with environment variables
    client = SonarrDbClient.from_env()
    if client:
        print("✅ Connected to Sonarr database")

        # Test stats
        stats = client.get_database_stats()
        print(f"Database stats: {stats}")

        # Test series lookup
        test_series = client.get_series_by_imdb("tt1628033")  # Top Gear from your data
        if test_series:
            print(f"Found test series: {test_series}")

            # Test episodes
            series_id = test_series['id']
            episodes = client.get_all_episodes_for_series(series_id)
            print(f"Found {len(episodes)} episodes")

            # Test bulk import dates
            if episodes:
                import_dates = client.bulk_import_dates_for_series(series_id)
                print(f"Import dates for {len(import_dates)} episodes")
        else:
            print("Test series not found")
    else:
        print("❌ Could not connect to database - check environment variables")
