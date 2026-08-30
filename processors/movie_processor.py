"""Movie processing — date discovery and DB writes for Radarr-managed movies."""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.database import ChronarrDatabase
from core.path_mapper import PathMapper
from clients.radarr_client import RadarrClient
from clients.radarr_db_client import RadarrDbClient
from clients.external_clients import ExternalClientManager
from config.settings import config
from utils.logging import _log
from utils.imdb_utils import find_imdb_in_directory  # Phase 3: Replaced NFOManager
from utils.file_utils import find_media_path_by_imdb_and_title


def _get_local_timezone():
    """Get the local timezone, respecting TZ environment variable"""
    tz_name = os.environ.get('TZ', 'UTC')
    
    try:
        # Try zoneinfo first (Python 3.9+)
        return ZoneInfo(tz_name)
    except ImportError:
        # Fallback for older Python versions
        try:
            import pytz
            return pytz.timezone(tz_name)
        except:
            # Final fallback to UTC
            return timezone.utc
    except:
        # Final fallback to UTC
        return timezone.utc


def convert_utc_to_local(utc_iso_string: str) -> str:
    """Convert UTC ISO timestamp to local timezone timestamp"""
    if not utc_iso_string:
        return utc_iso_string
    
    try:
        # Parse UTC timestamp
        if utc_iso_string.endswith('Z'):
            dt_utc = datetime.fromisoformat(utc_iso_string.replace('Z', '+00:00'))
        elif '+00:00' in utc_iso_string:
            dt_utc = datetime.fromisoformat(utc_iso_string)
        else:
            # Assume UTC if no timezone info
            dt_utc = datetime.fromisoformat(utc_iso_string).replace(tzinfo=timezone.utc)
        
        # Convert to local timezone
        local_tz = _get_local_timezone()
        dt_local = dt_utc.astimezone(local_tz)
        
        return dt_local.isoformat(timespec='seconds')
    except Exception:
        # If conversion fails, return original
        return utc_iso_string


class MovieProcessor:

    def __init__(self, db: ChronarrDatabase, nfo_manager, path_mapper: PathMapper, radarr_client=None, registry=None):
        # nfo_manager kept for call-site compat but is unused
        self.db = db
        self.path_mapper = path_mapper
        # InstanceRegistry — lets per-call `instance` params resolve the right
        # client/mapper instead of always using the default instance below.
        # None in the legacy single-instance/test construction path.
        self.registry = registry

        if radarr_client:
            # Pre-built client from InstanceRegistry (preferred path)
            self.radarr = radarr_client
            self.using_db = isinstance(radarr_client, RadarrDbClient)
        else:
            # Fallback: construct from env vars (single-instance legacy path)
            try:
                self.radarr = RadarrDbClient.from_env()
                if not self.radarr:
                    raise Exception("Database not configured")
                self.using_db = True
                _log("INFO", "Using Radarr direct database access")
            except Exception:
                self.radarr = RadarrClient(
                    os.environ.get("RADARR_URL", ""),
                    os.environ.get("RADARR_API_KEY", "")
                )
                self.using_db = False
                _log("INFO", "Using Radarr API client (database not configured)")

        self.external_clients = ExternalClientManager()

    def _resolve_radarr(self, instance: str):
        """Return (client, using_db, path_mapper) for a named instance.

        Looks the instance up in the InstanceRegistry so per-call `instance`
        params actually pick the right Radarr server instead of every call
        silently using whichever instance was wired in at construction time.
        Falls back to the default-instance attributes when there's no
        registry (legacy/test construction) or the instance isn't found.
        """
        if self.registry:
            client = self.registry.radarr(instance)
            if client is not None:
                mapper = self.registry.radarr_mapper(instance) or self.path_mapper
                return client, isinstance(client, RadarrDbClient), mapper
            _log("WARNING", f"[{instance}] No Radarr client in registry — falling back to default instance")
        return self.radarr, self.using_db, self.path_mapper

    def find_movie_path(self, movie_title: str, imdb_id: str, radarr_path: str = None, instance: str = 'radarr') -> Optional[Path]:
        """Find movie directory path using unified file utilities"""
        _, _, path_mapper = self._resolve_radarr(instance)
        return find_media_path_by_imdb_and_title(
            title=movie_title,
            imdb_id=imdb_id,
            search_paths=config.movie_paths,
            webhook_path=radarr_path,
            path_mapper=path_mapper
        )
    
    def should_skip_movie(self, imdb_id: str, movie_name: str = "", instance: str = 'radarr') -> Tuple[bool, str]:
        """Return (should_skip, reason) — skip when date, source, and video file are all present."""
        try:
            result = self.db.get_movie_dates(imdb_id, instance)
            if not result:
                return False, "No database record found"

            dateadded = result.get('dateadded')
            source = result.get('source')
            has_video_file = result.get('has_video_file', False)

            if dateadded and source and source not in ('unknown', 'no_valid_date_source') and has_video_file:
                return True, f"Complete: Has valid date '{dateadded}' from source '{source}'"
            if not dateadded:
                return False, "Missing dateadded"
            if not source or source in ('unknown', 'no_valid_date_source'):
                return False, f"Invalid source: '{source}'"
            if not has_video_file:
                return False, "No video file detected"
            return False, "Incomplete movie data"

        except Exception as e:
            _log("ERROR", f"Error checking movie completion for {imdb_id}: {e}")
            return False, f"Error checking completion: {e}"
    
    def process_movie(self, movie_path: Path, webhook_mode: bool = False, force_scan: bool = False, scan_mode: str = "smart", shutdown_event=None, imdb_id: str = None, instance: str = 'radarr') -> str:
        """Process a movie directory"""
        # Prefer the IMDb ID passed in (e.g. from webhook payload) over filesystem detection.
        # Filesystem detection only works when the ID is embedded in the folder/file name,
        # which standard Radarr naming doesn't do.
        if not imdb_id:
            imdb_id = find_imdb_in_directory(movie_path)
        if not imdb_id:
            _log("ERROR", f"[{instance}] No IMDb ID found in movie directory, filenames, or NFO file: {movie_path}")
            return "error"
        
        # Handle TMDB ID fallback case
        is_tmdb_fallback = imdb_id.startswith("tmdb-")
        if is_tmdb_fallback:
            _log("INFO", f"[{instance}] Processing movie: {movie_path.name} (TMDB: {imdb_id})")
        else:
            _log("INFO", f"[{instance}] Processing movie: {movie_path.name} (IMDb: {imdb_id})")
        
        # Check if we should skip this movie (unless forced, webhook mode, or incomplete mode)
        # Skip database optimization for incomplete mode since we need to check NFO files first
        if not force_scan and not webhook_mode and scan_mode != "incomplete":
            should_skip, reason = self.should_skip_movie(imdb_id, movie_path.name, instance=instance)
            if should_skip:
                _log("INFO", f"[{instance}] ⏭️ SKIPPING MOVIE: {movie_path.name} [{imdb_id}] - {reason}")
                self.db.upsert_movie(imdb_id, str(movie_path), instance=instance)
                return "skipped"
            else:
                _log("INFO", f"[{instance}] 🎬 PROCESSING MOVIE: {movie_path.name} [{imdb_id}] - {reason}")
        elif force_scan:
            _log("INFO", f"[{instance}] 🔄 FORCE PROCESSING MOVIE: {movie_path.name} [{imdb_id}] - Force scan enabled")
        else:
            _log("INFO", f"[{instance}] 📥 WEBHOOK PROCESSING MOVIE: {movie_path.name} [{imdb_id}] - Webhook mode")
        
        # Check for shutdown signal early in processing
        if shutdown_event and shutdown_event.is_set():
            _log("INFO", f"[{instance}] ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping movie processing: {movie_path.name}")
            return "shutdown"
        
        # Update database
        self.db.upsert_movie(imdb_id, str(movie_path), instance=instance)
        
        # Check for video files
        video_exts = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
        has_video = any(f.is_file() and f.suffix.lower() in video_exts for f in movie_path.iterdir())
        
        if not has_video:
            _log("WARNING", f"[{instance}] No video files found in: {movie_path} - skipping database entry")
            return "no_video_files"
        
        if scan_mode == "incomplete":
            return self._process_movie_nfo_first(movie_path, imdb_id, shutdown_event, instance=instance)
        
        # For smart/full modes: Use database-first optimization
        # TIER 1: Check database first (fastest - local lookup)
        existing = self.db.get_movie_dates(imdb_id, instance)
        _log("DEBUG", f"[{instance}] Database lookup for {imdb_id}: {existing}")
        
        # Enhanced debug for database state
        if existing:
            has_dateadded = bool(existing.get("dateadded"))
            source_value = existing.get("source")
            _log("INFO", f"[{instance}] 🔍 TIER 1 DEBUG - {imdb_id}: has_dateadded={has_dateadded}, source='{source_value}', dateadded='{existing.get('dateadded')}'")
        else:
            _log("INFO", f"[{instance}] 🔍 TIER 1 DEBUG - {imdb_id}: No database record found")
        
        # If we have complete data in database, use it and skip all other checks
        if existing and existing.get("dateadded") and existing.get("source") != "no_valid_date_source":
            _log("INFO", f"[{instance}] ✅ TIER 1 - Using complete database data for {imdb_id}: {existing['dateadded']} (source: {existing['source']})")
            dateadded, source, released = existing["dateadded"], existing["source"], existing.get("released")
            
            # Convert datetime objects to strings for NFO manager
            if hasattr(dateadded, 'isoformat'):
                dateadded = dateadded.isoformat()
            if released and hasattr(released, 'isoformat'):
                released = released.isoformat()
            
            # NFO file operations removed - database is now the single source of truth
            # (Phase 1: Remove NFO file write operations)
            
            _log("INFO", f"[{instance}] Completed processing movie: {movie_path.name} (source: {source}) [database-cached]")
            return "processed"
        else:
            _log("INFO", f"[{instance}] 🔍 TIER 1 SKIP - {imdb_id}: Database incomplete, proceeding to Tier 2")
        
        # TIER 2: Query external APIs directly (NFO layer removed in Phase 2)
        _log("INFO", f"[{instance}] 🔍 TIER 2 - No database cache, querying external APIs")

        # Fetch title/year from Radarr now so we can store them alongside dates
        radarr_client, _, _ = self._resolve_radarr(instance)
        radarr_meta = radarr_client.movie_by_imdb(imdb_id) if radarr_client else None
        title = radarr_meta.get("title") if radarr_meta else None
        year = radarr_meta.get("year") if radarr_meta else None

        # Check for shutdown signal before expensive API operations
        if shutdown_event and shutdown_event.is_set():
            _log("INFO", f"[{instance}] ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping movie processing before API calls: {movie_path.name}")
            return "shutdown"

        # TIER 3: No cached data found - determine if we should query APIs
        if webhook_mode:
            _log("INFO", f"[{instance}] Webhook processing - no cached data found, using full date decision logic")
            should_query = True  # Always query for webhooks when no cached data exists
        else:
            # Manual scan mode - determine if we should query APIs
            should_query = config.movie_poll_mode == "always"
            _log("DEBUG", f"[{instance}] Movie {imdb_id}: should_query={should_query}, poll_mode={config.movie_poll_mode}")
        
        # Use existing movie date decision logic
        # Pass NFO fallback data if available for cases where external APIs don't have import history
        nfo_fallback = locals().get('nfo_fallback_data', None)
        dateadded, source, released = self._decide_movie_dates(imdb_id, movie_path, should_query, nfo_fallback, instance=instance)
        
        # Webhook fallback: if ALL date sources fail, use current timestamp
        if webhook_mode and dateadded is None:
            local_tz = _get_local_timezone()
            current_time = datetime.now(local_tz).isoformat(timespec="seconds")
            _log("INFO", f"[{instance}] Webhook processing - all date sources failed, using current timestamp as last resort: {current_time}")
            dateadded, source = current_time, "webhook:fallback_timestamp"
        
        # If we don't have an import/download date but we have a release date, use it as dateadded
        # This ensures we save digital release dates, theatrical dates, etc. to the database
        final_dateadded = dateadded
        final_source = source
        
        if dateadded is None and released is not None:
            final_dateadded = released
            final_source = f"{source}_as_dateadded" if source else "release_date_fallback"
            _log("INFO", f"[{instance}] Using release date as dateadded: {final_dateadded} (source: {final_source})")
        
        # NFO file operations removed - database is now the single source of truth
        # (Phase 1: Remove NFO file write operations)
        
        # Skip remaining processing if no valid date found and file dates disabled
        if final_dateadded is None:
            _log("WARNING", f"[{instance}] Movie {movie_path.name} - no valid date source available, but NFO was still processed")
            self.db.upsert_movie_dates(imdb_id, released, None, source, True, title=title, year=year, instance=instance)
            return "processed"
            
        # Update dateadded and source for the rest of processing
        dateadded = final_dateadded
        source = final_source
        
        _log("DEBUG", f"[{instance}] Movie {movie_path.name} proceeding to save: dateadded={dateadded}, source={source}")
        
        # File mtime operations removed - database is now the single source of truth
        # (Phase 1: Remove NFO file write operations)
        
        _log("DEBUG", f"[{instance}] Movie processing reached file mtime section: fix_dir_mtimes={config.fix_dir_mtimes}, dateadded={dateadded}")
        
        
        # Save to database
        _log("DEBUG", f"[{instance}] About to save to database: imdb_id={imdb_id}, dateadded={dateadded}")
        try:
            self.db.upsert_movie_dates(imdb_id, released, dateadded, source, True, title=title, year=year, instance=instance)
            _log("DEBUG", f"[{instance}] Database save completed for {imdb_id}")
        except Exception as e:
            _log("ERROR", f"[{instance}] Database save failed for {imdb_id}: {e}")
            raise
        
        _log("INFO", f"[{instance}] Completed processing movie: {movie_path.name} (source: {source})")
        return "processed"
    
    def _process_movie_nfo_first(self, movie_path: Path, imdb_id: str, shutdown_event=None, instance: str = 'radarr') -> str:
        """Process movie for incomplete mode: Database-first then API (NFO checks removed in Phase 2)"""
        _log("INFO", f"[{instance}] 🔍 INCOMPLETE MODE: Checking movie for missing data: {movie_path.name}")

        if shutdown_event and shutdown_event.is_set():
            _log("INFO", f"[{instance}] ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping movie processing: {movie_path.name}")
            return "shutdown"

        existing = self.db.get_movie_dates(imdb_id, instance)

        if existing and existing.get("dateadded") and existing.get("source") != "no_valid_date_source":
            # Found in database - data is complete
            _log("INFO", f"[{instance}] ✅ Database has dateadded={existing['dateadded']}")
            dateadded, source, released = existing["dateadded"], existing["source"], existing.get("released")

            # Convert datetime objects to strings
            if hasattr(dateadded, 'isoformat'):
                dateadded = dateadded.isoformat()
            if released and hasattr(released, 'isoformat'):
                released = released.isoformat()

            _log("INFO", f"[{instance}] Completed processing movie: {movie_path.name} (source: {source}) [database-cached]")
            return "processed"

        # STEP 2: Database incomplete or missing, query APIs
        _log("DEBUG", f"[{instance}] STEP 2 - Querying APIs for missing data")
        
        # Check for shutdown signal before API calls
        if shutdown_event and shutdown_event.is_set():
            _log("INFO", f"[{instance}] ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping before API calls: {movie_path.name}")
            return "shutdown"
        
        # Handle TMDB ID fallback case
        is_tmdb_fallback = imdb_id.startswith("tmdb-")
        
        if is_tmdb_fallback:
            # TMDB fallback processing - use file modification time
            _log("INFO", f"[{instance}] 🔍 TMDB fallback processing for {imdb_id}")
            dateadded, source, released = self._get_file_mtime_date(movie_path)
            _log("INFO", f"[{instance}] Using file mtime for TMDB movie: {dateadded}")
        else:
            # Standard IMDb processing
            # Try to get digital release date from external APIs
            digital_date, digital_source = self._get_digital_release_date(imdb_id)
            
            if digital_date:
                dateadded = digital_date
                source = digital_source
                released = digital_date  # For movies, digital release is often the key date
                _log("INFO", f"[{instance}] Got digital release date from APIs: {dateadded} (source: {source})")
            else:
                # Last resort: file modification time
                dateadded, source, released = self._get_file_mtime_date(movie_path)
                _log("INFO", f"[{instance}] Using file mtime as fallback: {dateadded}")
        
        if dateadded:
            radarr_client, _, _ = self._resolve_radarr(instance)
            radarr_meta = radarr_client.movie_by_imdb(imdb_id) if radarr_client else None
            title = radarr_meta.get("title") if radarr_meta else None
            year = radarr_meta.get("year") if radarr_meta else None
            self.db.upsert_movie_dates(imdb_id, released, dateadded, source, True, title=title, year=year, instance=instance)

            _log("INFO", f"[{instance}] 🔍 INCOMPLETE MODE COMPLETE: {movie_path.name} (source: {source})")
            return "processed"
        else:
            _log("WARNING", f"[{instance}] Could not determine dateadded for movie: {movie_path.name}")
            return "error"
    
    # NFO helper methods removed in Phase 2 - database is the single source of truth

    def _decide_movie_dates(self, imdb_id: str, movie_path: Path, should_query: bool, existing: Optional[Dict], instance: str = 'radarr') -> Tuple[str, str, Optional[str]]:
        """Decide movie dates based on configuration and available data"""
        _log("DEBUG", f"[{instance}] _decide_movie_dates for {imdb_id}: should_query={should_query}, existing={existing}")

        if not should_query and existing:
            _log("DEBUG", f"[{instance}] Using existing data without querying: dateadded={existing.get('dateadded')}, source={existing.get('source')}")
            return existing["dateadded"], existing["source"], existing.get("released")

        radarr_client, _, _ = self._resolve_radarr(instance)

        # Query Radarr for movie info (database or API client)
        radarr_movie = None
        if should_query and radarr_client:
            radarr_movie = radarr_client.movie_by_imdb(imdb_id)
        
        released = None
        if radarr_movie:
            released = self._parse_date_to_iso(radarr_movie.get("inCinemas"))
        
        # Try import history first if configured
        if config.movie_priority == "import_then_digital":
            import_date, import_source = None, None
            if radarr_movie:
                movie_id = radarr_movie.get("id")
                if movie_id:
                    import_date, import_source = radarr_client.get_movie_import_date(movie_id, fallback_to_file_date=config.allow_file_date_fallback)
                    _log("INFO", f"[{instance}] Movie {imdb_id}: Radarr import result: date={import_date}, source={import_source}")
            
            # Check for special case: rename-first scenario (should prefer release dates)
            if import_source == "radarr:db.prefer_release_dates":
                _log("INFO", f"[{instance}] 🎯 Movie {imdb_id} has rename-first history - skipping import, preferring release dates")
                # Fall through to release date logic below
            # Check if we got a real import date or just file date fallback
            elif import_date and import_source != "radarr:db.file.dateAdded":
                # Convert import date to local timezone for NFO files
                local_import_date = convert_utc_to_local(import_date)
                _log("INFO", f"[{instance}] ✅ Movie {imdb_id}: Using import date {local_import_date} from {import_source}")
                return local_import_date, import_source, released
            
            # Get digital release date for comparison/fallback
            _log("INFO", f"[{instance}] 🔍 Movie {imdb_id}: Trying digital release date fallback...")
            digital_date, digital_source = self._get_digital_release_date(imdb_id)
            _log("INFO", f"[{instance}] Movie {imdb_id}: Digital release result: date={digital_date}, source={digital_source}")
            
            # If we only have file date and release date exists, prefer it if reasonable and enabled
            if import_date and import_source == "radarr:db.file.dateAdded" and digital_date and config.prefer_release_dates_over_file_dates:
                # Compare dates - prefer release date if it's reasonable
                if self._should_prefer_release_over_file_date(digital_date, digital_source, released, imdb_id):
                    _log("INFO", f"[{instance}] ✅ Movie {imdb_id}: Preferring digital release date {digital_date} over file date")
                    # When using digital release date, store it as both dateadded and released
                    return digital_date, digital_source, digital_date
                else:
                    # Convert file date to local timezone for NFO files
                    local_file_date = convert_utc_to_local(import_date)
                    _log("INFO", f"[{instance}] ✅ Movie {imdb_id}: Keeping file date {local_file_date} - digital date not reasonable")
                    return local_file_date, import_source, released
            
            # Use whichever we have
            if import_date:
                # Convert import date to local timezone for NFO files
                local_import_date = convert_utc_to_local(import_date)
                _log("INFO", f"[{instance}] ✅ Movie {imdb_id}: Using import date {local_import_date} from {import_source}")
                return local_import_date, import_source, released
            elif digital_date:
                _log("INFO", f"[{instance}] ✅ Movie {imdb_id}: Using digital release date {digital_date} from {digital_source}")
                # When using digital release date, store it as both dateadded and released
                return digital_date, digital_source, digital_date
            else:
                _log("WARNING", f"[{instance}] ⚠️ Movie {imdb_id}: No import date OR digital release date found")
        
        else:  # digital_then_import
            # Try digital release first
            digital_date, digital_source = self._get_digital_release_date(imdb_id)
            if digital_date:
                # When using digital release date, store it as both dateadded and released
                return digital_date, digital_source, digital_date
            
            # Fall back to import history
            if radarr_movie:
                movie_id = radarr_movie.get("id")
                if movie_id:
                    import_date, import_source = radarr_client.get_movie_import_date(movie_id, fallback_to_file_date=config.allow_file_date_fallback)
                    if import_date:
                        # Convert import date to local timezone for NFO files
                        local_import_date = convert_utc_to_local(import_date)
                        return local_import_date, import_source, released
        
        # Last resort: check if we have NFO fallback data (when external APIs don't have import history)
        if existing and existing.get('dateadded'):
            _log("INFO", f"[{instance}] ✅ Movie {imdb_id}: External APIs don't have import history, using NFO fallback date: {existing['dateadded']} (source: {existing['source']})")
            return existing["dateadded"], f"nfo_fallback:{existing['source']}", existing.get("released")
        
        # Last resort: file mtime (if allowed)
        if config.allow_file_date_fallback:
            return self._get_file_mtime_date(movie_path)
        else:
            _log("INFO", f"[{instance}] No valid dates found for {imdb_id} and file date fallback disabled - skipping NFO creation")
            
            # Log to failed movies debug file for troubleshooting
            self._log_failed_movie(movie_path, imdb_id, "No import date, no release date, file date fallback disabled")
            
            return None, "no_valid_date_source", None
    
    def _get_digital_release_date(self, imdb_id: str) -> Tuple[Optional[str], str]:
        """Get release date from external sources using configured priority"""
        _log("INFO", f"🔍 Calling external clients for {imdb_id}")
        _log("INFO", f"Release date priority: {config.release_date_priority}")
        _log("INFO", f"Smart validation enabled: {config.enable_smart_date_validation}")
        
        try:
            release_result = self.external_clients.get_release_date_by_priority(
                imdb_id, 
                config.release_date_priority,
                enable_smart_validation=config.enable_smart_date_validation
            )
            _log("INFO", f"External clients result for {imdb_id}: {release_result}")
            
            if release_result:
                _log("INFO", f"✅ Got release date: {release_result[0]} from {release_result[1]}")
                return release_result[0], release_result[1]
            else:
                _log("WARNING", f"❌ No release date found from external clients for {imdb_id}")
                return None, "release:none"
        except Exception as e:
            _log("ERROR", f"External clients error for {imdb_id}: {e}")
            return None, f"release:error:{str(e)}"
    
    # _get_radarr_nfo_premiered_date() removed in Phase 2 - no longer reading NFO files

    def _log_failed_movie(self, movie_path: Path, imdb_id: str, reason: str, available_countries: List[str] = None):
        """Log movies that failed to get valid dates to a debug file"""
        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            
            failed_log_path = log_dir / "failed_movies.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = f"[{timestamp}] {movie_path.name} | IMDb: {imdb_id} | Reason: {reason}"
            if available_countries:
                log_entry += f" | Available Countries: {', '.join(available_countries)}"
            log_entry += "\n"
            
            with open(failed_log_path, "a", encoding="utf-8") as f:
                f.write(log_entry)
            
            _log("INFO", f"📝 Logged failed movie to {failed_log_path}: {movie_path.name}")
            
        except Exception as e:
            _log("ERROR", f"Failed to write to failed movies log: {e}")
    
    def _get_file_mtime_date(self, movie_path: Path) -> Tuple[str, str, Optional[str]]:
        """Get date from file modification time as last resort"""
        video_exts = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
        newest_mtime = None
        
        for file_path in movie_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in video_exts:
                try:
                    mtime = file_path.stat().st_mtime
                    if newest_mtime is None or mtime > newest_mtime:
                        newest_mtime = mtime
                except Exception:
                    continue
        
        if newest_mtime:
            try:
                # Use local timezone for file modification times
                local_tz = _get_local_timezone()
                iso_date = datetime.fromtimestamp(newest_mtime, tz=local_tz).isoformat(timespec="seconds")
                return iso_date, "file:mtime", None
            except Exception:
                pass
        
        return "MANUAL_REVIEW_NEEDED", "manual_review_required", None
    
    def _should_prefer_release_over_file_date(self, release_date: str, release_source: str, theatrical_release: Optional[str], imdb_id: str) -> bool:
        """
        Decide if release date should be preferred over file date
        
        Logic:
        - For theatrical dates: Always prefer over file dates (they're authoritative)
        - For physical dates: Usually prefer over file dates  
        - For digital dates: Prefer if reasonable (not decades before theatrical)
        """
        try:
            release_dt = datetime.fromisoformat(release_date.replace("Z", "+00:00"))
            
            # Always prefer theatrical and physical releases over file dates
            if any(release_type in release_source for release_type in ["theatrical", "physical"]):
                _log("INFO", f"Release date {release_date} ({release_source}) for {imdb_id}, preferring over file date")
                return True
            
            # If we have theatrical release date, compare digital against it
            if theatrical_release:
                theatrical_dt = datetime.fromisoformat(theatrical_release.replace("Z", "+00:00"))
                year_diff = release_dt.year - theatrical_dt.year
                
                # If digital is more than 10 years before theatrical, it's probably wrong
                if year_diff < -10:
                    _log("INFO", f"Release date {release_date} is {abs(year_diff)} years before theatrical {theatrical_release} for {imdb_id}, using file date instead")
                    return False
                    
                # If digital is within reasonable range (theatrical to +20 years), use it
                if -2 <= year_diff <= 20:
                    _log("INFO", f"Release date {release_date} is reasonable for {imdb_id} (theatrical: {theatrical_release}), preferring over file date")
                    return True
            
            # If no theatrical date, use digital if it's not absurdly old
            if release_dt.year >= 1990:  # Reasonable minimum for digital releases
                _log("INFO", f"Release date {release_date} seems reasonable for {imdb_id}, preferring over file date")
                return True
                
            _log("INFO", f"Release date {release_date} seems too old for {imdb_id}, using file date instead")
            return False
            
        except Exception as e:
            _log("WARNING", f"Error comparing dates for {imdb_id}: {e}")
            return False
    
    def _parse_date_to_iso(self, date_str: str) -> Optional[str]:
        """Parse date string to ISO format"""
        if not date_str:
            return None
        try:
            if len(date_str) == 10 and date_str[4] == "-":
                dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            return dt.isoformat(timespec="seconds")
        except Exception:
            return None