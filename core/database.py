#!/usr/bin/env python3
"""
PostgreSQL database management for Chronarr
Handles database operations for tracking media dates and processing history
"""
import json
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

class ChronarrDatabase:
    """PostgreSQL database manager for Chronarr media tracking and processing history"""
    
    def __init__(self, config):
        """
        Initialize PostgreSQL database connection
        
        Args:
            config: Configuration object with database settings
        """
        if not config:
            raise ValueError("PostgreSQL configuration is required")
        self.db_host = config.db_host
        self.db_port = config.db_port
        self.db_name = config.db_name
        self.db_user = config.db_user
        self.db_password = config.db_password
        self.db_type = "postgresql"  # Chronarr uses PostgreSQL
        
        self._local = threading.local()
        self._init_database()
    
    
    def _get_connection(self) -> 'psycopg2.extensions.connection':
        """Get thread-local PostgreSQL database connection"""
        if not hasattr(self._local, 'connection'):
            self._local.connection = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
            self._local.connection.autocommit = True
        return self._local.connection
    
    def _get_first_value(self, row):
        """Get first value from row from PostgreSQL RealDictCursor"""
        # RealDictCursor returns dict-like objects
        return list(row.values())[0] if row else None
    
    @contextmanager
    def get_connection(self):
        """Context manager for PostgreSQL database connections"""
        conn = self._get_connection()
        try:
            yield conn
            # PostgreSQL uses autocommit - no manual commit needed
        except Exception:
            # PostgreSQL uses autocommit - no manual rollback needed
            raise
    
    def _init_database(self):
        """Initialize PostgreSQL database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            self._init_postgresql_tables(cursor)
            
            # Test the connection works and verify autocommit
            cursor.execute("SELECT 1")
            print(f"✅ PostgreSQL database initialized and connection verified")
            print(f"🔍 Autocommit status: {conn.autocommit}")
    
    def _init_postgresql_tables(self, cursor):
        """Initialize database tables"""
        # Series table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS series (
                imdb_id VARCHAR(20) PRIMARY KEY,
                path TEXT NOT NULL,
                last_updated TIMESTAMP NOT NULL,
                metadata JSONB
            )
        """)
        
        # Episodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                imdb_id VARCHAR(20) NOT NULL,
                season INTEGER NOT NULL,
                episode INTEGER NOT NULL,
                aired DATE,
                dateadded TIMESTAMP,
                source VARCHAR(100),
                last_updated TIMESTAMP NOT NULL,
                has_video_file BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (imdb_id, season, episode),
                FOREIGN KEY (imdb_id) REFERENCES series(imdb_id)
            )
        """)
        
        # Movies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                imdb_id VARCHAR(20) PRIMARY KEY,
                title TEXT,
                year INTEGER,
                path TEXT NOT NULL,
                released DATE,
                dateadded TIMESTAMP,
                source VARCHAR(100),
                last_updated TIMESTAMP NOT NULL,
                has_video_file BOOLEAN DEFAULT FALSE
            )
        """)

        # Add title and year columns if they don't exist (migration for existing databases)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='movies' AND column_name='title') THEN
                    ALTER TABLE movies ADD COLUMN title TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='movies' AND column_name='year') THEN
                    ALTER TABLE movies ADD COLUMN year INTEGER;
                END IF;
            END $$;
        """)

        # Add skipped and skip_reason columns if they don't exist (migration for skip tracking)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='movies' AND column_name='skipped') THEN
                    ALTER TABLE movies ADD COLUMN skipped BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='movies' AND column_name='skip_reason') THEN
                    ALTER TABLE movies ADD COLUMN skip_reason TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='episodes' AND column_name='skipped') THEN
                    ALTER TABLE episodes ADD COLUMN skipped BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='episodes' AND column_name='skip_reason') THEN
                    ALTER TABLE episodes ADD COLUMN skip_reason TEXT;
                END IF;
            END $$;
        """)
        
        # Processing history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_history (
                id SERIAL PRIMARY KEY,
                imdb_id VARCHAR(20) NOT NULL,
                media_type VARCHAR(20) NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                processed_at TIMESTAMP NOT NULL,
                details TEXT
            )
        """)
        
        # Missing IMDb tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS missing_imdb (
                id SERIAL PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                media_type VARCHAR(20) NOT NULL,
                folder_name TEXT,
                filename TEXT,
                discovered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_checked TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                check_count INTEGER DEFAULT 1,
                notes TEXT,
                resolved BOOLEAN DEFAULT FALSE,
                resolved_at TIMESTAMP,
                resolved_imdb_id VARCHAR(20)
            )
        """)
        
        # Scheduled scans table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_scans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                cron_expression VARCHAR(100) NOT NULL,
                media_type VARCHAR(20) NOT NULL CHECK (media_type IN ('tv', 'movies', 'both')),
                scan_mode VARCHAR(20) NOT NULL CHECK (scan_mode IN ('smart', 'full', 'incomplete')),
                specific_paths TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_run_at TIMESTAMP,
                next_run_at TIMESTAMP,
                run_count INTEGER DEFAULT 0,
                created_by VARCHAR(100),
                updated_by VARCHAR(100)
            )
        """)
        
        # Schedule execution history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedule_executions (
                id SERIAL PRIMARY KEY,
                schedule_id INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(50) NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
                media_type VARCHAR(20) NOT NULL,
                scan_mode VARCHAR(20) NOT NULL,
                items_processed INTEGER DEFAULT 0,
                items_skipped INTEGER DEFAULT 0,
                items_failed INTEGER DEFAULT 0,
                execution_time_seconds INTEGER,
                error_message TEXT,
                logs TEXT,
                triggered_by VARCHAR(100),
                FOREIGN KEY (schedule_id) REFERENCES scheduled_scans(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for PostgreSQL
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_imdb ON episodes(imdb_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_video ON episodes(has_video_file)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movies_video ON movies(has_video_file)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_imdb ON processing_history(imdb_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_missing_imdb_type ON missing_imdb(media_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_missing_imdb_resolved ON missing_imdb(resolved)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_missing_imdb_path ON missing_imdb(file_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_scans_enabled ON scheduled_scans(enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_scans_next_run ON scheduled_scans(next_run_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_schedule_executions_schedule ON schedule_executions(schedule_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_schedule_executions_status ON schedule_executions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_schedule_executions_started ON schedule_executions(started_at)")
    def upsert_series(self, imdb_id: str, path: str, metadata: Optional[Dict] = None):
        """Insert or update series record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            
            cursor.execute("""
                INSERT INTO series (imdb_id, path, last_updated, metadata)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (imdb_id) DO UPDATE SET
                    path = EXCLUDED.path,
                    last_updated = EXCLUDED.last_updated,
                    metadata = EXCLUDED.metadata
            """, (imdb_id, path, timestamp, json.dumps(metadata) if metadata else None))
    
    def upsert_episode_date(self, imdb_id: str, season: int, episode: int, 
                           aired: Optional[str], dateadded: Optional[str], 
                           source: str, has_video_file: bool = False):
        """Insert or update episode date record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            
            cursor.execute("""
                INSERT INTO episodes 
                (imdb_id, season, episode, aired, dateadded, source, has_video_file, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (imdb_id, season, episode) DO UPDATE SET
                    aired = EXCLUDED.aired,
                    dateadded = EXCLUDED.dateadded,
                    source = EXCLUDED.source,
                    has_video_file = EXCLUDED.has_video_file,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, season, episode, aired, dateadded, source, has_video_file, timestamp))
            import os
            if os.environ.get("DEBUG", "false").lower() == "true":
                print(f"🔍 DEBUG: PostgreSQL upsert executed for {imdb_id} S{season:02d}E{episode:02d}, rows affected: {cursor.rowcount}")
    
    def upsert_movie(self, imdb_id: str, path: str):
        """Insert or update movie record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            
            cursor.execute("""
                INSERT INTO movies (imdb_id, path, last_updated)
                VALUES (%s, %s, %s)
                ON CONFLICT (imdb_id) DO UPDATE SET
                    path = EXCLUDED.path,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, path, timestamp))
    
    def upsert_movie_dates(self, imdb_id: str, released: Optional[str],
                          dateadded: Optional[str], source: str, has_video_file: bool = False,
                          title: Optional[str] = None, year: Optional[int] = None):
        """Insert or update movie date record"""
        import os
        if os.environ.get("DEBUG", "false").lower() == "true":
            print(f"🔍 DATABASE UPSERT: imdb_id={imdb_id}, title={title}, dateadded={dateadded}, source={source}")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()

            cursor.execute("""
                INSERT INTO movies (imdb_id, title, year, path, released, dateadded, source, has_video_file, last_updated)
                VALUES (%s, %s, %s, COALESCE((SELECT path FROM movies WHERE imdb_id = %s), 'unknown'), %s, %s, %s, %s, %s)
                ON CONFLICT (imdb_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    year = EXCLUDED.year,
                    released = EXCLUDED.released,
                    dateadded = EXCLUDED.dateadded,
                    source = EXCLUDED.source,
                    has_video_file = EXCLUDED.has_video_file,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, title, year, imdb_id, released, dateadded, source, has_video_file, timestamp))
            
            # Debug: Check what was actually saved
            cursor.execute("SELECT dateadded, source FROM movies WHERE imdb_id = %s", (imdb_id,))
            result = cursor.fetchone()
            import os
            if os.environ.get("DEBUG", "false").lower() == "true":
                print(f"🔍 DATABASE VERIFY: After upsert, found dateadded={result['dateadded'] if result else 'NOT_FOUND'}, source={result['source'] if result else 'NOT_FOUND'}")

    def mark_movie_skipped(self, imdb_id: str, title: str, year: int, path: str, reason: str):
        """Mark a movie as skipped with reason"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO movies (imdb_id, title, year, path, skipped, skip_reason, has_video_file, last_updated)
                VALUES (%s, %s, %s, %s, TRUE, %s, FALSE, %s)
                ON CONFLICT (imdb_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    year = EXCLUDED.year,
                    path = EXCLUDED.path,
                    skipped = TRUE,
                    skip_reason = EXCLUDED.skip_reason,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, title, year, path, reason, timestamp))

    def mark_episode_skipped(self, imdb_id: str, season: int, episode: int, reason: str):
        """Mark an episode as skipped with reason"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO episodes (imdb_id, season, episode, skipped, skip_reason, has_video_file, last_updated)
                VALUES (%s, %s, %s, TRUE, %s, FALSE, %s)
                ON CONFLICT (imdb_id, season, episode) DO UPDATE SET
                    skipped = TRUE,
                    skip_reason = EXCLUDED.skip_reason,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, season, episode, reason, timestamp))

    def clear_movie_skipped(self, imdb_id: str):
        """Clear skipped flag for a movie"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE movies SET skipped = FALSE, skip_reason = NULL
                WHERE imdb_id = %s
            """, (imdb_id,))

    def clear_episode_skipped(self, imdb_id: str, season: int, episode: int):
        """Clear skipped flag for an episode"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE episodes SET skipped = FALSE, skip_reason = NULL
                WHERE imdb_id = %s AND season = %s AND episode = %s
            """, (imdb_id, season, episode))

    def get_skipped_counts(self) -> Dict:
        """Get counts of skipped movies and episodes"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Count skipped movies
            cursor.execute("SELECT COUNT(*) as count FROM movies WHERE skipped = TRUE")
            skipped_movies = cursor.fetchone()['count']

            # Count skipped episodes
            cursor.execute("SELECT COUNT(*) as count FROM episodes WHERE skipped = TRUE")
            skipped_episodes = cursor.fetchone()['count']

            return {
                'movies': skipped_movies,
                'episodes': skipped_episodes,
                'total': skipped_movies + skipped_episodes
            }

    def get_series_episodes(self, imdb_id: str, has_video_file_only: bool = False) -> List[Dict]:
        """Get all episodes for a series"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM episodes WHERE imdb_id = %s"
            params = [imdb_id]
            if has_video_file_only:
                query += " AND has_video_file = TRUE"
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_episode_date(self, imdb_id: str, season: int, episode: int) -> Optional[Dict]:
        """Get episode date record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM episodes 
                WHERE imdb_id = %s AND season = %s AND episode = %s
            """, (imdb_id, season, episode))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_movie_dates(self, imdb_id: str) -> Optional[Dict]:
        """Get movie date record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM movies WHERE imdb_id = %s", (imdb_id,))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def add_processing_history(self, imdb_id: str, media_type: str, event_type: str, details: Optional[Dict] = None):
        """Add processing history entry"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO processing_history (imdb_id, media_type, event_type, processed_at, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (imdb_id, media_type, event_type, datetime.utcnow().isoformat(), 
                  json.dumps(details) if details else None))
    
    def migrate_movie_imdb_id(self, old_imdb_id: str, new_imdb_id: str) -> bool:
        """Migrate a movie from placeholder IMDb ID to real IMDb ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check if old record exists
            cursor.execute("SELECT * FROM movies WHERE imdb_id = %s", (old_imdb_id,))
            old_record = cursor.fetchone()
            if not old_record:
                return False

            old_data = dict(old_record)

            # Check if new IMDb ID already exists
            cursor.execute("SELECT * FROM movies WHERE imdb_id = %s", (new_imdb_id,))
            if cursor.fetchone():
                # New IMDb ID already exists, just delete the old one
                cursor.execute("DELETE FROM movies WHERE imdb_id = %s", (old_imdb_id,))
                return True

            # Create new record with correct IMDb ID
            cursor.execute("""
                INSERT INTO movies (imdb_id, title, year, path, released, dateadded, source,
                                   has_video_file, last_updated, skipped, skip_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (new_imdb_id, old_data.get('title'), old_data.get('year'),
                  old_data.get('path'), old_data.get('released'), old_data.get('dateadded'),
                  old_data.get('source'), old_data.get('has_video_file'),
                  datetime.utcnow(), False, None))  # Clear skipped status

            # Delete old placeholder record
            cursor.execute("DELETE FROM movies WHERE imdb_id = %s", (old_imdb_id,))
            return True

    def migrate_series_imdb_id(self, old_imdb_id: str, new_imdb_id: str) -> bool:
        """Migrate a series and all its episodes from placeholder IMDb ID to real IMDb ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check if old series exists
            cursor.execute("SELECT * FROM series WHERE imdb_id = %s", (old_imdb_id,))
            old_series = cursor.fetchone()
            if not old_series:
                return False

            old_series_data = dict(old_series)

            # Check if new series IMDb ID already exists
            cursor.execute("SELECT * FROM series WHERE imdb_id = %s", (new_imdb_id,))
            if cursor.fetchone():
                # New series already exists, migrate episodes and delete old series
                cursor.execute("""
                    UPDATE episodes SET imdb_id = %s WHERE imdb_id = %s
                """, (new_imdb_id, old_imdb_id))
                cursor.execute("DELETE FROM series WHERE imdb_id = %s", (old_imdb_id,))
                return True

            # Create new series record
            cursor.execute("""
                INSERT INTO series (imdb_id, path, last_updated, metadata)
                VALUES (%s, %s, %s, %s)
            """, (new_imdb_id, old_series_data.get('path'),
                  datetime.utcnow(), old_series_data.get('metadata')))

            # Migrate all episodes to new series IMDb ID and clear skipped status
            cursor.execute("""
                UPDATE episodes
                SET imdb_id = %s, skipped = FALSE, skip_reason = NULL
                WHERE imdb_id = %s
            """, (new_imdb_id, old_imdb_id))

            # Delete old placeholder series
            cursor.execute("DELETE FROM series WHERE imdb_id = %s", (old_imdb_id,))
            return True

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()  # Regular cursor for PostgreSQL
            
            # Series stats
            cursor.execute("SELECT COUNT(*) FROM series")
            series_count = self._get_first_value(cursor.fetchone())
            
            # Episode stats
            cursor.execute("SELECT COUNT(*) FROM episodes")
            episodes_total = self._get_first_value(cursor.fetchone())
            
            cursor.execute("SELECT COUNT(*) FROM episodes WHERE has_video_file = TRUE")
            episodes_with_video = self._get_first_value(cursor.fetchone())
            
            # Movie stats
            cursor.execute("SELECT COUNT(*) FROM movies")
            movies_total = self._get_first_value(cursor.fetchone())
            
            cursor.execute("SELECT COUNT(*) FROM movies WHERE has_video_file = TRUE")
            movies_with_video = self._get_first_value(cursor.fetchone())
            
            # Processing history
            cursor.execute("SELECT COUNT(*) FROM processing_history")
            history_count = self._get_first_value(cursor.fetchone())
            
            # Database size calculation for PostgreSQL
            cursor.execute("SELECT pg_database_size(%s)", (self.db_name,))
            db_size_bytes = self._get_first_value(cursor.fetchone())
            db_size_mb = round(db_size_bytes / 1024 / 1024, 2) if db_size_bytes else 0
            
            return {
                "series_count": series_count,
                "episodes_total": episodes_total,
                "episodes_with_video": episodes_with_video,
                "movies_total": movies_total,
                "movies_with_video": movies_with_video,
                "processing_history_count": history_count,
                "database_size_mb": db_size_mb,
                "database_type": "postgresql"
            }
    
    def delete_episode(self, imdb_id: str, season: int, episode: int) -> bool:
        """
        Delete a specific episode from the database
        
        Args:
            imdb_id: Series IMDb ID
            season: Season number
            episode: Episode number
            
        Returns:
            True if episode was deleted, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM episodes 
                WHERE imdb_id = %s AND season = %s AND episode = %s
            """, (imdb_id, season, episode))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count > 0
    
    def delete_series_episodes(self, imdb_id: str) -> int:
        """
        Delete all episodes for a series from the database
        
        Args:
            imdb_id: Series IMDb ID
            
        Returns:
            Number of episodes deleted
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM episodes 
                WHERE imdb_id = %s
            """, (imdb_id,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count
    
    def delete_orphaned_episodes(self) -> List[Dict]:
        """
        Find and delete episodes that don't have corresponding video files on disk
        This requires checking filesystem for each episode, so use carefully
        
        Returns:
            List of deleted episodes with their details
        """
        from utils.file_utils import find_episodes_on_disk
        from pathlib import Path
        
        deleted_episodes = []
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all series with their paths
            cursor.execute("""
                SELECT DISTINCT imdb_id, path FROM series
            """)
            
            series_list = cursor.fetchall()
            
            for series in series_list:
                imdb_id = series['imdb_id']
                series_path = Path(series['path'])
                
                if not series_path.exists():
                    continue
                
                # Get episodes on disk
                disk_episodes = find_episodes_on_disk(series_path)
                disk_episode_keys = set(disk_episodes.keys())
                
                # Get episodes in database
                cursor.execute("""
                    SELECT season, episode, dateadded, source 
                    FROM episodes 
                    WHERE imdb_id = %s
                """, (imdb_id,))
                
                db_episodes = cursor.fetchall()
                
                # Find orphaned episodes (in DB but not on disk)
                for db_episode in db_episodes:
                    season = db_episode['season']
                    episode = db_episode['episode']
                    episode_key = (season, episode)
                    
                    if episode_key not in disk_episode_keys:
                        # Episode is orphaned - delete it
                        cursor.execute("""
                            DELETE FROM episodes 
                            WHERE imdb_id = %s AND season = %s AND episode = %s
                        """, (imdb_id, season, episode))
                        
                        deleted_episodes.append({
                            'imdb_id': imdb_id,
                            'season': season,
                            'episode': episode,
                            'dateadded': db_episode['dateadded'],
                            'source': db_episode['source'],
                            'series_path': str(series_path)
                        })
            
            conn.commit()
            
        return deleted_episodes
    
    def delete_movie(self, imdb_id: str) -> bool:
        """
        Delete a specific movie from the database
        
        Args:
            imdb_id: Movie IMDb ID
            
        Returns:
            True if movie was deleted, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM movies 
                WHERE imdb_id = %s
            """, (imdb_id,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count > 0
    
    def delete_series(self, imdb_id: str) -> bool:
        """
        Delete a specific series from the database
        
        Args:
            imdb_id: Series IMDb ID
            
        Returns:
            True if series was deleted, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM series 
                WHERE imdb_id = %s
            """, (imdb_id,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count > 0

    def update_movie_file_info(self, imdb_id: str, path: str, has_video_file: bool = True) -> bool:
        """
        Update path and video file status for an existing movie
        Used when population finds a video file for a manually-added movie

        Args:
            imdb_id: Movie IMDb ID
            path: File path to the video file
            has_video_file: Whether a video file exists (default True)

        Returns:
            True if movie was updated, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE movies
                SET path = %s,
                    has_video_file = %s,
                    last_updated = %s
                WHERE imdb_id = %s
            """, (path, has_video_file, datetime.utcnow(), imdb_id))

            updated_count = cursor.rowcount
            conn.commit()

            return updated_count > 0

    def update_episode_file_info(self, imdb_id: str, season: int, episode: int,
                                  path: str, has_video_file: bool = True) -> bool:
        """
        Update path and video file status for an existing episode
        Used when population finds a video file for a manually-added episode

        Args:
            imdb_id: Series IMDb ID
            season: Season number
            episode: Episode number
            path: File path to the video file
            has_video_file: Whether a video file exists (default True)

        Returns:
            True if episode was updated, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE episodes
                SET path = %s,
                    has_video_file = %s,
                    last_updated = %s
                WHERE imdb_id = %s AND season = %s AND episode = %s
            """, (path, has_video_file, datetime.utcnow(), imdb_id, season, episode))

            updated_count = cursor.rowcount
            conn.commit()

            return updated_count > 0

    def delete_orphaned_movies(self) -> List[Dict]:
        """
        Find and delete movies that don't have corresponding video files on disk
        This requires checking filesystem for each movie, so use carefully
        
        Returns:
            List of deleted movies with their details
        """
        from pathlib import Path
        
        deleted_movies = []
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all movies with their paths
            cursor.execute("""
                SELECT imdb_id, path, dateadded, source 
                FROM movies
            """)
            
            movies_list = cursor.fetchall()
            
            for movie in movies_list:
                imdb_id = movie['imdb_id']
                movie_path = Path(movie['path'])
                
                if not movie_path.exists():
                    # Movie directory doesn't exist - delete it
                    cursor.execute("""
                        DELETE FROM movies 
                        WHERE imdb_id = %s
                    """, (imdb_id,))
                    
                    deleted_movies.append({
                        'imdb_id': imdb_id,
                        'reason': 'directory_not_found',
                        'path': str(movie_path),
                        'dateadded': movie['dateadded'],
                        'source': movie['source']
                    })
                    continue
                
                # Check for video files
                video_exts = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
                has_video = any(f.is_file() and f.suffix.lower() in video_exts 
                              for f in movie_path.iterdir() if f.is_file())
                
                if not has_video:
                    # No video files found - delete this movie
                    cursor.execute("""
                        DELETE FROM movies 
                        WHERE imdb_id = %s
                    """, (imdb_id,))
                    
                    deleted_movies.append({
                        'imdb_id': imdb_id,
                        'reason': 'no_video_files',
                        'path': str(movie_path),
                        'dateadded': movie['dateadded'],
                        'source': movie['source']
                    })
            
            conn.commit()
            
        return deleted_movies
    
    def delete_orphaned_series(self) -> List[Dict]:
        """
        Find and delete TV series that don't have corresponding directories on disk
        This requires checking filesystem for each series, so use carefully
        
        Returns:
            List of deleted series with their details
        """
        from pathlib import Path
        
        deleted_series = []
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all series with their paths
            cursor.execute("""
                SELECT imdb_id, path, last_updated, metadata 
                FROM series
            """)
            
            series_list = cursor.fetchall()
            
            for series in series_list:
                imdb_id = series['imdb_id']
                series_path = Path(series['path'])
                
                if not series_path.exists():
                    # Series directory doesn't exist - delete the series and all its episodes
                    cursor.execute("""
                        DELETE FROM episodes 
                        WHERE imdb_id = %s
                    """, (imdb_id,))
                    episodes_deleted = cursor.rowcount
                    
                    cursor.execute("""
                        DELETE FROM series 
                        WHERE imdb_id = %s
                    """, (imdb_id,))
                    
                    deleted_series.append({
                        'imdb_id': imdb_id,
                        'reason': 'directory_not_found',
                        'path': str(series_path),
                        'last_updated': series['last_updated'],
                        'episodes_deleted': episodes_deleted
                    })
            
            conn.commit()
            
        return deleted_series
    
    def add_missing_imdb(self, file_path: str, media_type: str, folder_name: str = None, filename: str = None, notes: str = None):
        """Add or update a missing IMDb entry"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO missing_imdb (file_path, media_type, folder_name, filename, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (file_path) DO UPDATE SET
                    last_checked = CURRENT_TIMESTAMP,
                    check_count = missing_imdb.check_count + 1,
                    media_type = EXCLUDED.media_type,
                    folder_name = EXCLUDED.folder_name,
                    filename = EXCLUDED.filename,
                    notes = EXCLUDED.notes
            """, (file_path, media_type, folder_name, filename, notes))
            
            conn.commit()
    
    def get_missing_imdb_items(self, media_type: str = None, resolved: bool = False) -> List[Dict]:
        """Get missing IMDb items, optionally filtered by type and resolution status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT id, file_path, media_type, folder_name, filename, 
                       discovered_at, last_checked, check_count, notes,
                       resolved, resolved_at, resolved_imdb_id
                FROM missing_imdb
                WHERE resolved = %s
            """
            params = [resolved]
            
            if media_type:
                query += " AND media_type = %s"
                params.append(media_type)
                
            query += " ORDER BY last_checked DESC"
            
            cursor.execute(query, params)
            return cursor.fetchall()
    
    def resolve_missing_imdb(self, file_path: str, imdb_id: str):
        """Mark a missing IMDb item as resolved"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE missing_imdb 
                SET resolved = TRUE, 
                    resolved_at = CURRENT_TIMESTAMP,
                    resolved_imdb_id = %s
                WHERE file_path = %s
            """, (imdb_id, file_path))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_missing_imdb(self, file_path: str) -> bool:
        """Delete a missing IMDb entry"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM missing_imdb WHERE file_path = %s", (file_path,))
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count > 0
    
    # Scheduled Scans Methods
    
    def create_scheduled_scan(self, name: str, description: str, cron_expression: str, 
                             media_type: str, scan_mode: str, specific_paths: str = None,
                             enabled: bool = True, created_by: str = None) -> int:
        """Create a new scheduled scan"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO scheduled_scans 
                (name, description, cron_expression, media_type, scan_mode, specific_paths, enabled, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, description, cron_expression, media_type, scan_mode, specific_paths, enabled, created_by))
            
            return cursor.fetchone()['id']
    
    def get_scheduled_scans(self, enabled_only: bool = False) -> List[Dict]:
        """Get all scheduled scans"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM scheduled_scans"
            if enabled_only:
                query += " WHERE enabled = TRUE"
            query += " ORDER BY name"
            
            cursor.execute(query)
            return cursor.fetchall()
    
    def get_scheduled_scan(self, scan_id: int) -> Optional[Dict]:
        """Get a specific scheduled scan by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM scheduled_scans WHERE id = %s", (scan_id,))
            return cursor.fetchone()
    
    def update_scheduled_scan(self, scan_id: int, name: str = None, description: str = None,
                             cron_expression: str = None, media_type: str = None, 
                             scan_mode: str = None, specific_paths: str = None,
                             enabled: bool = None, updated_by: str = None) -> bool:
        """Update a scheduled scan"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = %s")
                params.append(name)
            if description is not None:
                updates.append("description = %s")
                params.append(description)
            if cron_expression is not None:
                updates.append("cron_expression = %s")
                params.append(cron_expression)
            if media_type is not None:
                updates.append("media_type = %s")
                params.append(media_type)
            if scan_mode is not None:
                updates.append("scan_mode = %s")
                params.append(scan_mode)
            if specific_paths is not None:
                updates.append("specific_paths = %s")
                params.append(specific_paths)
            if enabled is not None:
                updates.append("enabled = %s")
                params.append(enabled)
            if updated_by is not None:
                updates.append("updated_by = %s")
                params.append(updated_by)
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(scan_id)
            
            if not updates:
                return False
                
            query = f"UPDATE scheduled_scans SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)
            
            return cursor.rowcount > 0
    
    def delete_scheduled_scan(self, scan_id: int) -> bool:
        """Delete a scheduled scan and its execution history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM scheduled_scans WHERE id = %s", (scan_id,))
            return cursor.rowcount > 0
    
    def update_scan_next_run(self, scan_id: int, next_run_at: datetime) -> bool:
        """Update the next run time for a scheduled scan"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE scheduled_scans 
                SET next_run_at = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (next_run_at, scan_id))
            
            return cursor.rowcount > 0
    
    def update_scan_last_run(self, scan_id: int, last_run_at: datetime = None) -> bool:
        """Update the last run time and increment run count for a scheduled scan"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if last_run_at is None:
                last_run_at = datetime.utcnow()
            
            cursor.execute("""
                UPDATE scheduled_scans 
                SET last_run_at = %s, run_count = run_count + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (last_run_at, scan_id))
            
            return cursor.rowcount > 0
    
    # Schedule Execution Methods
    
    def create_schedule_execution(self, schedule_id: int, media_type: str, scan_mode: str,
                                 triggered_by: str = None) -> int:
        """Create a new schedule execution record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO schedule_executions 
                (schedule_id, status, media_type, scan_mode, triggered_by)
                VALUES (%s, 'running', %s, %s, %s)
                RETURNING id
            """, (schedule_id, media_type, scan_mode, triggered_by))
            
            return cursor.fetchone()['id']
    
    def update_schedule_execution(self, execution_id: int, status: str = None,
                                 items_processed: int = None, items_skipped: int = None,
                                 items_failed: int = None, error_message: str = None,
                                 logs: str = None) -> bool:
        """Update a schedule execution record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if status is not None:
                updates.append("status = %s")
                params.append(status)
                if status in ['completed', 'failed', 'cancelled']:
                    updates.append("completed_at = CURRENT_TIMESTAMP")
                    updates.append("execution_time_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at))")
            
            if items_processed is not None:
                updates.append("items_processed = %s")
                params.append(items_processed)
            if items_skipped is not None:
                updates.append("items_skipped = %s")
                params.append(items_skipped)
            if items_failed is not None:
                updates.append("items_failed = %s")
                params.append(items_failed)
            if error_message is not None:
                updates.append("error_message = %s")
                params.append(error_message)
            if logs is not None:
                updates.append("logs = %s")
                params.append(logs)
            
            if not updates:
                return False
                
            params.append(execution_id)
            query = f"UPDATE schedule_executions SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)
            
            return cursor.rowcount > 0
    
    def get_schedule_executions(self, schedule_id: int = None, limit: int = 50) -> List[Dict]:
        """Get schedule execution history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT se.*, ss.name as schedule_name
                FROM schedule_executions se
                JOIN scheduled_scans ss ON se.schedule_id = ss.id
            """
            params = []
            
            if schedule_id is not None:
                query += " WHERE se.schedule_id = %s"
                params.append(schedule_id)
            
            query += " ORDER BY se.started_at DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            return cursor.fetchall()
    
    def get_running_executions(self) -> List[Dict]:
        """Get currently running schedule executions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT se.*, ss.name as schedule_name
                FROM schedule_executions se
                JOIN scheduled_scans ss ON se.schedule_id = ss.id
                WHERE se.status = 'running'
                ORDER BY se.started_at DESC
            """)
            
            return cursor.fetchall()
    
    def close(self):
        """Close all database connections"""
        if hasattr(self._local, 'connection'):
            try:
                # For PostgreSQL, ensure all transactions are committed/rolled back
                try:
                    # Force rollback any open transactions
                    self._local.connection.rollback()
                except Exception:
                    pass
                
                # Close the connection
                self._local.connection.close()
                delattr(self._local, 'connection')
                print("✅ Database connection closed successfully")
            except Exception as e:
                print(f"⚠️ Error closing database connection: {e}")
                pass  # Connection may already be closed