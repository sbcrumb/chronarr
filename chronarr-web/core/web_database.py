"""
Chronarr Web Database - Lightweight Read-Only Database Access
Optimized for web interface queries with minimal dependencies
"""
import psycopg2
import psycopg2.extras
from typing import Dict, List, Optional, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class WebDatabase:
    """Lightweight database access for web interface"""
    
    def __init__(self, db_type: str, host: str, port: int, database: str, user: str, password: str):
        self.db_type = db_type.lower()
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.connection = None
        
        # Connect to database
        self._connect()
    
    def _connect(self):
        """Connect to PostgreSQL database"""
        if self.db_type != "postgresql":
            raise ValueError("Web interface only supports PostgreSQL")
        
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
            # Set to autocommit for read operations
            self.connection.autocommit = True
            logger.info(f"Connected to PostgreSQL: {self.host}:{self.port}/{self.database}")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def execute_query(self, query: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Query failed: {query[:100]}... Error: {e}")
            raise
    
    def execute_single(self, query: str, params: Optional[Tuple] = None) -> Optional[Dict[str, Any]]:
        """Execute a query and return single result"""
        results = self.execute_query(query, params)
        return results[0] if results else None
    
    def execute_scalar(self, query: str, params: Optional[Tuple] = None) -> Any:
        """Execute a query and return single value"""
        result = self.execute_single(query, params)
        return list(result.values())[0] if result else None
    
    # Dashboard Statistics
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        stats = {}
        
        # Movie statistics
        movie_query = """
            SELECT 
                COUNT(*) as total_movies,
                COUNT(CASE WHEN dateadded IS NOT NULL AND source != 'unknown' THEN 1 END) as movies_with_dates,
                COUNT(CASE WHEN dateadded IS NULL OR source = 'unknown' THEN 1 END) as movies_without_dates
            FROM movies
        """
        movie_stats = self.execute_single(movie_query)
        stats.update(movie_stats)
        
        # TV statistics
        tv_query = """
            SELECT 
                COUNT(DISTINCT imdb_id) as total_series,
                COUNT(*) as total_episodes,
                COUNT(CASE WHEN dateadded IS NOT NULL AND source != 'unknown' THEN 1 END) as episodes_with_dates,
                COUNT(CASE WHEN dateadded IS NULL OR source = 'unknown' THEN 1 END) as episodes_without_dates
            FROM episodes
        """
        tv_stats = self.execute_single(tv_query)
        stats.update(tv_stats)
        
        return stats
    
    # Movie queries
    def get_movies(self, skip: int = 0, limit: int = 50, has_date: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Get movies with pagination"""
        where_clause = ""
        params = []
        
        if has_date is not None:
            if has_date:
                where_clause = "WHERE dateadded IS NOT NULL AND source != 'unknown'"
            else:
                where_clause = "WHERE dateadded IS NULL OR source = 'unknown'"
        
        query = f"""
            SELECT imdb_id, title, year, dateadded, released, source, last_updated
            FROM movies
            {where_clause}
            ORDER BY title, year
            LIMIT %s OFFSET %s
        """
        params.extend([limit, skip])
        
        return self.execute_query(query, params)
    
    def get_movie_count(self, has_date: Optional[bool] = None) -> int:
        """Get total movie count"""
        where_clause = ""
        params = []
        
        if has_date is not None:
            if has_date:
                where_clause = "WHERE dateadded IS NOT NULL AND source != 'unknown'"
            else:
                where_clause = "WHERE dateadded IS NULL OR source = 'unknown'"
        
        query = f"SELECT COUNT(*) FROM movies {where_clause}"
        return self.execute_scalar(query, params)
    
    # TV Series queries
    def get_series(self, skip: int = 0, limit: int = 50, date_filter: str = "none") -> List[Dict[str, Any]]:
        """Get TV series with episode statistics"""
        where_clause = ""
        if date_filter == "complete":
            where_clause = """
                WHERE NOT EXISTS (
                    SELECT 1 FROM episodes e2 
                    WHERE e2.imdb_id = e.imdb_id 
                    AND (e2.dateadded IS NULL OR e2.source = 'unknown')
                )
            """
        elif date_filter == "incomplete":
            where_clause = """
                WHERE EXISTS (
                    SELECT 1 FROM episodes e2 
                    WHERE e2.imdb_id = e.imdb_id 
                    AND (e2.dateadded IS NULL OR e2.source = 'unknown')
                )
            """
        
        query = f"""
            SELECT 
                e.imdb_id,
                e.series_title,
                COUNT(*) as total_episodes,
                COUNT(CASE WHEN e.dateadded IS NOT NULL AND e.source != 'unknown' THEN 1 END) as episodes_with_dates,
                COUNT(CASE WHEN e.dateadded IS NULL OR e.source = 'unknown' THEN 1 END) as episodes_without_dates,
                MAX(e.last_updated) as last_updated
            FROM episodes e
            {where_clause}
            GROUP BY e.imdb_id, e.series_title
            ORDER BY e.series_title
            LIMIT %s OFFSET %s
        """
        
        return self.execute_query(query, [limit, skip])
    
    def get_series_count(self, date_filter: str = "none") -> int:
        """Get total series count"""
        where_clause = ""
        if date_filter == "complete":
            where_clause = """
                WHERE NOT EXISTS (
                    SELECT 1 FROM episodes e2 
                    WHERE e2.imdb_id = e.imdb_id 
                    AND (e2.dateadded IS NULL OR e2.source = 'unknown')
                )
            """
        elif date_filter == "incomplete":
            where_clause = """
                WHERE EXISTS (
                    SELECT 1 FROM episodes e2 
                    WHERE e2.imdb_id = e.imdb_id 
                    AND (e2.dateadded IS NULL OR e2.source = 'unknown')
                )
            """
        
        query = f"""
            SELECT COUNT(DISTINCT imdb_id)
            FROM episodes e
            {where_clause}
        """
        
        return self.execute_scalar(query)
    
    def get_episodes_for_series(self, imdb_id: str) -> List[Dict[str, Any]]:
        """Get all episodes for a series"""
        query = """
            SELECT imdb_id, series_title, season, episode, episode_title, 
                   dateadded, source, last_updated
            FROM episodes
            WHERE imdb_id = %s
            ORDER BY season, episode
        """
        return self.execute_query(query, [imdb_id])
    
    # Source statistics
    def get_series_sources(self) -> List[Dict[str, Any]]:
        """Get source statistics for series"""
        query = """
            SELECT 
                source,
                COUNT(DISTINCT imdb_id) as series_count,
                COUNT(*) as episode_count
            FROM episodes
            WHERE source != 'unknown'
            GROUP BY source
            ORDER BY series_count DESC, episode_count DESC
        """
        return self.execute_query(query)
    
    # Episode-specific methods for web interface
    def get_episode_date(self, imdb_id: str, season: int, episode: int) -> Optional[Dict]:
        """Get episode data including dates"""
        query = """
            SELECT imdb_id, season, episode, aired, dateadded, source, has_video_file, last_updated
            FROM episodes 
            WHERE imdb_id = %s AND season = %s AND episode = %s
        """
        return self.execute_single(query, (imdb_id, season, episode))
    
    def upsert_episode_date(self, imdb_id: str, season: int, episode: int, 
                           aired: Optional[str], dateadded: Optional[str], 
                           source: str, has_video_file: bool = False) -> None:
        """Update or insert episode date information"""
        # First check if episode exists
        existing = self.get_episode_date(imdb_id, season, episode)
        
        # Temporarily disable autocommit for the transaction
        original_autocommit = self.connection.autocommit
        self.connection.autocommit = False
        
        try:
            with self.connection.cursor() as cursor:
                if existing:
                    # Update existing episode
                    query = """
                        UPDATE episodes 
                        SET aired = %s, dateadded = %s, source = %s, has_video_file = %s, last_updated = NOW()
                        WHERE imdb_id = %s AND season = %s AND episode = %s
                    """
                    cursor.execute(query, (aired, dateadded, source, has_video_file, imdb_id, season, episode))
                else:
                    # Insert new episode
                    query = """
                        INSERT INTO episodes (imdb_id, season, episode, aired, dateadded, source, has_video_file, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    """
                    cursor.execute(query, (imdb_id, season, episode, aired, dateadded, source, has_video_file))
                
                self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Failed to upsert episode date: {e}")
            raise
        finally:
            # Restore original autocommit setting
            self.connection.autocommit = original_autocommit
    
    def get_movie_dates(self, imdb_id: str) -> Optional[Dict]:
        """Get movie data including dates"""
        query = """
            SELECT imdb_id, path, released, dateadded, source, has_video_file, last_updated
            FROM movies 
            WHERE imdb_id = %s
        """
        return self.execute_single(query, (imdb_id,))
    
    def upsert_movie_dates(self, imdb_id: str, released: Optional[str], 
                          dateadded: Optional[str], source: str, 
                          has_video_file: bool = False, path: str = "") -> None:
        """Update or insert movie date information"""
        # First check if movie exists
        existing = self.get_movie_dates(imdb_id)
        
        # Temporarily disable autocommit for the transaction
        original_autocommit = self.connection.autocommit
        self.connection.autocommit = False
        
        try:
            with self.connection.cursor() as cursor:
                if existing:
                    # Update existing movie
                    query = """
                        UPDATE movies 
                        SET released = %s, dateadded = %s, source = %s, has_video_file = %s, last_updated = NOW()
                        WHERE imdb_id = %s
                    """
                    cursor.execute(query, (released, dateadded, source, has_video_file, imdb_id))
                else:
                    # Insert new movie
                    query = """
                        INSERT INTO movies (imdb_id, path, released, dateadded, source, has_video_file, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """
                    cursor.execute(query, (imdb_id, path, released, dateadded, source, has_video_file))
                
                self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Failed to upsert movie dates: {e}")
            raise
        finally:
            # Restore original autocommit setting
            self.connection.autocommit = original_autocommit
    
    def get_connection(self):
        """Get database connection for advanced operations"""
        return self.connection
    
    def _get_first_value(self, row):
        """Extract first value from a database row (compatibility method)"""
        if row is None:
            return None
        if isinstance(row, dict):
            return list(row.values())[0] if row else None
        return row[0] if row else None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get basic database statistics (compatibility method)"""
        return self.get_dashboard_stats()
    
    def add_processing_history(self, imdb_id: str, media_type: str, event_type: str, details: Dict) -> None:
        """Add processing history entry (simplified for web interface)"""
        # Temporarily disable autocommit for the transaction
        original_autocommit = self.connection.autocommit
        self.connection.autocommit = False
        
        try:
            with self.connection.cursor() as cursor:
                # Check if processing_history table exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'processing_history'
                    )
                """)
                table_exists = cursor.fetchone()[0]
                
                if table_exists:
                    query = """
                        INSERT INTO processing_history (imdb_id, media_type, event_type, details, processed_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """
                    import json
                    cursor.execute(query, (imdb_id, media_type, event_type, json.dumps(details)))
                    self.connection.commit()
                else:
                    # Table doesn't exist, skip logging
                    logger.debug("Processing history table not found, skipping log entry")
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Failed to add processing history: {e}")
            # Don't raise, this is non-critical
        finally:
            # Restore original autocommit setting
            self.connection.autocommit = original_autocommit
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()