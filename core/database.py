#!/usr/bin/env python3
"""
PostgreSQL database management for Chronarr
Handles database operations for tracking media dates and processing history
"""
import json
import os
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

class ChronarrDatabase:
    """PostgreSQL database manager for Chronarr media tracking and processing history"""
    
    def __init__(self, config):
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
        """Get thread-local PostgreSQL database connection, reconnecting if closed"""
        conn = getattr(self._local, 'connection', None)
        if conn is None or conn.closed:
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
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # Connection died mid-use — discard it so the next caller reconnects
            if hasattr(self._local, 'connection'):
                try:
                    self._local.connection.close()
                except Exception:
                    pass
                delattr(self._local, 'connection')
            raise
    
    def _init_database(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            self._init_postgresql_tables(cursor)
    
    def _init_postgresql_tables(self, cursor):
        # Series — instance is part of the PK so two different Sonarr instances
        # can track the same show independently.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS series (
                imdb_id VARCHAR(20) NOT NULL,
                instance VARCHAR(100) NOT NULL DEFAULT 'sonarr',
                path TEXT NOT NULL,
                last_updated TIMESTAMP NOT NULL,
                metadata JSONB,
                missing_from_source_since TIMESTAMP DEFAULT NULL,
                PRIMARY KEY (imdb_id, instance)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                imdb_id VARCHAR(20) NOT NULL,
                instance VARCHAR(100) NOT NULL DEFAULT 'sonarr',
                season INTEGER NOT NULL,
                episode INTEGER NOT NULL,
                aired DATE,
                dateadded TIMESTAMP,
                source VARCHAR(100),
                last_updated TIMESTAMP NOT NULL,
                has_video_file BOOLEAN DEFAULT FALSE,
                skipped BOOLEAN DEFAULT FALSE,
                skip_reason TEXT,
                PRIMARY KEY (imdb_id, season, episode, instance),
                FOREIGN KEY (imdb_id, instance) REFERENCES series(imdb_id, instance)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                imdb_id VARCHAR(20) NOT NULL,
                instance VARCHAR(100) NOT NULL DEFAULT 'radarr',
                title TEXT,
                year INTEGER,
                path TEXT NOT NULL DEFAULT 'unknown',
                released DATE,
                dateadded TIMESTAMP,
                source VARCHAR(100),
                last_updated TIMESTAMP NOT NULL,
                has_video_file BOOLEAN DEFAULT FALSE,
                skipped BOOLEAN DEFAULT FALSE,
                skip_reason TEXT,
                missing_from_source_since TIMESTAMP DEFAULT NULL,
                PRIMARY KEY (imdb_id, instance)
            )
        """)

        # Migrate existing single-instance databases to the composite-PK schema.
        # Runs only when the instance column is absent (first upgrade to v3).
        cursor.execute("""
            DO $$
            BEGIN
                -- Series: drop the old FK from episodes before touching the series PK.
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='series' AND column_name='instance') THEN
                    ALTER TABLE episodes DROP CONSTRAINT IF EXISTS episodes_imdb_id_fkey;
                    ALTER TABLE series ADD COLUMN instance VARCHAR(100) NOT NULL DEFAULT 'sonarr';
                    ALTER TABLE series ADD COLUMN IF NOT EXISTS missing_from_source_since TIMESTAMP DEFAULT NULL;
                    ALTER TABLE series DROP CONSTRAINT series_pkey;
                    ALTER TABLE series ADD PRIMARY KEY (imdb_id, instance);
                END IF;

                -- Movies: independent of series.
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='movies' AND column_name='instance') THEN
                    ALTER TABLE movies ADD COLUMN instance VARCHAR(100) NOT NULL DEFAULT 'radarr';
                    ALTER TABLE movies ADD COLUMN IF NOT EXISTS title TEXT;
                    ALTER TABLE movies ADD COLUMN IF NOT EXISTS year INTEGER;
                    ALTER TABLE movies ADD COLUMN IF NOT EXISTS skipped BOOLEAN DEFAULT FALSE;
                    ALTER TABLE movies ADD COLUMN IF NOT EXISTS skip_reason TEXT;
                    ALTER TABLE movies ADD COLUMN IF NOT EXISTS missing_from_source_since TIMESTAMP DEFAULT NULL;
                    ALTER TABLE movies DROP CONSTRAINT movies_pkey;
                    ALTER TABLE movies ADD PRIMARY KEY (imdb_id, instance);
                END IF;

                -- Episodes: needs series to have its composite PK in place first.
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='episodes' AND column_name='instance') THEN
                    ALTER TABLE episodes ADD COLUMN instance VARCHAR(100) NOT NULL DEFAULT 'sonarr';
                    ALTER TABLE episodes ADD COLUMN IF NOT EXISTS skipped BOOLEAN DEFAULT FALSE;
                    ALTER TABLE episodes ADD COLUMN IF NOT EXISTS skip_reason TEXT;
                    ALTER TABLE episodes DROP CONSTRAINT episodes_pkey;
                    ALTER TABLE episodes ADD PRIMARY KEY (imdb_id, season, episode, instance);
                    ALTER TABLE episodes ADD CONSTRAINT episodes_series_fk
                        FOREIGN KEY (imdb_id, instance) REFERENCES series(imdb_id, instance);
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

        # Scheduled cleanups table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_cleanups (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                cron_expression VARCHAR(100) NOT NULL,
                check_movies BOOLEAN DEFAULT TRUE,
                check_series BOOLEAN DEFAULT TRUE,
                check_filesystem BOOLEAN DEFAULT TRUE,
                check_database BOOLEAN DEFAULT TRUE,
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

        # Cleanup execution history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cleanup_executions (
                id SERIAL PRIMARY KEY,
                schedule_id INTEGER,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(50) NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
                movies_removed INTEGER DEFAULT 0,
                series_removed INTEGER DEFAULT 0,
                episodes_removed INTEGER DEFAULT 0,
                execution_time_seconds INTEGER,
                error_message TEXT,
                report_json TEXT,
                triggered_by VARCHAR(100),
                FOREIGN KEY (schedule_id) REFERENCES scheduled_cleanups(id) ON DELETE SET NULL
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_cleanups_enabled ON scheduled_cleanups(enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_cleanups_next_run ON scheduled_cleanups(next_run_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cleanup_executions_schedule ON cleanup_executions(schedule_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cleanup_executions_status ON cleanup_executions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cleanup_executions_started ON cleanup_executions(started_at)")
    def upsert_series(self, imdb_id: str, path: str, instance: str = 'sonarr', metadata: Optional[Dict] = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO series (imdb_id, instance, path, last_updated, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (imdb_id, instance) DO UPDATE SET
                    path = EXCLUDED.path,
                    last_updated = EXCLUDED.last_updated,
                    metadata = EXCLUDED.metadata
            """, (imdb_id, instance, path, timestamp, json.dumps(metadata) if metadata else None))
    
    def upsert_episode_date(self, imdb_id: str, season: int, episode: int,
                           aired: Optional[str], dateadded: Optional[str],
                           source: str, has_video_file: bool = False, instance: str = 'sonarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO episodes
                (imdb_id, instance, season, episode, aired, dateadded, source, has_video_file, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (imdb_id, season, episode, instance) DO UPDATE SET
                    aired = COALESCE(EXCLUDED.aired, episodes.aired),
                    dateadded = COALESCE(EXCLUDED.dateadded, episodes.dateadded),
                    source = COALESCE(EXCLUDED.source, episodes.source),
                    has_video_file = EXCLUDED.has_video_file,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, instance, season, episode, aired, dateadded, source, has_video_file, timestamp))
    
    def upsert_movie(self, imdb_id: str, path: str, instance: str = 'radarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO movies (imdb_id, instance, path, last_updated)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (imdb_id, instance) DO UPDATE SET
                    path = EXCLUDED.path,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, instance, path, timestamp))
    
    def upsert_movie_dates(self, imdb_id: str, released: Optional[str],
                          dateadded: Optional[str], source: str, has_video_file: bool = False,
                          title: Optional[str] = None, year: Optional[int] = None,
                          instance: str = 'radarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO movies (imdb_id, instance, title, year, path, released, dateadded, source, has_video_file, last_updated)
                VALUES (%s, %s, %s, %s,
                        COALESCE((SELECT path FROM movies WHERE imdb_id = %s AND instance = %s), 'unknown'),
                        %s, %s, %s, %s, %s)
                ON CONFLICT (imdb_id, instance) DO UPDATE SET
                    title = COALESCE(EXCLUDED.title, movies.title),
                    year = COALESCE(EXCLUDED.year, movies.year),
                    released = COALESCE(EXCLUDED.released, movies.released),
                    dateadded = COALESCE(EXCLUDED.dateadded, movies.dateadded),
                    source = COALESCE(EXCLUDED.source, movies.source),
                    has_video_file = EXCLUDED.has_video_file,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, instance, title, year, imdb_id, instance, released, dateadded, source, has_video_file, timestamp))

    def mark_movie_skipped(self, imdb_id: str, title: str, year: int, path: str, reason: str, instance: str = 'radarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO movies (imdb_id, instance, title, year, path, skipped, skip_reason, has_video_file, last_updated)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s, FALSE, %s)
                ON CONFLICT (imdb_id, instance) DO UPDATE SET
                    title = EXCLUDED.title,
                    year = EXCLUDED.year,
                    path = EXCLUDED.path,
                    skipped = TRUE,
                    skip_reason = EXCLUDED.skip_reason,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, instance, title, year, path, reason, timestamp))

    def mark_episode_skipped(self, imdb_id: str, season: int, episode: int, reason: str, instance: str = 'sonarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp = datetime.utcnow()
            cursor.execute("""
                INSERT INTO episodes (imdb_id, instance, season, episode, skipped, skip_reason, has_video_file, last_updated)
                VALUES (%s, %s, %s, %s, TRUE, %s, FALSE, %s)
                ON CONFLICT (imdb_id, season, episode, instance) DO UPDATE SET
                    skipped = TRUE,
                    skip_reason = EXCLUDED.skip_reason,
                    last_updated = EXCLUDED.last_updated
            """, (imdb_id, instance, season, episode, reason, timestamp))

    def clear_movie_skipped(self, imdb_id: str, instance: str = 'radarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE movies SET skipped = FALSE, skip_reason = NULL
                WHERE imdb_id = %s AND instance = %s
            """, (imdb_id, instance))

    def clear_episode_skipped(self, imdb_id: str, season: int, episode: int, instance: str = 'sonarr'):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE episodes SET skipped = FALSE, skip_reason = NULL
                WHERE imdb_id = %s AND season = %s AND episode = %s AND instance = %s
            """, (imdb_id, season, episode, instance))

    def get_skipped_counts(self) -> Dict:
        """Total skipped counts across all instances — for dashboard summary."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM movies WHERE skipped = TRUE")
            skipped_movies = cursor.fetchone()['count']
            cursor.execute("SELECT COUNT(*) as count FROM episodes WHERE skipped = TRUE")
            skipped_episodes = cursor.fetchone()['count']
            return {
                'movies': skipped_movies,
                'episodes': skipped_episodes,
                'total': skipped_movies + skipped_episodes
            }

    def get_series_episodes(self, imdb_id: str, instance: str = 'sonarr', has_video_file_only: bool = False) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM episodes WHERE imdb_id = %s AND instance = %s"
            params = [imdb_id, instance]
            if has_video_file_only:
                query += " AND has_video_file = TRUE"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_episode_date(self, imdb_id: str, season: int, episode: int, instance: str = 'sonarr') -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM episodes
                WHERE imdb_id = %s AND season = %s AND episode = %s AND instance = %s
            """, (imdb_id, season, episode, instance))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_movie_dates(self, imdb_id: str, instance: str = 'radarr') -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", (imdb_id, instance))
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
    
    def migrate_movie_imdb_id(self, old_imdb_id: str, new_imdb_id: str, instance: str = 'radarr') -> bool:
        """Replace a placeholder IMDb ID with the real one, preserving all other data."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", (old_imdb_id, instance))
            old_record = cursor.fetchone()
            if not old_record:
                return False

            old_data = dict(old_record)

            cursor.execute("SELECT * FROM movies WHERE imdb_id = %s AND instance = %s", (new_imdb_id, instance))
            if cursor.fetchone():
                cursor.execute("DELETE FROM movies WHERE imdb_id = %s AND instance = %s", (old_imdb_id, instance))
                return True

            cursor.execute("""
                INSERT INTO movies (imdb_id, instance, title, year, path, released, dateadded, source,
                                   has_video_file, last_updated, skipped, skip_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NULL)
            """, (new_imdb_id, instance, old_data.get('title'), old_data.get('year'),
                  old_data.get('path'), old_data.get('released'), old_data.get('dateadded'),
                  old_data.get('source'), old_data.get('has_video_file'), datetime.utcnow()))

            cursor.execute("DELETE FROM movies WHERE imdb_id = %s AND instance = %s", (old_imdb_id, instance))
            return True

    def migrate_series_imdb_id(self, old_imdb_id: str, new_imdb_id: str, instance: str = 'sonarr') -> bool:
        """Replace a placeholder series IMDb ID with the real one, migrating all episodes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM series WHERE imdb_id = %s AND instance = %s", (old_imdb_id, instance))
            old_series = cursor.fetchone()
            if not old_series:
                return False

            old_series_data = dict(old_series)

            cursor.execute("SELECT * FROM series WHERE imdb_id = %s AND instance = %s", (new_imdb_id, instance))
            if cursor.fetchone():
                cursor.execute("UPDATE episodes SET imdb_id = %s WHERE imdb_id = %s AND instance = %s",
                               (new_imdb_id, old_imdb_id, instance))
                cursor.execute("DELETE FROM series WHERE imdb_id = %s AND instance = %s", (old_imdb_id, instance))
                return True

            cursor.execute("""
                INSERT INTO series (imdb_id, instance, path, last_updated, metadata)
                VALUES (%s, %s, %s, %s, %s)
            """, (new_imdb_id, instance, old_series_data.get('path'),
                  datetime.utcnow(), old_series_data.get('metadata')))

            cursor.execute("""
                UPDATE episodes SET imdb_id = %s, skipped = FALSE, skip_reason = NULL
                WHERE imdb_id = %s AND instance = %s
            """, (new_imdb_id, old_imdb_id, instance))

            cursor.execute("DELETE FROM series WHERE imdb_id = %s AND instance = %s", (old_imdb_id, instance))
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
    
    def delete_episode(self, imdb_id: str, season: int, episode: int, instance: str = 'sonarr') -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM episodes
                WHERE imdb_id = %s AND season = %s AND episode = %s AND instance = %s
            """, (imdb_id, season, episode, instance))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count > 0

    def delete_series_episodes(self, imdb_id: str, instance: str = 'sonarr') -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM episodes WHERE imdb_id = %s AND instance = %s", (imdb_id, instance))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
    
    def delete_orphaned_episodes(self) -> List[Dict]:
        """Delete DB episode rows that have no matching file on disk. Checks filesystem."""
        from utils.file_utils import find_episodes_on_disk
        from pathlib import Path
        
        deleted_episodes = []
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT imdb_id, path FROM series")
            series_list = cursor.fetchall()

            for series in series_list:
                imdb_id = series['imdb_id']
                series_path = Path(series['path'])
                if not series_path.exists():
                    continue

                disk_episodes = find_episodes_on_disk(series_path)
                disk_episode_keys = set(disk_episodes.keys())

                cursor.execute(
                    "SELECT season, episode, dateadded, source FROM episodes WHERE imdb_id = %s",
                    (imdb_id,)
                )
                for ep in cursor.fetchall():
                    season, episode = ep['season'], ep['episode']
                    if (season, episode) not in disk_episode_keys:
                        cursor.execute(
                            "DELETE FROM episodes WHERE imdb_id = %s AND season = %s AND episode = %s",
                            (imdb_id, season, episode)
                        )
                        deleted_episodes.append({
                            'imdb_id': imdb_id,
                            'season': season,
                            'episode': episode,
                            'dateadded': ep['dateadded'],
                            'source': ep['source'],
                            'series_path': str(series_path)
                        })

            conn.commit()

        return deleted_episodes
    
    def delete_movie(self, imdb_id: str, instance: str = 'radarr') -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM movies WHERE imdb_id = %s AND instance = %s", (imdb_id, instance))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count > 0

    def delete_series(self, imdb_id: str, instance: str = 'sonarr') -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM series WHERE imdb_id = %s AND instance = %s", (imdb_id, instance))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count > 0

    def update_movie_file_info(self, imdb_id: str, path: str, has_video_file: bool = True) -> bool:
        """Update path and file status — used when a population scan finds a video for a queued movie."""
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
        Update video file status for an existing episode
        Used when population finds a video file for a manually-added episode

        Args:
            imdb_id: Series IMDb ID
            season: Season number
            episode: Episode number
            path: File path (ignored - kept for backward compatibility)
            has_video_file: Whether a video file exists (default True)

        Returns:
            True if episode was updated, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE episodes
                SET has_video_file = %s,
                    last_updated = %s
                WHERE imdb_id = %s AND season = %s AND episode = %s
            """, (has_video_file, datetime.utcnow(), imdb_id, season, episode))

            updated_count = cursor.rowcount
            conn.commit()

            return updated_count > 0

    # ── Library sync helpers ──────────────────────────────────────────────────

    def get_all_movie_records(self) -> List[Dict]:
        """Return all movie records including instance — used by library sync."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT imdb_id, instance, title, path, missing_from_source_since FROM movies"
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_all_series_records(self) -> List[Dict]:
        """Return all series records including instance — used by library sync."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT imdb_id, instance, path, metadata, missing_from_source_since FROM series"
            )
            return [dict(r) for r in cursor.fetchall()]

    def mark_movies_missing_from_source(self, imdb_ids: List[str], timestamp) -> None:
        """Set missing_from_source_since for movies not yet marked."""
        if not imdb_ids:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE movies SET missing_from_source_since = %s
                   WHERE imdb_id = ANY(%s) AND missing_from_source_since IS NULL""",
                (timestamp, imdb_ids)
            )
            conn.commit()

    def mark_series_missing_from_source(self, imdb_ids: List[str], timestamp) -> None:
        """Set missing_from_source_since for series not yet marked."""
        if not imdb_ids:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE series SET missing_from_source_since = %s
                   WHERE imdb_id = ANY(%s) AND missing_from_source_since IS NULL""",
                (timestamp, imdb_ids)
            )
            conn.commit()

    def clear_movies_missing_from_source(self, imdb_ids: List[str]) -> None:
        """Clear missing_from_source_since for movies that returned to Radarr."""
        if not imdb_ids:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE movies SET missing_from_source_since = NULL WHERE imdb_id = ANY(%s)",
                (imdb_ids,)
            )
            conn.commit()

    def clear_series_missing_from_source(self, imdb_ids: List[str]) -> None:
        """Clear missing_from_source_since for series that returned to Sonarr."""
        if not imdb_ids:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE series SET missing_from_source_since = NULL WHERE imdb_id = ANY(%s)",
                (imdb_ids,)
            )
            conn.commit()

    def get_movies_missing_before(self, cutoff) -> List[Dict]:
        """Return movies that have been missing from Radarr since before cutoff."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT imdb_id, title, path, missing_from_source_since
                   FROM movies
                   WHERE missing_from_source_since IS NOT NULL
                     AND missing_from_source_since <= %s""",
                (cutoff,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_series_missing_before(self, cutoff) -> List[Dict]:
        """Return series that have been missing from Sonarr since before cutoff."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT imdb_id, path, metadata, missing_from_source_since
                   FROM series
                   WHERE missing_from_source_since IS NOT NULL
                     AND missing_from_source_since <= %s""",
                (cutoff,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def delete_orphaned_movies(self) -> List[Dict]:
        """Delete DB movie rows whose directory or video files no longer exist on disk."""
        from pathlib import Path

        deleted_movies = []
        video_exts = (".mkv", ".mp4", ".avi", ".mov", ".m4v")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT imdb_id, path, dateadded, source FROM movies")

            for movie in cursor.fetchall():
                imdb_id = movie['imdb_id']
                movie_path = Path(movie['path'])

                if not movie_path.exists():
                    cursor.execute("DELETE FROM movies WHERE imdb_id = %s", (imdb_id,))
                    deleted_movies.append({
                        'imdb_id': imdb_id, 'reason': 'directory_not_found',
                        'path': str(movie_path), 'dateadded': movie['dateadded'],
                        'source': movie['source']
                    })
                    continue

                has_video = any(
                    f.is_file() and f.suffix.lower() in video_exts
                    for f in movie_path.iterdir() if f.is_file()
                )
                if not has_video:
                    cursor.execute("DELETE FROM movies WHERE imdb_id = %s", (imdb_id,))
                    deleted_movies.append({
                        'imdb_id': imdb_id, 'reason': 'no_video_files',
                        'path': str(movie_path), 'dateadded': movie['dateadded'],
                        'source': movie['source']
                    })

            conn.commit()

        return deleted_movies
    
    def delete_orphaned_series(self) -> List[Dict]:
        """Delete DB series (and all their episodes) whose directory no longer exists on disk."""
        from pathlib import Path

        deleted_series = []

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT imdb_id, path, last_updated, metadata FROM series")

            for series in cursor.fetchall():
                imdb_id = series['imdb_id']
                series_path = Path(series['path'])

                if not series_path.exists():
                    cursor.execute("DELETE FROM episodes WHERE imdb_id = %s", (imdb_id,))
                    episodes_deleted = cursor.rowcount
                    cursor.execute("DELETE FROM series WHERE imdb_id = %s", (imdb_id,))
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

    # Scheduled Cleanup Methods

    def create_scheduled_cleanup(self, name: str, description: str, cron_expression: str,
                                 check_movies: bool = True, check_series: bool = True,
                                 check_filesystem: bool = True, check_database: bool = True,
                                 enabled: bool = True, created_by: str = None) -> int:
        """Create a new scheduled cleanup"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO scheduled_cleanups
                (name, description, cron_expression, check_movies, check_series,
                 check_filesystem, check_database, enabled, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, description, cron_expression, check_movies, check_series,
                  check_filesystem, check_database, enabled, created_by))

            return cursor.fetchone()['id']

    def get_scheduled_cleanups(self, enabled_only: bool = False) -> List[Dict]:
        """Get all scheduled cleanups"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM scheduled_cleanups"
            if enabled_only:
                query += " WHERE enabled = TRUE"
            query += " ORDER BY name"

            cursor.execute(query)
            return cursor.fetchall()

    def get_scheduled_cleanup(self, cleanup_id: int) -> Optional[Dict]:
        """Get a specific scheduled cleanup by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM scheduled_cleanups WHERE id = %s", (cleanup_id,))
            return cursor.fetchone()

    def update_scheduled_cleanup(self, cleanup_id: int, name: str = None, description: str = None,
                                 cron_expression: str = None, check_movies: bool = None,
                                 check_series: bool = None, check_filesystem: bool = None,
                                 check_database: bool = None, enabled: bool = None,
                                 updated_by: str = None) -> bool:
        """Update a scheduled cleanup"""
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
            if check_movies is not None:
                updates.append("check_movies = %s")
                params.append(check_movies)
            if check_series is not None:
                updates.append("check_series = %s")
                params.append(check_series)
            if check_filesystem is not None:
                updates.append("check_filesystem = %s")
                params.append(check_filesystem)
            if check_database is not None:
                updates.append("check_database = %s")
                params.append(check_database)
            if enabled is not None:
                updates.append("enabled = %s")
                params.append(enabled)
            if updated_by is not None:
                updates.append("updated_by = %s")
                params.append(updated_by)

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(cleanup_id)

            if not updates:
                return False

            query = f"UPDATE scheduled_cleanups SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)

            return cursor.rowcount > 0

    def delete_scheduled_cleanup(self, cleanup_id: int) -> bool:
        """Delete a scheduled cleanup and its execution history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM scheduled_cleanups WHERE id = %s", (cleanup_id,))
            return cursor.rowcount > 0

    def update_cleanup_next_run(self, cleanup_id: int, next_run_at: datetime) -> bool:
        """Update the next run time for a scheduled cleanup"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE scheduled_cleanups
                SET next_run_at = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (next_run_at, cleanup_id))

            return cursor.rowcount > 0

    def update_cleanup_last_run(self, cleanup_id: int, last_run_at: datetime = None) -> bool:
        """Update the last run time and increment run count for a scheduled cleanup"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if last_run_at is None:
                last_run_at = datetime.utcnow()

            cursor.execute("""
                UPDATE scheduled_cleanups
                SET last_run_at = %s, run_count = run_count + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (last_run_at, cleanup_id))

            return cursor.rowcount > 0

    # Cleanup Execution Methods

    def create_cleanup_execution(self, schedule_id: int = None, triggered_by: str = None) -> int:
        """Create a new cleanup execution record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO cleanup_executions
                (schedule_id, status, triggered_by)
                VALUES (%s, 'running', %s)
                RETURNING id
            """, (schedule_id, triggered_by))

            return cursor.fetchone()['id']

    def update_cleanup_execution(self, execution_id: int, status: str = None,
                                 movies_removed: int = None, series_removed: int = None,
                                 episodes_removed: int = None, error_message: str = None,
                                 report_json: str = None) -> bool:
        """Update a cleanup execution record"""
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

            if movies_removed is not None:
                updates.append("movies_removed = %s")
                params.append(movies_removed)
            if series_removed is not None:
                updates.append("series_removed = %s")
                params.append(series_removed)
            if episodes_removed is not None:
                updates.append("episodes_removed = %s")
                params.append(episodes_removed)
            if error_message is not None:
                updates.append("error_message = %s")
                params.append(error_message)
            if report_json is not None:
                updates.append("report_json = %s")
                params.append(report_json)

            if not updates:
                return False

            params.append(execution_id)
            query = f"UPDATE cleanup_executions SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)

            return cursor.rowcount > 0

    def get_cleanup_executions(self, schedule_id: int = None, limit: int = 50) -> List[Dict]:
        """Get cleanup execution history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT ce.*, sc.name as schedule_name
                FROM cleanup_executions ce
                LEFT JOIN scheduled_cleanups sc ON ce.schedule_id = sc.id
            """
            params = []

            if schedule_id is not None:
                query += " WHERE ce.schedule_id = %s"
                params.append(schedule_id)

            query += " ORDER BY ce.started_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)
            return cursor.fetchall()

    def get_running_cleanup_executions(self) -> List[Dict]:
        """Get currently running cleanup executions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ce.*, sc.name as schedule_name
                FROM cleanup_executions ce
                LEFT JOIN scheduled_cleanups sc ON ce.schedule_id = sc.id
                WHERE ce.status = 'running'
                ORDER BY ce.started_at DESC
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