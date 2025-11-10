#!/usr/bin/env python3
"""
TV Series Processor - Clean implementation for TV episode processing
Handles manual scans and webhook processing with proper NFO filename matching
"""
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
import re

from core.database import ChronarrDatabase
from core.episode_nfo_manager import EpisodeNFOManager
from core.nfo_manager import NFOManager
from core.path_mapper import PathMapper
from clients.sonarr_client import SonarrClient
from clients.external_clients import ExternalClientManager
from core.logging import _log, convert_utc_to_local


class TVSeriesProcessor:
    """Clean TV series processor with video filename matching"""

    def __init__(self, db: ChronarrDatabase, nfo_manager: NFOManager,
                 path_mapper: PathMapper, sonarr_client: SonarrClient):
        self.db = db
        self.nfo_manager = nfo_manager  # Keep for series/season NFOs
        self.episode_nfo_manager = EpisodeNFOManager()
        self.path_mapper = path_mapper
        self.sonarr = sonarr_client
        self.external_manager = ExternalClientManager()

        # Initialize Sonarr database client for high-performance queries
        self.sonarr_db = None
        try:
            from clients.sonarr_db_client import SonarrDbClient
            self.sonarr_db = SonarrDbClient.from_env()
            if self.sonarr_db:
                _log("INFO", "✅ SONARR DB MODE: Direct database access enabled")
            else:
                _log("INFO", "⚠️ SONARR API MODE: Using API (configure SONARR_DB_TYPE for better performance)")
        except Exception as e:
            _log("WARNING", f"Sonarr DB client initialization failed, using API: {e}")
            self.sonarr_db = None
    
    def process_series_manual_scan(self, series_path: Path) -> bool:
        """Process a TV series during manual scan"""
        _log("INFO", f"Processing TV series: {series_path.name}")
        
        # Extract IMDb ID
        imdb_id = self._extract_imdb_id(series_path)
        if not imdb_id:
            _log("ERROR", f"No IMDb ID found for series: {series_path.name}")
            return False
        
        # Find all episodes on disk
        episodes_on_disk = self._find_episodes_on_disk(series_path)
        if not episodes_on_disk:
            _log("WARNING", f"No episodes found on disk for: {series_path.name}")
            return False
        
        _log("INFO", f"Found {len(episodes_on_disk)} episodes on disk")
        
        # Process each episode
        episodes_processed = 0
        for (season_num, episode_num), video_files in episodes_on_disk.items():
            if self._process_episode_manual_scan(series_path, imdb_id, season_num, episode_num):
                episodes_processed += 1
        
        # Create series-level NFOs if any episodes were processed
        if episodes_processed > 0:
            self._create_series_nfos(series_path, imdb_id)
        
        _log("INFO", f"Completed processing series: {series_path.name} ({episodes_processed} episodes)")
        return episodes_processed > 0
    
    def process_episode_webhook(self, webhook_data: Dict[str, Any]) -> bool:
        """Process a single episode from Sonarr webhook"""
        # TODO: Parse webhook data and extract episode info
        # This will be implemented when we add webhook support
        pass
    
    def _extract_imdb_id(self, series_path: Path) -> Optional[str]:
        """Extract IMDb ID from series directory or files"""
        # Try directory name first
        imdb_id = self.nfo_manager.parse_imdb_from_path(series_path)
        if imdb_id:
            return imdb_id
        
        # Try tvshow.nfo if it exists
        tvshow_nfo = series_path / "tvshow.nfo"
        if tvshow_nfo.exists():
            imdb_id = self.nfo_manager.parse_imdb_from_nfo(tvshow_nfo)
            if imdb_id:
                return imdb_id
        
        # Try any existing episode NFO files
        for season_dir in series_path.iterdir():
            if season_dir.is_dir() and self._is_season_directory(season_dir.name):
                for nfo_file in season_dir.glob("*.nfo"):
                    imdb_id = self.nfo_manager.parse_imdb_from_nfo(nfo_file)
                    if imdb_id:
                        return imdb_id
        
        return None
    
    def _is_season_directory(self, dirname: str) -> bool:
        """Check if directory name matches season pattern"""
        return bool(re.match(r'^[Ss]eason\s+\d+$', dirname, re.IGNORECASE))
    
    def _find_episodes_on_disk(self, series_path: Path) -> Dict[Tuple[int, int], List[Path]]:
        """Find all episodes on disk, grouped by (season, episode)"""
        episodes = {}
        
        try:
            _log("DEBUG", f"Scanning for season directories in: {series_path}")
            _log("DEBUG", f"Series path exists: {series_path.exists()}, is_dir: {series_path.is_dir()}")
            
            if not series_path.exists() or not series_path.is_dir():
                _log("ERROR", f"Series path does not exist or is not a directory: {series_path}")
                return episodes
            
            # List all items in directory for debugging
            try:
                items = list(series_path.iterdir())
                _log("DEBUG", f"Found {len(items)} items in series directory")
                for item in items:
                    _log("DEBUG", f"  Item: {item.name} (is_dir: {item.is_dir()})")
            except Exception as e:
                _log("ERROR", f"Failed to list directory contents: {e}")
                return episodes
            
            for season_dir in series_path.iterdir():
                _log("DEBUG", f"Checking directory: {season_dir.name} (is_dir: {season_dir.is_dir()})")
                _log("DEBUG", f"Season directory regex test for '{season_dir.name}': {self._is_season_directory(season_dir.name)}")
                
                if season_dir.is_dir() and self._is_season_directory(season_dir.name):
                    season_num = self._extract_season_number(season_dir.name)
                    _log("DEBUG", f"Found season directory: {season_dir.name} → season {season_num}")
                    if season_num is None:
                        _log("WARNING", f"Could not extract season number from: {season_dir.name}")
                        continue
                    
                    # Find video files in this season
                    season_episodes = self.episode_nfo_manager.find_video_files_for_season(season_dir)
                    _log("DEBUG", f"Found {len(season_episodes)} episodes in {season_dir.name}: {list(season_episodes.keys())}")
                    
                    # Add season directory info to episodes
                    for (s_num, e_num), video_files in season_episodes.items():
                        _log("DEBUG", f"Episode S{s_num:02d}E{e_num:02d}: season_dir={season_num}, filename_season={s_num}")
                        if s_num == season_num:  # Verify season matches directory
                            episodes[(s_num, e_num)] = video_files
                            _log("DEBUG", f"Added episode S{s_num:02d}E{e_num:02d} to processing list")
                        else:
                            _log("WARNING", f"Season mismatch: directory={season_num}, filename={s_num} for S{s_num:02d}E{e_num:02d}")
            
            _log("DEBUG", f"Total episodes found on disk: {len(episodes)}")
            return episodes
            
        except Exception as e:
            _log("ERROR", f"Exception in _find_episodes_on_disk: {e}")
            return episodes
    
    def _extract_season_number(self, dirname: str) -> Optional[int]:
        """Extract season number from directory name"""
        match = re.search(r'[Ss]eason\s+(\d+)', dirname, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _process_episode_manual_scan(self, series_path: Path, imdb_id: str, 
                                   season_num: int, episode_num: int) -> bool:
        """Process a single episode during manual scan"""
        season_dir = series_path / f"Season {season_num:02d}"
        if not season_dir.exists():
            # Try alternate format
            season_dir = series_path / f"Season {season_num}"
            if not season_dir.exists():
                _log("ERROR", f"Season directory not found for S{season_num:02d}E{episode_num:02d}")
                return False
        
        _log("DEBUG", f"Processing episode S{season_num:02d}E{episode_num:02d}")
        
        # Step 1: Check for existing Chronarr data
        existing_nfo = self.episode_nfo_manager.find_nfo_for_episode(season_dir, season_num, episode_num)
        if existing_nfo:
            nfo_data = self.episode_nfo_manager.extract_chronarr_data(existing_nfo)
            if nfo_data:
                # Verify against database
                db_data = self.db.get_episode_date(imdb_id, season_num, episode_num)
                if db_data and db_data.get("dateadded") == nfo_data.get("dateadded"):
                    _log("DEBUG", f"Episode S{season_num:02d}E{episode_num:02d} already up to date")
                    # Still migrate filename if needed
                    self.episode_nfo_manager.migrate_nfo_to_video_filename(season_dir, season_num, episode_num)
                    return True
        
        # Step 2: Check database
        db_data = self.db.get_episode_date(imdb_id, season_num, episode_num)
        if db_data and db_data.get("dateadded"):
            _log("DEBUG", f"Using database data for S{season_num:02d}E{episode_num:02d}")
            aired = db_data.get("aired")
            dateadded = db_data.get("dateadded")
            source = db_data.get("source", "database")
        else:
            # Step 3: Query Sonarr for episode data
            aired, dateadded, source = self._get_episode_dates_from_sonarr(imdb_id, season_num, episode_num)
        
        # Step 4: Create/update NFO and database
        if dateadded or aired:
            # Get episode metadata for title/plot
            title, plot = self._get_episode_metadata_from_sonarr(imdb_id, season_num, episode_num)
            
            # Use aired date as dateadded if no import date found (user requirement)
            if not dateadded and aired:
                dateadded = aired
                if source == "no_data_found":
                    source = "tmdb:air_date_fallback"
                else:
                    source = f"{source}_used_as_dateadded"
                _log("INFO", f"Using aired date as dateadded for S{season_num:02d}E{episode_num:02d}: {dateadded}")
            
            # Create/update NFO with video filename
            success = self.episode_nfo_manager.create_episode_nfo(
                season_dir, season_num, episode_num, aired, dateadded, source, title, plot
            )
            
            if success:
                # Update database
                self.db.upsert_episode_date(imdb_id, season_num, episode_num, aired, dateadded, source, True)
                return True
        
        _log("WARNING", f"Could not get dates for episode S{season_num:02d}E{episode_num:02d}")
        return False
    
    def _get_episode_dates_from_sonarr(self, imdb_id: str, season_num: int, episode_num: int) -> Tuple[Optional[str], Optional[str], str]:
        """Get episode dates from Sonarr (DB first, then API fallback)"""
        aired = None
        dateadded = None
        source = "no_data_found"

        # TIER 1: Try Sonarr database (high performance)
        if self.sonarr_db:
            try:
                # Find series by IMDb
                series = self.sonarr_db.get_series_by_imdb(imdb_id)
                if series:
                    series_id = series['id']

                    # Get all episodes for series
                    episodes = self.sonarr_db.get_all_episodes_for_series(series_id)

                    # Find target episode
                    target_episode = None
                    for ep in episodes:
                        if ep['seasonNumber'] == season_num and ep['episodeNumber'] == episode_num:
                            target_episode = ep
                            break

                    if target_episode:
                        # Get air date
                        aired = target_episode.get('airDate')

                        # Try to get import date from history
                        episode_id = target_episode['id']
                        import_date, import_source = self.sonarr_db.get_episode_import_date(episode_id)

                        if import_date:
                            dateadded = import_date
                            source = import_source
                            _log("INFO", f"✅ DB: Found import date for S{season_num:02d}E{episode_num:02d}: {dateadded}")
                            return aired, dateadded, source

                        # Fallback to episode file date
                        file_date = self.sonarr_db.get_episode_file_date(series_id, season_num, episode_num)
                        if file_date:
                            dateadded = file_date
                            source = "sonarr:db.file.dateAdded"
                            _log("INFO", f"✅ DB: Using file date for S{season_num:02d}E{episode_num:02d}: {dateadded}")
                            return aired, dateadded, source

                        # Use air date as fallback
                        if aired:
                            dateadded = convert_utc_to_local(aired)
                            source = "sonarr:db.airDate"
                            _log("WARNING", f"⚠️ DB: No import date, using air date for S{season_num:02d}E{episode_num:02d}: {dateadded}")
                            return aired, dateadded, source

            except Exception as e:
                _log("WARNING", f"Sonarr DB query failed for S{season_num:02d}E{episode_num:02d}, falling back to API: {e}")

        # TIER 2: Fall back to Sonarr API
        if not self.sonarr.enabled:
            _log("WARNING", "Sonarr not enabled, cannot get episode dates")
            return aired, dateadded, source

        try:
            # Find series in Sonarr using lookup endpoint first
            series = self.sonarr.series_by_imdb(imdb_id)
            if not series:
                _log("WARNING", f"Series not found via Sonarr lookup for IMDb: {imdb_id}")
                # Try direct method as fallback (slower but more reliable)
                _log("DEBUG", f"Trying direct series search for IMDb: {imdb_id}")
                series = self.sonarr.series_by_imdb_direct(imdb_id)
                if not series:
                    _log("WARNING", f"Series not found via direct search either for IMDb: {imdb_id}")
                    # Fall through to external API fallback

            if series:
                # Get episodes for series
                episodes = self.sonarr.episodes_for_series(series["id"])
                target_episode = None

                for episode in episodes:
                    if (episode.get("seasonNumber") == season_num and
                        episode.get("episodeNumber") == episode_num):
                        target_episode = episode
                        break

                if not target_episode:
                    _log("WARNING", f"Episode S{season_num:02d}E{episode_num:02d} not found in Sonarr")
                    # Don't return here - fall through to external API fallback
                else:
                    # Get airdate
                    aired = target_episode.get("airDateUtc")

                    # Try to get import history
                    episode_id = target_episode.get("id")
                    if episode_id:
                        import_date = self.get_episode_import_history(episode_id)
                        if import_date:
                            # Sonarr import dates are already in local timezone despite 'Z' suffix
                            # Remove 'Z' and use as-is to avoid double timezone conversion
                            dateadded = import_date.replace('Z', '') if 'Z' in import_date else import_date
                            source = "sonarr:api.history.import"
                            _log("INFO", f"✅ API: Found import date for S{season_num:02d}E{episode_num:02d}: {dateadded}")
                            return aired, dateadded, source

                    # Fallback to airdate if no import history
                    if aired:
                        dateadded = convert_utc_to_local(aired)
                        source = "sonarr:api.episode.airDateUtc"
                        _log("WARNING", f"⚠️ API: No import history for S{season_num:02d}E{episode_num:02d}, using airdate: {dateadded}")
                        return aired, dateadded, source

        except Exception as e:
            _log("ERROR", f"Sonarr API error for S{season_num:02d}E{episode_num:02d}: {e}")
        
        # Try external APIs for episode airdate
        _log("INFO", f"Trying external APIs for episode S{season_num:02d}E{episode_num:02d} airdate")
        aired, source = self._get_episode_airdate_from_external_apis(imdb_id, season_num, episode_num)
        if aired:
            dateadded = convert_utc_to_local(aired)
            return aired, dateadded, source
        
        _log("ERROR", f"Could not get any date information for S{season_num:02d}E{episode_num:02d}")
        return aired, dateadded, source
    
    def _get_episode_metadata_from_sonarr(self, imdb_id: str, season_num: int, episode_num: int) -> Tuple[Optional[str], Optional[str]]:
        """Get episode title and plot from Sonarr"""
        if not self.sonarr.enabled:
            return None, None
        
        try:
            series = self.sonarr.series_by_imdb(imdb_id)
            if not series:
                # Try direct method as fallback
                series = self.sonarr.series_by_imdb_direct(imdb_id)
            
            if series:
                episodes = self.sonarr.episodes_for_series(series["id"])
                for episode in episodes:
                    if (episode.get("seasonNumber") == season_num and 
                        episode.get("episodeNumber") == episode_num):
                        title = episode.get("title")
                        plot = episode.get("overview")
                        return title, plot
        except Exception as e:
            _log("DEBUG", f"Could not get metadata for S{season_num:02d}E{episode_num:02d}: {e}")
        
        return None, None
    
    def _get_episode_airdate_from_external_apis(self, imdb_id: str, season_num: int, episode_num: int) -> Tuple[Optional[str], str]:
        """Get episode airdate from external APIs (TMDB, OMDb) as fallback"""
        # Try TMDB first
        if self.external_manager.tmdb.enabled:
            try:
                _log("DEBUG", f"Trying TMDB for episode S{season_num:02d}E{episode_num:02d} airdate")
                
                # First convert IMDb to TMDB TV ID
                tv_search = self.external_manager.tmdb._get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
                if tv_search and tv_search.get("tv_results"):
                    tv_id = tv_search["tv_results"][0].get("id")
                    if tv_id:
                        _log("DEBUG", f"Found TMDB TV ID {tv_id} for {imdb_id}")
                        
                        # Get episode details
                        episode_data = self.external_manager.tmdb._get(f"/tv/{tv_id}/season/{season_num}/episode/{episode_num}")
                        if episode_data and episode_data.get("air_date"):
                            airdate = episode_data["air_date"]
                            # Convert to ISO format with UTC timezone
                            iso_airdate = f"{airdate}T00:00:00Z"
                            _log("INFO", f"Found TMDB airdate for S{season_num:02d}E{episode_num:02d}: {iso_airdate}")
                            return iso_airdate, "tmdb:episode.air_date"
            except Exception as e:
                _log("WARNING", f"TMDB episode lookup failed for S{season_num:02d}E{episode_num:02d}: {e}")
        
        # Try OMDb as fallback
        if self.external_manager.omdb.enabled:
            try:
                _log("DEBUG", f"Trying OMDb for episode S{season_num:02d}E{episode_num:02d} airdate")
                episode_dates = self.external_manager.omdb.get_tv_season_episodes(imdb_id, season_num)
                if episode_num in episode_dates:
                    airdate = episode_dates[episode_num]
                    # Convert to ISO format
                    from datetime import datetime, timezone
                    try:
                        # Try to parse OMDb date format (usually DD MMM YYYY)
                        dt = datetime.strptime(airdate, "%d %b %Y").replace(tzinfo=timezone.utc)
                        iso_airdate = dt.isoformat(timespec="seconds")
                        _log("INFO", f"Found OMDb airdate for S{season_num:02d}E{episode_num:02d}: {iso_airdate}")
                        return iso_airdate, "omdb:episode.released"
                    except ValueError:
                        # Try other common formats
                        for fmt in ["%Y-%m-%d", "%d %B %Y"]:
                            try:
                                dt = datetime.strptime(airdate, fmt).replace(tzinfo=timezone.utc)
                                iso_airdate = dt.isoformat(timespec="seconds")
                                _log("INFO", f"Found OMDb airdate for S{season_num:02d}E{episode_num:02d}: {iso_airdate}")
                                return iso_airdate, "omdb:episode.released"
                            except ValueError:
                                continue
            except Exception as e:
                _log("WARNING", f"OMDb episode lookup failed for S{season_num:02d}E{episode_num:02d}: {e}")
        
        _log("WARNING", f"No external API airdate found for S{season_num:02d}E{episode_num:02d}")
        return None, "no_external_data"
    
    def _create_series_nfos(self, series_path: Path, imdb_id: str):
        """DISABLED: Skip creating tvshow.nfo and season.nfo files (user only wants episode NFOs)"""
        # # Create tvshow.nfo only if it doesn't exist
        # tvshow_nfo = series_path / "tvshow.nfo"
        # if not tvshow_nfo.exists():
        #     self.nfo_manager.create_tvshow_nfo(series_path, imdb_id)
        # else:
        #     _log("DEBUG", f"Skipping tvshow.nfo creation - already exists: {tvshow_nfo}")
        # 
        # # Create season.nfo for each season directory only if they don't exist
        # for season_dir in series_path.iterdir():
        #     if season_dir.is_dir() and self._is_season_directory(season_dir.name):
        #         season_num = self._extract_season_number(season_dir.name)
        #         if season_num is not None:
        #             season_nfo = season_dir / "season.nfo"
        #             if not season_nfo.exists():
        #                 self.nfo_manager.create_season_nfo(season_dir, season_num)
        #             else:
        #                 _log("DEBUG", f"Skipping season.nfo creation - already exists: {season_nfo}")
        pass  # Function disabled - only process episode NFOs