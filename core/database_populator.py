#!/usr/bin/env python3
"""
Database Populator for Chronarr
Bulk populates the Chronarr database from Radarr/Sonarr
Phase 4: Replace NFO-based initial population with direct DB/API queries
"""
import time
import hashlib
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import os
from core.database import ChronarrDatabase
from clients.radarr_client import RadarrClient
from clients.radarr_db_client import RadarrDbClient
from clients.sonarr_client import SonarrClient
from clients.sonarr_db_client import SonarrDbClient
from utils.logging import _log
from utils.imdb_utils import parse_imdb_from_path


class DatabasePopulator:
    """Populates Chronarr database from Radarr/Sonarr sources"""

    def __init__(self, db: ChronarrDatabase, radarr_client: RadarrClient = None, sonarr_client: SonarrClient = None):
        self.db = db

        # Try database clients first, fall back to API clients
        self.radarr_db = None
        self.radarr_api = None
        self.sonarr_db = None
        self.sonarr_api = None
        self.using_radarr_db = False
        self.using_sonarr_db = False

        # Radarr setup
        try:
            self.radarr_db = RadarrDbClient.from_env()
            if self.radarr_db:
                _log("INFO", "DatabasePopulator: Using Radarr direct database access")
                self.radarr = self.radarr_db
                self.using_radarr_db = True
            else:
                raise Exception("Database not configured")
        except Exception:
            self.radarr_api = radarr_client if radarr_client else RadarrClient(
                os.environ.get("RADARR_URL", ""),
                os.environ.get("RADARR_API_KEY", "")
            )
            self.radarr = self.radarr_api
            _log("INFO", "DatabasePopulator: Using Radarr API client")

        # Sonarr setup
        try:
            self.sonarr_db = SonarrDbClient.from_env()
            if self.sonarr_db:
                _log("INFO", "DatabasePopulator: Using Sonarr direct database access")
                self.sonarr = self.sonarr_db
                self.using_sonarr_db = True
            else:
                raise Exception("Database not configured")
        except Exception:
            self.sonarr_api = sonarr_client if sonarr_client else SonarrClient(
                os.environ.get("SONARR_URL", ""),
                os.environ.get("SONARR_API_KEY", "")
            )
            self.sonarr = self.sonarr_api
            _log("INFO", "DatabasePopulator: Using Sonarr API client")

    def get_episode_import_history(self, episode_id: int) -> Optional[str]:
        """
        Get episode import history from either database or API
        Wraps both SonarrDbClient.get_episode_import_date and SonarrClient.get_episode_import_history
        """
        if self.using_sonarr_db and self.sonarr_db:
            # Database client returns (date_iso, source)
            date_iso, source = self.sonarr_db.get_episode_import_date(episode_id)
            return date_iso
        elif self.sonarr_api:
            # API client returns Optional[str]
            return self.sonarr_api.get_episode_import_history(episode_id)
        else:
            return None

    def populate_movies(self) -> Dict[str, any]:
        """
        Populate movies from Radarr database/API

        Returns:
            Dictionary with statistics: {
                'total': int,
                'added': int,
                'updated': int,
                'skipped': int,
                'errors': int,
                'duration': float
            }
        """
        _log("INFO", "Starting movie population from Radarr")
        start_time = time.time()

        stats = {
            'total': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'duration': 0.0,
            'skipped_items': []  # Track what was skipped and why
        }

        try:
            # Get all movies from Radarr (database or API)
            if self.using_radarr_db and self.radarr_db:
                movies = self.radarr_db.get_all_movies()
            elif hasattr(self.radarr, 'db_client') and self.radarr.db_client:
                # Legacy API client with db_client attribute
                movies = self.radarr.db_client.get_all_movies()
            else:
                _log("ERROR", "Radarr database/API client not available - cannot populate movies")
                stats['errors'] += 1
                return stats
            if not movies:
                _log("WARNING", "No movies found in Radarr database")
                return stats

            stats['total'] = len(movies)
            _log("INFO", f"Found {stats['total']} movies in Radarr")

            # Process each movie
            for movie in movies:
                try:
                    # Get movie path first (we'll need it for IMDb extraction)
                    path = movie.get('path', '')

                    # Try to get IMDb ID from Radarr database
                    imdb_id = movie.get('imdb_id')

                    # If not in database, try extracting from directory/filename
                    if not imdb_id and path:
                        imdb_id = parse_imdb_from_path(Path(path))
                        if imdb_id:
                            _log("DEBUG", f"Extracted IMDb ID {imdb_id} from path for: {movie.get('title')}")

                    if not imdb_id:
                        # Generate placeholder IMDb ID using hash of path
                        path_hash = hashlib.md5(path.encode()).hexdigest()[:12]
                        imdb_id = f"missing-{path_hash}"
                        skip_reason = 'No IMDb ID found'
                        skip_info = {
                            'title': movie.get('title', 'Unknown'),
                            'year': movie.get('year'),
                            'imdb_id': imdb_id,
                            'path': path,
                            'reason': skip_reason
                        }
                        stats['skipped_items'].append(skip_info)
                        _log("DEBUG", f"Movie without IMDb ID: {movie.get('title')} (path: {path}), using placeholder {imdb_id}")

                        # Mark as skipped in database with placeholder IMDb ID
                        self.db.mark_movie_skipped(
                            imdb_id=imdb_id,
                            title=movie.get('title', 'Unknown'),
                            year=movie.get('year', 0),
                            path=path,
                            reason=skip_reason
                        )
                        stats['skipped'] += 1
                        continue

                    # Check if movie already exists in database
                    existing = self.db.get_movie_dates(imdb_id)
                    if existing and existing.get('dateadded'):
                        # Already in database - update file path and video status if needed
                        existing_path = existing.get('path')
                        if not existing_path or existing_path == 'unknown' or existing_path != path:
                            _log("INFO", f"Movie {imdb_id} exists but updating file info: {path}")
                            self.db.update_movie_file_info(imdb_id, path, has_video_file=True)

                            # Add to processing history
                            try:
                                self.db.add_processing_history(
                                    imdb_id=imdb_id,
                                    media_type='movie',
                                    event_type='file_info_update',
                                    details={'path': path}
                                )
                            except Exception as e:
                                _log("WARNING", f"Failed to add processing history for {imdb_id}: {e}")

                            stats['updated'] += 1
                        else:
                            _log("DEBUG", f"Movie {imdb_id} already in database with correct path, skipping")
                        continue

                    # Get release date
                    released = None
                    if movie.get('digital_release'):
                        released = movie.get('digital_release')
                        source_type = 'radarr:digital'
                    elif movie.get('physical_release'):
                        released = movie.get('physical_release')
                        source_type = 'radarr:physical'
                    elif movie.get('in_cinemas'):
                        released = movie.get('in_cinemas')
                        source_type = 'radarr:theatrical'
                    else:
                        source_type = 'radarr:unknown'

                    # Get import date from Radarr history using Radarr's internal movie ID
                    radarr_movie_id = movie.get('id')
                    if radarr_movie_id:
                        # get_movie_import_date returns tuple (date, source)
                        if self.using_radarr_db and self.radarr_db:
                            import_date, import_source = self.radarr_db.get_movie_import_date(radarr_movie_id)
                        else:
                            # API client doesn't have this method
                            import_date = None
                            import_source = "radarr:api.no_history"
                        if import_date:
                            dateadded = import_date
                            source = import_source
                        elif released:
                            # Use release date as fallback
                            dateadded = released
                            source = f'{source_type}_fallback'
                        else:
                            skip_reason = 'No import date in Radarr history and no release dates available'
                            skip_info = {
                                'title': movie.get('title', 'Unknown'),
                                'year': movie.get('year'),
                                'imdb_id': imdb_id,
                                'reason': skip_reason
                            }
                            stats['skipped_items'].append(skip_info)
                            _log("DEBUG", f"No date available for movie {imdb_id}, skipping")

                            # Mark as skipped in database for troubleshooting
                            self.db.mark_movie_skipped(
                                imdb_id=imdb_id,
                                title=movie.get('title', 'Unknown'),
                                year=movie.get('year', 0),
                                path=path or 'unknown',
                                reason=skip_reason
                            )
                            stats['skipped'] += 1
                            continue
                    elif released:
                        # No Radarr ID, use release date
                        dateadded = released
                        source = f'{source_type}_fallback'
                    else:
                        skip_reason = 'No Radarr movie ID and no release dates available'
                        skip_info = {
                            'title': movie.get('title', 'Unknown'),
                            'year': movie.get('year'),
                            'imdb_id': imdb_id,
                            'reason': skip_reason
                        }
                        stats['skipped_items'].append(skip_info)
                        _log("DEBUG", f"No date available for movie {imdb_id}, skipping")

                        # Mark as skipped in database for troubleshooting
                        self.db.mark_movie_skipped(
                            imdb_id=imdb_id,
                            title=movie.get('title', 'Unknown'),
                            year=movie.get('year', 0),
                            path=path or 'unknown',
                            reason=skip_reason
                        )
                        stats['skipped'] += 1
                        continue

                    # Insert into database with title and year
                    title = movie.get('title')
                    year = movie.get('year')
                    self.db.upsert_movie_dates(
                        imdb_id, released, dateadded, source,
                        has_video_file=True, title=title, year=year
                    )

                    # Add to processing history
                    try:
                        self.db.add_processing_history(
                            imdb_id=imdb_id,
                            media_type='movie',
                            event_type='database_population',
                            details={'source': source, 'title': title}
                        )
                    except Exception as e:
                        _log("WARNING", f"Failed to add processing history for {imdb_id}: {e}")

                    stats['added'] += 1
                    _log("DEBUG", f"Added movie {imdb_id}: {title} ({year}) (source: {source})")

                except Exception as e:
                    _log("ERROR", f"Error processing movie {movie.get('title', 'unknown')}: {e}")
                    stats['errors'] += 1
                    continue

        except Exception as e:
            _log("ERROR", f"Error during movie population: {e}")
            stats['errors'] += 1

        stats['duration'] = time.time() - start_time
        _log("INFO", f"Movie population complete: {stats['added']} added, {stats['skipped']} skipped, {stats['errors']} errors in {stats['duration']:.2f}s")

        # Log details of skipped items
        if stats['skipped_items']:
            _log("INFO", f"Skipped items details ({len(stats['skipped_items'])} total):")
            for item in stats['skipped_items']:
                _log("INFO", f"  - {item['title']} ({item.get('year', 'N/A')}) [{item.get('imdb_id', 'No IMDb')}]: {item['reason']}")

        return stats

    def populate_tv_episodes(self) -> Dict[str, any]:
        """
        Populate TV episodes from Sonarr API

        Returns:
            Dictionary with statistics: {
                'total_series': int,
                'total_episodes': int,
                'added': int,
                'updated': int,
                'skipped': int,
                'errors': int,
                'duration': float
            }
        """
        _log("INFO", "Starting TV episode population from Sonarr")
        start_time = time.time()

        stats = {
            'total_series': 0,
            'total_episodes': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'duration': 0.0,
            'skipped_items': []  # Track what was skipped and why
        }

        try:
            # Get all series from Sonarr
            all_series = self.sonarr.get_all_series()
            if not all_series:
                _log("WARNING", "No series found in Sonarr")
                return stats

            stats['total_series'] = len(all_series)
            _log("INFO", f"Found {stats['total_series']} series in Sonarr")

            # Process each series
            for series in all_series:
                try:
                    # Database client returns snake_case (imdb_id), API returns camelCase (imdbId)
                    imdb_id = series.get('imdb_id') or series.get('imdbId')
                    series_id = series.get('id')
                    series_path = series.get('path', '')
                    series_title = series.get('title', 'Unknown')

                    if not imdb_id and series_path:
                        # Try to extract from path first
                        imdb_id = parse_imdb_from_path(Path(series_path))
                        if imdb_id:
                            _log("DEBUG", f"Extracted IMDb ID {imdb_id} from path for {series_title}")

                    if not imdb_id:
                        # Generate placeholder IMDb ID using hash of path
                        path_hash = hashlib.md5(series_path.encode()).hexdigest()[:12]
                        imdb_id = f"missing-{path_hash}"
                        _log("DEBUG", f"Series without IMDb ID: {series_title} (path: {series_path}), using placeholder {imdb_id}")

                    # Update series record
                    self.db.upsert_series(imdb_id, series_path)

                    # Try high-performance database bulk query first
                    bulk_import_dates = {}

                    if self.using_sonarr_db and self.sonarr_db:
                        try:
                            _log("DEBUG", f"Using DB bulk query for {series_title}")
                            bulk_import_dates = self.sonarr_db.bulk_import_dates_for_series(series_id)
                            _log("DEBUG", f"✅ Got {len(bulk_import_dates)} import dates from DB for {series_title}")
                        except Exception as e:
                            _log("WARNING", f"DB bulk query failed for {series_title}, falling back to API: {e}")

                    # Get all episodes for this series
                    if self.using_sonarr_db and self.sonarr_db:
                        episodes = self.sonarr_db.get_all_episodes_for_series(series_id)
                    else:
                        episodes = self.sonarr_api.episodes_for_series(series_id)
                    if not episodes:
                        continue

                    _log("DEBUG", f"Processing {len(episodes)} episodes for {series_title}")

                    # Process each episode
                    for episode in episodes:
                        try:
                            # Both database and API return camelCase (seasonNumber, episodeNumber)
                            season_num = episode.get('seasonNumber', 0)
                            episode_num = episode.get('episodeNumber', 0)
                            episode_title = episode.get('title', 'Unknown')

                            if season_num < 0 or episode_num <= 0:
                                continue

                            stats['total_episodes'] += 1

                            # Check if episode already exists
                            existing = self.db.get_episode_date(imdb_id, season_num, episode_num)
                            if existing and existing.get('dateadded'):
                                # Already in database - update file path and video status if needed
                                existing_path = existing.get('path')
                                episode_path = episode.get('path', 'unknown')
                                if not existing_path or existing_path == 'unknown' or existing_path != episode_path:
                                    _log("INFO", f"Episode {imdb_id} S{season_num:02d}E{episode_num:02d} exists but updating file info: {episode_path}")
                                    self.db.update_episode_file_info(imdb_id, season_num, episode_num, episode_path, has_video_file=True)

                                    # Add to processing history
                                    try:
                                        self.db.add_processing_history(
                                            imdb_id=imdb_id,
                                            media_type='episode',
                                            event_type='file_info_update',
                                            details={'season': season_num, 'episode': episode_num, 'path': episode_path}
                                        )
                                    except Exception as e:
                                        _log("WARNING", f"Failed to add processing history for {imdb_id} S{season_num:02d}E{episode_num:02d}: {e}")

                                    stats['updated'] += 1
                                continue

                            # Only process episodes that have video files
                            # Database returns episodeFileId and hasFile (computed field)
                            has_file = episode.get('hasFile', False)

                            if not has_file:
                                # No video file - skip silently (intentionally filtered)
                                continue

                            # Get air date
                            # Both database and API return airDate (camelCase)
                            aired = episode.get('airDate')

                            # Get import date
                            dateadded = None
                            source = None

                            # Try bulk DB result first
                            if (season_num, episode_num) in bulk_import_dates:
                                dateadded, source = bulk_import_dates[(season_num, episode_num)]
                            # Fall back to API query
                            else:
                                episode_id = episode.get('id')
                                if episode_id:
                                    import_date = self.get_episode_import_history(episode_id)
                                    if import_date:
                                        dateadded = import_date
                                        source = 'sonarr:api.import_history'

                            # Fallback to air date if no import date
                            if not dateadded and aired:
                                dateadded = aired
                                source = 'sonarr:aired_fallback'

                            # Last resort: try episode file dateAdded
                            if not dateadded:
                                episode_id = episode.get('id')
                                if episode_id and self.using_sonarr_db and self.sonarr_db:
                                    file_date = self.sonarr_db.get_episode_file_date(series_id, season_num, episode_num)
                                    if file_date:
                                        dateadded = file_date
                                        source = 'sonarr:db.file.dateAdded'
                                        _log("INFO", f"Using file date for {series_title} S{season_num:02d}E{episode_num:02d}: {file_date}")

                            if not dateadded:
                                # No date available
                                skip_reason = 'No import date from Sonarr history and no air date available'
                                skip_info = {
                                    'title': series_title,
                                    'episode_title': episode_title,
                                    'season': season_num,
                                    'episode': episode_num,
                                    'reason': skip_reason
                                }
                                stats['skipped_items'].append(skip_info)

                                # Mark as skipped in database for troubleshooting
                                self.db.mark_episode_skipped(
                                    imdb_id=imdb_id,
                                    season=season_num,
                                    episode=episode_num,
                                    reason=skip_reason
                                )
                                stats['skipped'] += 1
                                continue

                            # Insert into database
                            self.db.upsert_episode_date(imdb_id, season_num, episode_num, aired, dateadded, source, has_file)

                            # Add to processing history
                            try:
                                self.db.add_processing_history(
                                    imdb_id=imdb_id,
                                    media_type='episode',
                                    event_type='database_population',
                                    details={'season': season_num, 'episode': episode_num, 'source': source, 'title': episode_title}
                                )
                            except Exception as e:
                                _log("WARNING", f"Failed to add processing history for {imdb_id} S{season_num:02d}E{episode_num:02d}: {e}")

                            stats['added'] += 1

                        except Exception as e:
                            _log("ERROR", f"Error processing episode S{season_num:02d}E{episode_num:02d} of {series_title}: {e}")
                            stats['errors'] += 1
                            continue

                except Exception as e:
                    _log("ERROR", f"Error processing series {series.get('title', 'unknown')}: {e}")
                    stats['errors'] += 1
                    continue

        except Exception as e:
            _log("ERROR", f"Error during TV episode population: {e}")
            stats['errors'] += 1

        stats['duration'] = time.time() - start_time
        _log("INFO", f"TV episode population complete: {stats['added']} added, {stats['skipped']} skipped, {stats['errors']} errors in {stats['duration']:.2f}s")

        # Log details of skipped items
        if stats['skipped_items']:
            _log("INFO", f"Skipped episodes details ({len(stats['skipped_items'])} total):")
            for item in stats['skipped_items'][:20]:  # Only log first 20 to avoid spam
                _log("INFO", f"  - {item['title']} S{str(item['season']).zfill(2)}E{str(item['episode']).zfill(2)} ({item.get('episode_title', 'Unknown')}): {item['reason']}")
            if len(stats['skipped_items']) > 20:
                _log("INFO", f"  ... and {len(stats['skipped_items']) - 20} more (see web interface for full list)")

        return stats

    def populate_all(self) -> Dict[str, any]:
        """
        Populate both movies and TV episodes

        Returns:
            Combined statistics dictionary
        """
        _log("INFO", "Starting full database population")
        start_time = time.time()

        movie_stats = self.populate_movies()
        tv_stats = self.populate_tv_episodes()

        combined_stats = {
            'movies': movie_stats,
            'tv': tv_stats,
            'total_duration': time.time() - start_time
        }

        _log("INFO", f"Full database population complete in {combined_stats['total_duration']:.2f}s")
        return combined_stats
