#!/usr/bin/env python3
"""Enhanced Radarr API client with improved import date detection"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlencode, urljoin
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError

from core.logging import _log

# Import path mapper for proper path handling
try:
    from core.path_mapper import path_mapper
except ImportError:
    # Fallback for standalone testing
    class DummyPathMapper:
        def analyze_import_source_path(self, path):
            return "/downloads/" in path.lower(), "basic_check"
            
        def is_download_path(self, path):
            return "/downloads/" in str(path).lower() or "/completed/" in str(path).lower()
            
    path_mapper = DummyPathMapper()

# Import database client for enhanced performance
try:
    from clients.radarr_db_client import RadarrDbClient
except ImportError:
    RadarrDbClient = None


class RadarrClient:
    """Enhanced Radarr API client with improved import date detection"""
    
    # Radarr History API event types (HistoryEventType enum)
    # From: https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/History/HistoryEventType.cs
    EVENT_TYPE_GRABBED = 1    # Movie was grabbed from indexer
    EVENT_TYPE_IMPORTED = 3   # Movie was imported to final library
    EVENT_TYPE_FAILED = 4     # Download or import failed
    EVENT_TYPE_RETAGGED = 6   # Files were tagged
    EVENT_TYPE_RENAMED = 8    # Files were renamed

    # Event types that indicate real imports
    REAL_IMPORT_EVENT_TYPES = [EVENT_TYPE_IMPORTED]  # Only trust actual "imported" events
    
    # These are now handled by path_mapper, but keeping for backward compatibility
    DOWNLOAD_PATH_INDICATORS = [
        '/downloads/', '/download/', '/completed/', '/importing/',
        '/nzbs/', '/torrents/', '/temp/', '/tmp/',
        'sabnzbd', 'nzbget', 'deluge', 'qbittorrent', 'transmission',
        'usenet', 'torrent', 'radarr', 'completed', 'processing'
    ]
    
    def __init__(self, base_url: str, api_key: str, timeout: int = 45, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = max(0, retries)
        
        # Initialize database client - REQUIRED for operation
        self.db_client = None
        if RadarrDbClient:
            try:
                self.db_client = RadarrDbClient.from_env()
                if self.db_client:
                    _log("INFO", "✅ DATABASE ONLY MODE: Direct database access enabled")
                else:
                    _log("ERROR", "❌ DATABASE ONLY MODE: Database configuration required - API mode disabled")
            except Exception as e:
                _log("ERROR", f"❌ DATABASE ONLY MODE: Failed to initialize database client: {e}")
                self.db_client = None
        else:
            _log("ERROR", "❌ DATABASE ONLY MODE: RadarrDbClient not available - check dependencies")

    def _get(self, path: str, params: Dict[str, Any] = None) -> Optional[Any]:
        """Make GET request to Radarr API with retries"""
        if not self.api_key:
            return None
            
        attempt = 0
        last_err = None
        
        while attempt <= self.retries:
            try:
                params = params or {}
                params["apikey"] = self.api_key
                url = urljoin(f"{self.base_url}/", path.lstrip("/"))
                
                if params:
                    url = url + ("&" if "?" in url else "?") + urlencode(params)
                
                _log("DEBUG", f"Radarr API Request: {url}")
                req = UrlRequest(url, headers={"Accept": "application/json"})
                
                with urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read().decode("utf-8")
                    result = json.loads(data)
                    return result
                    
            except (URLError, HTTPError, json.JSONDecodeError) as e:
                last_err = e
                _log("DEBUG", f"Radarr API attempt {attempt + 1} failed: {e}")
                time.sleep(min(2 ** attempt, 5))  # Exponential backoff
                attempt += 1
        
        _log("WARNING", f"Radarr GET {path} failed after {self.retries + 1} attempts: {last_err}")
        return None

    def movie_by_imdb(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """Find movie by IMDb ID - DATABASE ONLY mode"""
        imdb_id = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"
        _log("DEBUG", f"Looking up movie by IMDb ID: {imdb_id}")
        
        # Database required - no API fallback
        if self.db_client:
            try:
                movie = self.db_client.get_movie_by_imdb(imdb_id)
                if movie:
                    _log("INFO", f"✅ Found via database: {movie.get('title')} (ID: {movie.get('id')})")
                    return movie
                else:
                    _log("WARNING", f"Movie not found in database for IMDb ID: {imdb_id}")
                    return None
            except Exception as e:
                _log("ERROR", f"Database lookup failed: {e}")
                return None
        
        # No database client available
        _log("ERROR", "Database client required for movie lookup - API mode disabled")
        return None

    def _analyze_event_for_import(self, event: Dict[str, Any], movie_info: Dict[str, Any] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Analyze a history event to determine if it's a real import.
        
        Args:
            event: The history event to analyze
            movie_info: Optional movie information to validate paths against
        
        Returns:
            (is_real_import, reason, date_iso)
        """
        event_type = event.get("eventType")
        date_str = event.get("date")
        event_data = event.get("data", {})
        
        # Parse date
        date_iso = None
        if date_str:
            try:
                date_iso = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
            except Exception:
                date_iso = None
        
        if not date_iso:
            return False, "no_valid_date", None
            
        # Convert event type to int if needed
        try:
            event_type_int = int(event_type) if isinstance(event_type, str) and event_type.isdigit() else event_type
        except (ValueError, TypeError):
            event_type_int = None

        # Check if event type indicates import
        if event_type_int not in self.REAL_IMPORT_EVENT_TYPES:
            return False, f"event_type_not_import({event_type})", date_iso
        
        # Get all possible source paths/titles
        source_items = []
        
        # Get both sourcePath and importedPath if available
        if event_data:
            for key in ['sourcePath', 'droppedPath', 'path', 'sourceTitle', 'importedPath']:
                if event_data.get(key):
                    source_items.append(event_data[key])
                    
        # Also check event root for these fields
        for key in ['sourcePath', 'sourceTitle', 'importedPath']:
            if event.get(key):
                source_items.append(event[key])
        
        # Clean up and make unique
        source_items = [str(s).lower().strip() for s in source_items if s]
        source_items = list(set(source_items))  # Remove duplicates
        
        if not source_items:
            return False, "no_source_paths", date_iso
            
        # If we have movie info, look for title/year match
        if movie_info:
            movie_title = movie_info.get('title', '').lower().replace(':', '.').replace(' ', '.')
            movie_year = str(movie_info.get('year', ''))
            
            for source in source_items:
                # Clean up source text for comparison
                source_clean = source.replace(' ', '.').replace('_', '.').replace('-', '.')
                
                # Check if both title and year are in the source
                if movie_title and movie_year:
                    if movie_title in source_clean and movie_year in source_clean:
                        _log("DEBUG", f"✅ Match found - Title: {movie_title}, Year: {movie_year}")
                        return True, "matched_title_and_year", date_iso
                        
                # Also check for downloads path as secondary validation
                if path_mapper.is_download_path(source):
                    _log("DEBUG", f"Source is from downloads: {source}")
                    return True, "from_downloads_path", date_iso
                    
            _log("DEBUG", f"⚠️ No match found in sources: {source_items}")
            return False, "no_title_year_match", date_iso
        
        # Fallback to basic path validation if no movie info
        for source in source_items:
            if path_mapper.is_download_path(source):
                return True, "basic_download_path_match", date_iso
                
        return False, "no_download_path_match", date_iso

    def earliest_import_event_optimized(self, movie_id: int) -> Optional[str]:
        """
        Find earliest real import event with optimized querying.
        Stops as soon as we find valid import events instead of loading everything.
        """
        _log("INFO", f"Finding earliest import for movie_id {movie_id}")
        
        # Get movie info for path validation
        movie_info = self._get(f"/api/v3/movie/{movie_id}")
        if not movie_info or not isinstance(movie_info, dict):
            _log("ERROR", f"Could not get movie info for ID {movie_id}")
            return None
        
        earliest_real_import = None
        first_grab = None
        page = 1
        page_size = 50  # Smaller pages for faster iteration
        total_processed = 0
        
        while page <= 20:  # Safety limit
            # Get history in chronological order
            data = self._get("/api/v3/history", {
                "movieId": str(movie_id),
                "page": page,
                "pageSize": page_size,
                "sortKey": "date",
                "sortDirection": "ascending"
            })
            
            if not data:
                break
                
            items = data if isinstance(data, list) else data.get("records", [])
            if not items:
                break
            
            _log("DEBUG", f"Page {page}: Processing {len(items)} events")
            
            for event in items:
                total_processed += 1
                event_type = event.get("eventType")
                if not event_type:
                    continue
                    
                # Convert event type to int or handle string types
                try:
                    if isinstance(event_type, str):
                        # Map string event types to numeric values
                        string_to_numeric = {
                            "grabbed": self.EVENT_TYPE_GRABBED,
                            "downloadFolderImported": self.EVENT_TYPE_IMPORTED,
                            "movieFileImported": self.EVENT_TYPE_IMPORTED,
                            "downloadFailed": self.EVENT_TYPE_FAILED,
                            "movieFileRenamed": self.EVENT_TYPE_RENAMED,
                            "movieFileDeleted": 5  # Not in our constants but common
                        }
                        event_type = string_to_numeric.get(event_type, 0)
                    else:
                        event_type = int(event_type)
                except (ValueError, TypeError):
                    _log("DEBUG", f"Unknown event type: {event_type}")
                    continue
                
                # Check for grab events (type 1) - but validate it's a real download
                if event_type == self.EVENT_TYPE_GRABBED and not first_grab:
                    if event.get("date"):
                        try:
                            # Get event data to check if this is a real grab with download info
                            event_data = event.get("data", {})
                            if isinstance(event_data, str):
                                try:
                                    event_data = json.loads(event_data)
                                except (json.JSONDecodeError, AttributeError):
                                    event_data = {}
                            
                            # Check if this grab has actual download/indexer info
                            source_title = event_data.get("sourceTitle", "")
                            indexer = event_data.get("indexer", "")
                            
                            # Only count grabs that have actual download metadata
                            if source_title or indexer:
                                first_grab = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
                                _log("DEBUG", f"Found real grab event with source '{source_title}' from '{indexer}' at {first_grab}")
                            else:
                                _log("DEBUG", f"Skipping grab event without download info at {event.get('date')}")
                        except Exception:
                            pass
                
                # Only process import events (type 3)
                if event_type != self.EVENT_TYPE_IMPORTED:
                    continue
                    
                # Get imported path from event data
                imported_path = None
                event_data = event.get("data", {})
                
                # Handle both string and dict data
                if isinstance(event_data, str):
                    try:
                        event_data = json.loads(event_data)
                    except (json.JSONDecodeError, AttributeError) as e:
                        _log("DEBUG", f"Failed to parse event data JSON: {e}")
                        continue
                elif not isinstance(event_data, dict):
                    continue
                
                imported_path = event_data.get("importedPath", "")
                if not imported_path:
                    continue
                    
                imported_path = imported_path.lower()
                    
                movie_imdb = (movie_info.get("imdbId", "") or "").lower()
                movie_title = (movie_info.get("title", "") or "").lower()
                movie_year = str(movie_info.get("year", ""))
                
                # First try IMDb ID match
                # First try IMDb ID match
                if movie_imdb and (
                    f"[imdb-{movie_imdb}]" in imported_path or
                    f"[{movie_imdb}]" in imported_path or
                    movie_imdb in imported_path
                ):
                    _log("INFO", f"Found potential IMDb match in {event_type} event: {imported_path}")
                    date_iso = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
                    _log("INFO", f"✅ FOUND IMPORT: exact IMDb match at {date_iso}")
                    earliest_real_import = date_iso
                    break

                # Then try title/year match with fuzzy path cleaning
                if movie_title and movie_year:
                    # Clean strings for comparison
                    clean_title = movie_title.replace(" ", ".").replace(":", ".").replace("-", ".").replace("_", ".").lower()
                    clean_path = imported_path.replace(" ", ".").replace("-", ".").replace("_", ".").replace("[", "").replace("]", "").lower()
                    
                    # Look for both title and year in the path
                    if clean_title in clean_path and movie_year in clean_path:
                        date_iso = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
                        _log("INFO", f"Found potential title/year match for event type {event_type}: {clean_title} ({movie_year})")
                        _log("INFO", f"✅ FOUND IMPORT at {date_iso}")
                        earliest_real_import = date_iso
                        break
                            
                # Fallback to normal import analysis
                is_real, reason, date_iso = self._analyze_event_for_import(event, movie_info)
                if is_real and date_iso:
                    source_path = (event.get("data", {}).get("sourcePath", "") or 
                                 event.get("data", {}).get("droppedPath", "") or 
                                 event.get("sourcePath", "") or
                                 event.get("data", {}).get("importedPath", "") or
                                 event.get("importedPath", "") or "").lower()
                    
                    if source_path:
                        # Check for path match
                        movie_imdb = (movie_info.get("imdbId", "") or "").lower()
                        if movie_imdb and (
                            f"[imdb-{movie_imdb}]" in source_path or
                            f"[{movie_imdb}]" in source_path or
                            movie_imdb in source_path
                        ):
                            _log("INFO", f"✅ FOUND IMPORT: IMDb match in path at {date_iso}")
                            earliest_real_import = date_iso
                            break
                        
                        # Check for title/year match
                        movie_title = (movie_info.get("title", "") or "").lower().replace(":", ".").replace(" ", ".")
                        movie_year = str(movie_info.get("year", ""))
                        if movie_title and movie_year and movie_title in source_path and movie_year in source_path:
                            _log("INFO", f"✅ FOUND IMPORT: Title/year match at {date_iso}")
                            earliest_real_import = date_iso
                            break
                elif event_type == 3:
                    _log("DEBUG", f"⚠️  Skipped import event: {reason}")
            
            # If we found a real import, no need to continue
            if earliest_real_import:
                break
                
            # If we got less than page size, we've seen all events
            if len(items) < page_size:
                break
                
            page += 1
        
        _log("INFO", f"Processed {total_processed} events across {page-1} pages")
        
        if earliest_real_import:
            _log("INFO", f"✅ Using earliest real import: {earliest_real_import}")
            return earliest_real_import
            
        if first_grab:
            _log("WARNING", f"⚠️  No real imports found, using grab date: {first_grab}")
            return first_grab
            
        _log("ERROR", f"❌ No import or grab events found for movie_id {movie_id}")
        return None

    def movie_files(self, movie_id: int) -> List[Dict[str, Any]]:
        """Get movie files for a movie - DATABASE ONLY mode"""
        if self.db_client:
            _log("INFO", "Using database for movie files lookup")
            # Database handles this internally in get_movie_file_date()
            return []
        
        _log("ERROR", "Database client required for movie files - API mode disabled")
        return []

    def earliest_file_dateadded(self, movie_id: int) -> Optional[str]:
        """Get earliest file dateAdded - DATABASE ONLY mode"""
        if self.db_client:
            try:
                return self.db_client.get_movie_file_date(movie_id)
            except Exception as e:
                _log("ERROR", f"Database file date query failed: {e}")
                return None
        
        _log("ERROR", "Database client required for file dates - API mode disabled")
        return None

    def get_movie_import_date(self, movie_id: int, fallback_to_file_date: bool = True) -> Tuple[Optional[str], str]:
        """
        Get the best import date for a movie - DATABASE ONLY mode.
        
        Returns:
            (date_iso, source_description)
        """
        # Database required - no API fallback
        if self.db_client:
            try:
                date_iso, source = self.db_client.get_movie_import_date_optimized(movie_id, fallback_to_file_date)
                if date_iso:
                    return date_iso, source
                else:
                    _log("WARNING", f"No import date found in database for movie_id {movie_id}")
                    return None, "radarr:db.no_date_found"
            except Exception as e:
                _log("ERROR", f"Database import date query failed: {e}")
                return None, "radarr:db.error"
        
        # No database client available
        _log("ERROR", "Database client required for import date detection - API mode disabled")
        return None, "radarr:db.not_configured"

    def _get_earliest_import_date(self, movie_id: int, movie_info: Dict) -> Optional[str]:
        """Get the earliest import date from Radarr history."""
        _log("INFO", f"Finding earliest import for movie_id {movie_id}")
        
        earliest_real_import = None
        earliest_grab_date = None
        page = 1
        page_size = 50
        total_events = 0

        # Get full movie history
        while True:
            # Get page of history
            history_data = self._get_movie_history_page(movie_id, page, page_size)
            if not history_data:
                break
            
            # Process events on this page
            for event in history_data:
                event_type = event.get("eventType")
                if not event_type:
                    continue
                
                # Parse event date
                event_date = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
                
                # Track earliest grab date as fallback (EventType 1)
                if event_type == 1 and not earliest_grab_date:
                    earliest_grab_date = event_date
                    _log("DEBUG", f"Found first grab event at {earliest_grab_date}")
                    continue
                
                # Look for import events (EventType 3)
                if event_type == 3:
                    try:
                        data = json.loads(event.get("data", "{}"))
                        if data.get("importedPath"):
                            _log("INFO", f"✅ FOUND IMPORT at {event_date}")
                            earliest_real_import = event_date
                            break
                    except (json.JSONDecodeError, AttributeError):
                        continue
            
            # Break if we found an import
            if earliest_real_import:
                break

            total_events += len(history_data)
            page += 1

        _log("INFO", f"Processed {total_events} events across {page}")

        if earliest_real_import:
            return earliest_real_import
        if earliest_grab_date:
            _log("WARNING", f"⚠️  No EventType 3 (import) found, using grab date: {earliest_grab_date}")
            return earliest_grab_date
        return None

    def _get_movie_history_page(self, movie_id: int, page: int, page_size: int) -> List[Dict[str, Any]]:
        """Get a page of movie history."""
        data = self._get("/api/v3/history", {
            "movieId": str(movie_id),
            "page": page,
            "pageSize": page_size,
            "sortKey": "date",
            "sortDirection": "ascending"
        })
        return data if isinstance(data, list) else data.get("records", [])