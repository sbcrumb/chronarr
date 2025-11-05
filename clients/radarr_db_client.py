#!/usr/bin/env python3
"""
Direct Radarr Database Client for Chronarr
Provides high-performance access to Radarr's SQLite/PostgreSQL database
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


class RadarrDbClient:
    """Direct database client for Radarr's SQLite or PostgreSQL database"""
    
    def __init__(self, 
                 db_type: str = "sqlite",
                 db_path: Optional[str] = None, 
                 db_host: Optional[str] = None,
                 db_port: Optional[int] = None,
                 db_name: Optional[str] = None,
                 db_user: Optional[str] = None,
                 db_password: Optional[str] = None):
        """
        Initialize Radarr database client
        
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
    def from_env(cls) -> Optional['RadarrDbClient']:
        """Create client from environment variables"""
        db_type = os.environ.get("RADARR_DB_TYPE", "").lower()
        
        if not db_type:
            return None
            
        if db_type == "sqlite":
            db_path = os.environ.get("RADARR_DB_PATH")
            if not db_path or not Path(db_path).exists():
                _log("WARNING", f"RADARR_DB_PATH not found or invalid: {db_path}")
                return None
            return cls(db_type="sqlite", db_path=db_path)
            
        elif db_type == "postgresql":
            # Support both individual vars and connection string
            db_url = os.environ.get("RADARR_DB_URL")
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
                    db_host=os.environ.get("RADARR_DB_HOST"),
                    db_port=int(os.environ.get("RADARR_DB_PORT", "5432")),
                    db_name=os.environ.get("RADARR_DB_NAME"),
                    db_user=os.environ.get("RADARR_DB_USER"),
                    db_password=os.environ.get("RADARR_DB_PASSWORD")
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
                _log("INFO", f"Connected to Radarr {self.db_type} database successfully")
            else:
                raise Exception("Failed to create connection")
        except Exception as e:
            _log("ERROR", f"Failed to connect to Radarr database: {e}")
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
    
    def get_movie_by_imdb(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """
        Find movie by IMDb ID using database query
        
        Returns:
            Dictionary with movie info including id, imdbId, title, year, path
        """
        imdb_id = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"
        
        query = """
        SELECT 
            m."Id" as id,
            m."Path" as path,
            m."Added" as added,
            mm."ImdbId" as imdb_id,
            mm."Title" as title,
            mm."Year" as year,
            mm."DigitalRelease" as digital_release
        FROM "Movies" m
        JOIN "MovieMetadata" mm ON m."MovieMetadataId" = mm."Id"
        WHERE mm."ImdbId" = %s
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

    def get_all_movies(self) -> List[Dict[str, Any]]:
        """
        Get all movies from Radarr database (only movies with files)

        Returns:
            List of dictionaries with movie info
        """
        query = """
        SELECT
            m."Id" as id,
            m."Path" as path,
            m."Added" as added,
            mm."ImdbId" as imdb_id,
            mm."Title" as title,
            mm."Year" as year,
            mm."DigitalRelease" as digital_release,
            mm."PhysicalRelease" as physical_release,
            mm."InCinemas" as in_cinemas,
            (SELECT COUNT(*) FROM "MovieFiles" mf WHERE mf."MovieId" = m."Id") as file_count
        FROM "Movies" m
        JOIN "MovieMetadata" mm ON m."MovieMetadataId" = mm."Id"
        WHERE (SELECT COUNT(*) FROM "MovieFiles" mf WHERE mf."MovieId" = m."Id") > 0
        ORDER BY mm."Title"
        """

        if self.db_type == "sqlite":
            # SQLite uses ? placeholders but this query has none
            pass

        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()

                cursor.execute(query)
                rows = cursor.fetchall()

                if rows:
                    return [dict(row) if self.db_type == "sqlite" else row for row in rows]
                return []

        except Exception as e:
            _log("ERROR", f"Database query error getting all movies: {e}")
            return []

    def get_earliest_import_date(self, movie_id: int) -> Tuple[Optional[str], str]:
        """
        Get earliest import date from History table, accounting for upgrade scenarios
        
        Args:
            movie_id: Radarr movie ID
            
        Returns:
            (date_iso, source_description)
        """
        # If first event is rename, all subsequent imports are upgrades - skip them
        if self.is_first_event_rename_based(movie_id):
            _log("INFO", f"Movie {movie_id} has rename-first history - all imports are upgrades, skipping")
            return None, "radarr:db.upgrade_imports_skipped"
        
        # Query for earliest import event - PostgreSQL uses INTEGER EventType (3 = import)
        import_query = """
        SELECT 
            h."Date" as event_date,
            h."Data" as event_data,
            h."EventType" as event_type
        FROM "History" h
        WHERE h."MovieId" = %s 
            AND h."EventType" = 3
        ORDER BY h."Date" ASC
        LIMIT 1
        """
        
        # Fallback: earliest grab event - PostgreSQL uses INTEGER EventType (1 = grab)
        grab_query = """
        SELECT 
            h."Date" as event_date,
            h."Data" as event_data,
            h."EventType" as event_type
        FROM "History" h
        WHERE h."MovieId" = %s 
            AND h."EventType" = 1
            AND h."Data" IS NOT NULL
        ORDER BY h."Date" ASC
        LIMIT 1
        """
        
        if self.db_type == "sqlite":
            import_query = import_query.replace("%s", "?")
            grab_query = grab_query.replace("%s", "?")
        
        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()
                
                # Try import events first
                cursor.execute(import_query, (movie_id,))
                row = cursor.fetchone()
                
                if row:
                    event_date = row['event_date'] if self.db_type == "postgresql" else row[0]
                    event_type = row['event_type'] if self.db_type == "postgresql" else row[2]
                    if isinstance(event_date, str):
                        dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
                    else:
                        dt = event_date.replace(tzinfo=timezone.utc)
                    
                    date_iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                    _log("INFO", f"✅ Found import event ({event_type}) for movie {movie_id} at {date_iso}")
                    return date_iso, "radarr:db.history.import"
                
                # Fallback to grab events
                cursor.execute(grab_query, (movie_id,))
                row = cursor.fetchone()
                
                if row:
                    event_date = row['event_date'] if self.db_type == "postgresql" else row[0]
                    event_type = row['event_type'] if self.db_type == "postgresql" else row[2]
                    if isinstance(event_date, str):
                        dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
                    else:
                        dt = event_date.replace(tzinfo=timezone.utc)
                    
                    date_iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                    _log("WARNING", f"⚠️ Using grab event ({event_type}) for movie {movie_id} at {date_iso}")
                    return date_iso, "radarr:db.history.grab"
                    
        except Exception as e:
            _log("ERROR", f"Database query error for movie {movie_id}: {e}")
            
        return None, "radarr:db.no_date_found"

    def is_first_event_rename_based(self, movie_id: int) -> bool:
        """
        Check if the first event in history is rename-based (not a true import)
        
        This helps identify movies where:
        - First event: movieFileRenamed (EventType = 8)
        - Followed by: downloadFolderImported (EventType = 3) - this is an upgrade
        
        In such cases, we should prefer release dates over the upgrade date
        """
        query = """
        SELECT h."EventType" as event_type, h."Date" as event_date
        FROM "History" h
        WHERE h."MovieId" = %s
        ORDER BY h."Date" ASC
        LIMIT 5
        """
        
        if self.db_type == "sqlite":
            query = query.replace("%s", "?")
        
        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()
                
                cursor.execute(query, (movie_id,))
                rows = cursor.fetchall()
                
                if rows:
                    _log("INFO", f"Movie {movie_id} history debug - first 5 events:")
                    for i, row in enumerate(rows):
                        event_type = row['event_type'] if self.db_type == "postgresql" else row[0] 
                        event_date = row['event_date'] if self.db_type == "postgresql" else row[1]
                        _log("INFO", f"  Event {i+1}: Type={event_type}, Date={event_date}")
                    
                    first_event_type = rows[0]['event_type'] if self.db_type == "postgresql" else rows[0][0]
                    # EventType 8 = movieFileRenamed
                    # Also check for EventType 7 = movieFileRenamed in some Radarr versions
                    is_rename_first = first_event_type in [7, 8]
                    _log("INFO", f"Movie {movie_id}: First event type={first_event_type}, is_rename_first={is_rename_first}")
                    
                    if is_rename_first:
                        _log("INFO", f"🎯 Movie {movie_id} detected as rename-first scenario - will prefer release dates over import dates")
                    
                    return is_rename_first
                else:
                    _log("WARNING", f"Movie {movie_id}: No history events found - this could indicate missing data")
                    
        except Exception as e:
            _log("ERROR", f"Error checking first event type for movie {movie_id}: {e}")
            
        return False
    
    def get_movie_file_date(self, movie_id: int) -> Optional[str]:
        """
        Get earliest file dateAdded as fallback
        
        Args:
            movie_id: Radarr movie ID
            
        Returns:
            ISO date string or None
        """
        query = """
        SELECT MIN(mf."DateAdded") as earliest_date
        FROM "MovieFiles" mf
        WHERE mf."MovieId" = %s
        """
        
        if self.db_type == "sqlite":
            query = query.replace("%s", "?")
        
        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()
                    
                cursor.execute(query, (movie_id,))
                row = cursor.fetchone()
                
                if row:
                    date_value = row['earliest_date'] if self.db_type == "postgresql" else row[0]
                    if date_value:
                        if isinstance(date_value, str):
                            dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                        else:
                            dt = date_value.replace(tzinfo=timezone.utc)
                        
                        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                        
        except Exception as e:
            _log("ERROR", f"Database query error for movie file date {movie_id}: {e}")
            
        return None
    
    def get_movie_import_date_optimized(self, movie_id: int, fallback_to_file_date: bool = True) -> Tuple[Optional[str], str]:
        """
        Get the best import date for a movie using optimized database queries
        
        Args:
            movie_id: Radarr movie ID
            fallback_to_file_date: Whether to fall back to file dateAdded
            
        Returns:
            (date_iso, source_description)
        """
        # Try history first - this handles upgrade detection internally
        date_iso, source = self.get_earliest_import_date(movie_id)
        if date_iso:
            return date_iso, source
        
        # Check if we skipped upgrades and should prefer release dates
        if source == "radarr:db.upgrade_imports_skipped":
            _log("INFO", f"Movie {movie_id} upgrade scenario detected - signaling to prefer release dates")
            return None, "radarr:db.prefer_release_dates"
        
        # Fallback to file date if requested
        if fallback_to_file_date:
            file_date = self.get_movie_file_date(movie_id)
            if file_date:
                _log("WARNING", f"Using file dateAdded as fallback for movie_id {movie_id}")
                return file_date, "radarr:db.file.dateAdded"
        
        return None, "radarr:db.no_date_found"
    
    def bulk_import_dates(self, imdb_ids: List[str]) -> Dict[str, Tuple[Optional[str], str]]:
        """
        Get import dates for multiple movies in a single query
        
        Args:
            imdb_ids: List of IMDb IDs
            
        Returns:
            Dictionary mapping imdb_id -> (date_iso, source)
        """
        if not imdb_ids:
            return {}
        
        # Ensure all IMDb IDs have tt prefix
        clean_imdb_ids = [imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}" for imdb_id in imdb_ids]
        
        placeholders = ",".join(["%s"] * len(clean_imdb_ids))
        if self.db_type == "sqlite":
            placeholders = ",".join(["?"] * len(clean_imdb_ids))
        
        query = f"""
        SELECT 
            mm."ImdbId" as imdb_id,
            m."Id" as movie_id,
            MIN(h."Date") as earliest_import
        FROM "Movies" m
        JOIN "MovieMetadata" mm ON m."MovieMetadataId" = mm."Id"
        LEFT JOIN "History" h ON m."Id" = h."MovieId" AND h."EventType" = 3
        WHERE mm."ImdbId" IN ({placeholders})
        GROUP BY mm."ImdbId", m."Id"
        """
        
        results = {}
        
        try:
            with self._get_connection() as conn:
                if self.db_type == "postgresql":
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    cursor = conn.cursor()
                    
                cursor.execute(query, clean_imdb_ids)
                rows = cursor.fetchall()
                
                for row in rows:
                    if self.db_type == "postgresql":
                        imdb_id, movie_id, earliest_import = row['imdb_id'], row['movie_id'], row['earliest_import']
                    else:
                        imdb_id, movie_id, earliest_import = row[0], row[1], row[2]
                    
                    if earliest_import:
                        if isinstance(earliest_import, str):
                            dt = datetime.fromisoformat(earliest_import.replace("Z", "+00:00"))
                        else:
                            dt = earliest_import.replace(tzinfo=timezone.utc)
                        
                        date_iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                        results[imdb_id] = (date_iso, "radarr:db.bulk.import")
                    else:
                        results[imdb_id] = (None, "radarr:db.bulk.no_import")
                
        except Exception as e:
            _log("ERROR", f"Bulk query error: {e}")
            # Return empty results for failed queries
            for imdb_id in clean_imdb_ids:
                if imdb_id not in results:
                    results[imdb_id] = (None, "radarr:db.bulk.error")
        
        return results
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get basic statistics about the Radarr database"""
        stats = {}
        
        queries = {
            "total_movies": 'SELECT COUNT(*) FROM "Movies"',
            "total_movie_files": 'SELECT COUNT(*) FROM "MovieFiles"',
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
        Comprehensive health check for the Radarr database connection
        
        Returns:
            Dictionary with health status, connection info, and basic functionality tests
        """
        health = {
            "status": "healthy",
            "database_type": self.db_type,
            "connection": "ok",
            "readable": False,
            "writable": False,
            "tables_exist": False,
            "sample_data": False,
            "issues": [],
            "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
        }
        
        try:
            # Test 1: Basic connection
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Test 2: Check if we can read (basic query)
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
                
                # Test 3: Check required tables exist
                required_tables = ["Movies", "MovieMetadata", "History", "MovieFiles"]
                existing_tables = []
                
                try:
                    if self.db_type == "postgresql":
                        cursor.execute("""
                            SELECT table_name 
                            FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name IN ('Movies', 'MovieMetadata', 'History', 'MovieFiles')
                        """)
                    else:  # SQLite
                        cursor.execute("""
                            SELECT name 
                            FROM sqlite_master 
                            WHERE type='table' 
                            AND name IN ('Movies', 'MovieMetadata', 'History', 'MovieFiles')
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
                
                # Test 4: Check for sample data
                if health["tables_exist"]:
                    try:
                        cursor.execute('SELECT COUNT(*) FROM "Movies"')
                        movie_count = cursor.fetchone()[0]
                        
                        cursor.execute('SELECT COUNT(*) FROM "History"')
                        history_count = cursor.fetchone()[0]
                        
                        if movie_count > 0 and history_count > 0:
                            health["sample_data"] = True
                            health["movie_count"] = movie_count
                            health["history_count"] = history_count
                        else:
                            health["issues"].append(f"Low data counts - Movies: {movie_count}, History: {history_count}")
                            
                    except Exception as e:
                        health["issues"].append(f"Sample data check failed: {e}")
                
                # Test 5: Test a real query (movie with IMDb lookup)
                if health["sample_data"]:
                    try:
                        cursor.execute("""
                            SELECT COUNT(*) 
                            FROM "Movies" m
                            JOIN "MovieMetadata" mm ON m."MovieMetadataId" = mm."Id"
                            WHERE mm."ImdbId" IS NOT NULL
                        """)
                        imdb_movies = cursor.fetchone()[0]
                        health["movies_with_imdb"] = imdb_movies
                        
                        if imdb_movies > 0:
                            health["functional"] = True
                        else:
                            health["issues"].append("No movies with IMDb IDs found")
                            
                    except Exception as e:
                        health["issues"].append(f"Functional test failed: {e}")
                        health["status"] = "degraded"
        
        except Exception as e:
            health["status"] = "error"
            health["connection"] = "failed"
            health["issues"].append(f"Connection failed: {e}")
            _log("ERROR", f"Database health check failed: {e}")
        
        # Overall status determination
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
    print("Testing RadarrDbClient...")
    
    # Test with environment variables
    client = RadarrDbClient.from_env()
    if client:
        print("✅ Connected to Radarr database")
        
        # Test stats
        stats = client.get_database_stats()
        print(f"Database stats: {stats}")
        
        # Test movie lookup
        test_movie = client.get_movie_by_imdb("tt1596343")
        if test_movie:
            print(f"Found test movie: {test_movie}")
            
            # Test import date
            movie_id = test_movie['id']
            date_iso, source = client.get_movie_import_date_optimized(movie_id)
            print(f"Import date: {date_iso} (source: {source})")
        else:
            print("Test movie not found")
    else:
        print("❌ Could not connect to database - check environment variables")