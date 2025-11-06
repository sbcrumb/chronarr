"""
Orphaned Record Cleanup Utility for Chronarr
Removes database entries for media that no longer exists in Radarr/Sonarr or on filesystem
"""
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from core.logging import _log


class OrphanedRecordCleaner:
    """Clean up orphaned records from Chronarr database"""

    def __init__(self, chronarr_db, radarr_db_client=None, sonarr_db_client=None):
        """
        Initialize cleanup utility

        Args:
            chronarr_db: ChronarrDatabase instance
            radarr_db_client: Optional RadarrDbClient instance
            sonarr_db_client: Optional SonarrDbClient instance
        """
        self.chronarr_db = chronarr_db
        self.radarr_db = radarr_db_client
        self.sonarr_db = sonarr_db_client

    def find_orphaned_movies(self, check_filesystem: bool = True, check_database: bool = True) -> List[Dict[str, Any]]:
        """
        Find orphaned movie records

        Args:
            check_filesystem: Verify file paths exist
            check_database: Verify entries exist in Radarr database

        Returns:
            List of orphaned movie records with reasons
        """
        orphaned = []

        # Get all movies from Chronarr database
        with self.chronarr_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT imdb_id, title, path, dateadded
                FROM movies
                ORDER BY title
            """)
            movies = cursor.fetchall()

        _log("INFO", f"Checking {len(movies)} movies for orphaned records...")

        for movie in movies:
            imdb_id = movie['imdb_id']
            title = movie['title']
            file_path = movie.get('path')

            reasons = []
            filesystem_missing = False
            database_missing = False

            # Check 1: File system
            if check_filesystem and file_path:
                if not Path(file_path).exists():
                    filesystem_missing = True
                    reasons.append(f"File not found: {file_path}")

            # Check 2: Radarr database
            if check_database and self.radarr_db:
                try:
                    radarr_movie = self.radarr_db.get_movie_by_imdb(imdb_id)
                    if not radarr_movie:
                        database_missing = True
                        reasons.append("Not found in Radarr database")
                except Exception as e:
                    _log("WARNING", f"Error checking Radarr DB for {imdb_id}: {e}")

            # Orphaned if BOTH checks fail (hybrid approach)
            if check_filesystem and check_database:
                is_orphaned = filesystem_missing and database_missing
            elif check_filesystem:
                is_orphaned = filesystem_missing
            elif check_database:
                is_orphaned = database_missing
            else:
                is_orphaned = False

            if is_orphaned and reasons:
                orphaned.append({
                    'imdb_id': imdb_id,
                    'title': title,
                    'file_path': file_path,
                    'dateadded': movie.get('dateadded'),
                    'reasons': reasons,
                    'type': 'movie'
                })

        _log("INFO", f"Found {len(orphaned)} orphaned movies")
        return orphaned

    def find_orphaned_series(self, check_filesystem: bool = True, check_database: bool = True) -> List[Dict[str, Any]]:
        """
        Find orphaned TV series records

        Args:
            check_filesystem: Verify series paths exist
            check_database: Verify entries exist in Sonarr database

        Returns:
            List of orphaned series records with reasons
        """
        orphaned = []

        # Get all series from Chronarr database
        with self.chronarr_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT imdb_id, path
                FROM series
                ORDER BY path
            """)
            series_list = cursor.fetchall()

        _log("INFO", f"Checking {len(series_list)} TV series for orphaned records...")

        for series in series_list:
            imdb_id = series['imdb_id']
            series_path = series.get('path')
            # Extract title from path for display purposes
            title = Path(series_path).name if series_path else imdb_id

            reasons = []
            filesystem_missing = False
            database_missing = False

            # Check 1: File system
            if check_filesystem and series_path:
                if not Path(series_path).exists():
                    filesystem_missing = True
                    reasons.append(f"Series path not found: {series_path}")

            # Check 2: Sonarr database
            if check_database and self.sonarr_db:
                try:
                    sonarr_series = self.sonarr_db.get_series_by_imdb(imdb_id)
                    if not sonarr_series:
                        database_missing = True
                        reasons.append("Not found in Sonarr database")
                except Exception as e:
                    _log("WARNING", f"Error checking Sonarr DB for {imdb_id}: {e}")

            # Orphaned if BOTH checks fail (hybrid approach)
            if check_filesystem and check_database:
                is_orphaned = filesystem_missing and database_missing
            elif check_filesystem:
                is_orphaned = filesystem_missing
            elif check_database:
                is_orphaned = database_missing
            else:
                is_orphaned = False

            if is_orphaned and reasons:
                # Count episodes for this series
                with self.chronarr_db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) as episode_count
                        FROM episodes
                        WHERE imdb_id = %s
                    """, (imdb_id,))
                    result = cursor.fetchone()
                    episode_count = result['episode_count'] if result else 0

                orphaned.append({
                    'imdb_id': imdb_id,
                    'title': title,
                    'series_path': series_path,
                    'episode_count': episode_count,
                    'reasons': reasons,
                    'type': 'series'
                })

        _log("INFO", f"Found {len(orphaned)} orphaned TV series")
        return orphaned

    def remove_orphaned_movies(self, orphaned_movies: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
        """
        Remove orphaned movie records from database

        Args:
            orphaned_movies: List of orphaned movie records from find_orphaned_movies()
            dry_run: If True, only report what would be deleted

        Returns:
            Dictionary with removal results
        """
        removed_count = 0
        removed_titles = []

        for movie in orphaned_movies:
            imdb_id = movie['imdb_id']
            title = movie['title']
            reasons = ', '.join(movie['reasons'])

            if dry_run:
                _log("INFO", f"[DRY RUN] Would remove movie: {title} ({imdb_id}) - Reasons: {reasons}")
                removed_titles.append(f"{title} ({imdb_id})")
                removed_count += 1
            else:
                try:
                    with self.chronarr_db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM movies WHERE imdb_id = %s", (imdb_id,))

                    _log("INFO", f"Removed orphaned movie: {title} ({imdb_id}) - Reasons: {reasons}")
                    removed_titles.append(f"{title} ({imdb_id})")
                    removed_count += 1
                except Exception as e:
                    _log("ERROR", f"Failed to remove movie {imdb_id}: {e}")

        return {
            'removed_count': removed_count,
            'removed_titles': removed_titles,
            'dry_run': dry_run
        }

    def remove_orphaned_series(self, orphaned_series: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
        """
        Remove orphaned TV series records from database

        Args:
            orphaned_series: List of orphaned series records from find_orphaned_series()
            dry_run: If True, only report what would be deleted

        Returns:
            Dictionary with removal results
        """
        removed_count = 0
        removed_episodes = 0
        removed_titles = []

        for series in orphaned_series:
            imdb_id = series['imdb_id']
            title = series['title']
            episode_count = series.get('episode_count', 0)
            reasons = ', '.join(series['reasons'])

            if dry_run:
                _log("INFO", f"[DRY RUN] Would remove series: {title} ({imdb_id}) with {episode_count} episodes - Reasons: {reasons}")
                removed_titles.append(f"{title} ({imdb_id}) - {episode_count} episodes")
                removed_count += 1
                removed_episodes += episode_count
            else:
                try:
                    with self.chronarr_db.get_connection() as conn:
                        cursor = conn.cursor()
                        # Remove episodes first
                        cursor.execute("DELETE FROM episodes WHERE imdb_id = %s", (imdb_id,))
                        # Then remove series
                        cursor.execute("DELETE FROM series WHERE imdb_id = %s", (imdb_id,))

                    _log("INFO", f"Removed orphaned series: {title} ({imdb_id}) with {episode_count} episodes - Reasons: {reasons}")
                    removed_titles.append(f"{title} ({imdb_id}) - {episode_count} episodes")
                    removed_count += 1
                    removed_episodes += episode_count
                except Exception as e:
                    _log("ERROR", f"Failed to remove series {imdb_id}: {e}")

        return {
            'removed_count': removed_count,
            'removed_episodes': removed_episodes,
            'removed_titles': removed_titles,
            'dry_run': dry_run
        }

    def cleanup_orphaned_records(self,
                                 check_movies: bool = True,
                                 check_series: bool = True,
                                 check_filesystem: bool = True,
                                 check_database: bool = True,
                                 dry_run: bool = False) -> Dict[str, Any]:
        """
        Main cleanup function - find and remove all orphaned records

        Args:
            check_movies: Clean up orphaned movies
            check_series: Clean up orphaned TV series
            check_filesystem: Verify file paths exist
            check_database: Verify entries exist in Radarr/Sonarr databases
            dry_run: If True, only report what would be deleted

        Returns:
            Comprehensive cleanup report
        """
        start_time = datetime.now()
        _log("INFO", f"Starting orphaned record cleanup (dry_run={dry_run})...")

        report = {
            'start_time': start_time.isoformat(),
            'dry_run': dry_run,
            'movies': {'checked': 0, 'orphaned': 0, 'removed': 0, 'removed_titles': []},
            'series': {'checked': 0, 'orphaned': 0, 'removed': 0, 'removed_episodes': 0, 'removed_titles': []},
            'validation_methods': []
        }

        # Record validation methods used
        if check_filesystem:
            report['validation_methods'].append('filesystem')
        if check_database:
            report['validation_methods'].append('database')

        # Process movies
        if check_movies:
            orphaned_movies = self.find_orphaned_movies(check_filesystem, check_database)
            report['movies']['checked'] = len(orphaned_movies) if orphaned_movies else 0
            report['movies']['orphaned'] = len(orphaned_movies)

            if orphaned_movies:
                movie_results = self.remove_orphaned_movies(orphaned_movies, dry_run)
                report['movies']['removed'] = movie_results['removed_count']
                report['movies']['removed_titles'] = movie_results['removed_titles']

        # Process TV series
        if check_series:
            orphaned_series = self.find_orphaned_series(check_filesystem, check_database)
            report['series']['checked'] = len(orphaned_series) if orphaned_series else 0
            report['series']['orphaned'] = len(orphaned_series)

            if orphaned_series:
                series_results = self.remove_orphaned_series(orphaned_series, dry_run)
                report['series']['removed'] = series_results['removed_count']
                report['series']['removed_episodes'] = series_results.get('removed_episodes', 0)
                report['series']['removed_titles'] = series_results['removed_titles']

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        report['end_time'] = end_time.isoformat()
        report['duration_seconds'] = duration
        report['total_removed'] = report['movies']['removed'] + report['series']['removed']

        _log("INFO", f"Orphaned record cleanup completed in {duration:.2f}s - Removed {report['total_removed']} items")

        return report
