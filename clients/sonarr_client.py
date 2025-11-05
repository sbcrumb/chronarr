#!/usr/bin/env python3
"""
Enhanced Sonarr API client for TV show metadata and episode management
"""
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError

from core.logging import _log


class SonarrClient:
    """Enhanced Sonarr API client for TV series and episode management"""
    
    def __init__(self, base_url: str, api_key: str, timeout: int = 45, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = max(0, retries)
        self.enabled = bool(self.base_url and self.api_key)

    def _get(self, path: str, params: Dict[str, Any] = None) -> Optional[Any]:
        """Make GET request to Sonarr API with retries"""
        if not self.enabled:
            return None
            
        url = f"{self.base_url}/api/v3{path}"
        if params:
            url += "?" + urlencode(params)
            
        headers = {"X-Api-Key": self.api_key}
        
        for attempt in range(self.retries):
            try:
                _log("DEBUG", f"Sonarr API Request: {url}")
                req = UrlRequest(url, headers=headers)
                
                with urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read().decode("utf-8")
                    result = json.loads(data) if data else None
                    return result
                    
            except HTTPError as e:
                if e.code == 401:
                    _log("ERROR", "Sonarr authentication failed - check API key")
                    return None
                elif e.code == 429:
                    wait_time = (attempt + 1) * 2
                    _log("WARNING", f"Sonarr rate limited, waiting {wait_time}s (attempt {attempt+1}/{self.retries})")
                    time.sleep(wait_time)
                else:
                    _log("WARNING", f"Sonarr HTTP {e.code} error on attempt {attempt+1}/{self.retries}: {e.reason}")
                    
            except Exception as e:
                _log("WARNING", f"Sonarr API attempt {attempt+1}/{self.retries} failed: {e}")
            
            if attempt < self.retries - 1:
                time.sleep(0.5 * (attempt + 1))
        
        _log("ERROR", f"Sonarr API failed after {self.retries} attempts: {url}")
        return None

    def series_by_imdb(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """Find series by IMDb ID using lookup endpoint"""
        search_term = f"imdbid:{imdb_id}"
        _log("DEBUG", f"Searching Sonarr with term: {search_term}")
        
        result = self._get("/series/lookup", {"term": search_term})
        if not result:
            _log("WARNING", f"No results from Sonarr lookup for: {search_term}")
            return None
            
        _log("DEBUG", f"Sonarr lookup returned {len(result)} results")
        
        # Log all results for debugging
        for i, series in enumerate(result):
            series_imdb = series.get("imdbId", "")
            series_title = series.get("title", "")
            series_id = series.get("id", "")
            _log("DEBUG", f"Result {i+1}: Title='{series_title}', IMDb='{series_imdb}', ID={series_id}")
        
        # Find exact IMDb match (case insensitive)
        target_imdb = imdb_id.lower()
        for series in result:
            series_imdb = (series.get("imdbId") or "").lower()
            if series_imdb == target_imdb:
                _log("INFO", f"Found exact IMDb match: {series.get('title')} (ID: {series.get('id')})")
                return series
                
        # Try partial match as fallback
        for series in result:
            series_imdb = (series.get("imdbId") or "").lower()
            if target_imdb in series_imdb or series_imdb in target_imdb:
                _log("WARNING", f"Found partial IMDb match: {series.get('title')} (Expected: {imdb_id}, Found: {series.get('imdbId')})")
                return series
        
        _log("WARNING", f"No IMDb match found in {len(result)} results for {imdb_id}")
        return None

    def series_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Search for series by title as fallback when IMDb lookup fails"""
        _log("DEBUG", f"Searching Sonarr by title: {title}")
        
        result = self._get("/series/lookup", {"term": title})
        if not result:
            _log("WARNING", f"No results from Sonarr title search for: {title}")
            return None
            
        _log("DEBUG", f"Sonarr title search returned {len(result)} results")
        
        title_lower = title.lower()
        
        # Look for exact title match
        for series in result:
            series_title = (series.get("title") or "").lower()
            if series_title == title_lower:
                _log("INFO", f"Found exact title match: {series.get('title')} (ID: {series.get('id')})")
                return series
        
        # Look for partial title match
        for series in result:
            series_title = (series.get("title") or "").lower()
            if title_lower in series_title or series_title in title_lower:
                _log("INFO", f"Found partial title match: '{series.get('title')}' for search '{title}' (ID: {series.get('id')})")
                return series
        
        _log("WARNING", f"No title match found for: {title}")
        return None

    def get_all_series(self) -> List[Dict[str, Any]]:
        """Get all series from Sonarr"""
        return self._get("/series") or []

    def series_by_imdb_direct(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """Find series by scanning all series for IMDb match (slower but more reliable)"""
        _log("DEBUG", f"Direct series lookup for IMDb: {imdb_id}")
        all_series = self.get_all_series()
        
        target_imdb = imdb_id.lower()
        for series in all_series:
            series_imdb = (series.get("imdbId") or "").lower()
            if series_imdb == target_imdb:
                _log("INFO", f"Found series via direct lookup: {series.get('title')} (ID: {series.get('id')})")
                return series
        
        _log("WARNING", f"No series found with IMDb ID via direct lookup: {imdb_id}")
        return None

    def get_series_by_id(self, series_id: int) -> Optional[Dict[str, Any]]:
        """Get series information by Sonarr series ID"""
        return self._get(f"/series/{series_id}")

    def episodes_for_series(self, series_id: int) -> List[Dict[str, Any]]:
        """Get all episodes for a series"""
        return self._get("/episode", {"seriesId": series_id}) or []

    def episode_file(self, episode_file_id: int) -> Optional[Dict[str, Any]]:
        """Get episode file details"""
        return self._get(f"/episodefile/{episode_file_id}")
    
    def get_episode_import_history(self, episode_id: int) -> Optional[str]:
        """
        Get the original import date from history with enhanced detection.
        Focuses on finding the earliest REAL import, not upgrades.
        """
        all_records = []
        page = 1
        page_size = 100
        
        # Collect all history records for this episode
        while True:
            history = self._get("/history", {
                "episodeId": episode_id, 
                "sortKey": "date", 
                "sortDir": "asc",
                "page": page,
                "pageSize": page_size
            })
            
            if not history:
                break
                
            records = history.get("records", []) if isinstance(history, dict) else []
            if not records:
                break
                
            all_records.extend(records)
            
            if len(records) < page_size:
                break
                
            page += 1
            if page > 10:  # Safety valve
                break
        
        _log("DEBUG", f"Got {len(all_records)} history records for episode {episode_id}")
        
        # Categorize events
        import_events = []
        grabbed_events = []
        rename_events = []
        
        for event in all_records:
            event_type = event.get("eventType", "").lower()
            date = event.get("date")
            
            if not date:
                continue
            
            _log("DEBUG", f"History event: {event_type} at {date}")
            
            if event_type == "downloadfolderimported":
                import_events.append({"date": date, "event": event})
            elif event_type == "grabbed":
                grabbed_events.append({"date": date, "event": event})
            elif event_type == "episodefilerenamed":
                rename_events.append({"date": date, "event": event})
        
        # Use the earliest real import event
        if import_events:
            earliest_import = min(import_events, key=lambda x: x["date"])
            import_date = earliest_import["date"]
            _log("INFO", f"Found import date: {import_date} for episode {episode_id}")
            
            # Check chronological order of events
            if rename_events:
                earliest_rename = min(rename_events, key=lambda x: x["date"])
                rename_date = earliest_rename["date"]
                
                try:
                    import_dt = datetime.fromisoformat(import_date.replace("Z", "+00:00"))
                    rename_dt = datetime.fromisoformat(rename_date.replace("Z", "+00:00"))
                    
                    # If import happened BEFORE rename, it's valid original import
                    if import_dt <= rename_dt:
                        _log("INFO", f"Import {import_date} happened before/during rename {rename_date} - using import date")
                        return import_date
                    
                    # If rename happened BEFORE import - always use aired date fallback
                    else:
                        _log("WARNING", f"Rename {rename_date} happened before import {import_date} - using aired date fallback")
                        return None  # Trigger aired date fallback
                        
                except Exception as e:
                    _log("DEBUG", f"Error comparing dates: {e}")
            
            return import_date
        
        # Fallback to grab event
        if grabbed_events:
            earliest_grab = min(grabbed_events, key=lambda x: x["date"])
            _log("WARNING", f"No import events, using grab date: {earliest_grab['date']} for episode {episode_id}")
            return earliest_grab["date"]
        
        _log("WARNING", f"No reliable import events found for episode {episode_id} - should use air date instead")
        return None


if __name__ == "__main__":
    # Test the client
    import os
    
    base_url = os.environ.get("SONARR_URL", "")
    api_key = os.environ.get("SONARR_API_KEY", "")
    
    if base_url and api_key:
        client = SonarrClient(base_url, api_key)
        
        # Test with a known series
        test_imdb = "tt2085059"  # Example
        series = client.series_by_imdb(test_imdb)
        
        if series:
            series_id = series.get("id")
            print(f"Found series: {series.get('title')} (ID: {series_id})")
            
            # Get episodes
            episodes = client.episodes_for_series(series_id)
            print(f"Found {len(episodes)} episodes")
            
            # Test import date for first episode
            if episodes:
                first_episode = episodes[0]
                episode_id = first_episode.get("id")
                import_date = client.get_episode_import_history(episode_id)
                print(f"First episode import date: {import_date}")
        else:
            print(f"Series not found: {test_imdb}")
    else:
        print("Please set SONARR_URL and SONARR_API_KEY environment variables for testing")