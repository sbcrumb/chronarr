#!/usr/bin/env python3
"""
External API clients for TMDB, OMDb, and Jellyseerr
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlencode, quote
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError

from core.logging import _log


def _get_json(url: str, timeout: int = 20, headers: Dict[str, str] = None, suppress_404: bool = False) -> Optional[Dict[str, Any]]:
    """Make GET request and return JSON"""
    try:
        req = UrlRequest(url, headers=headers or {"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        # Handle specific HTTP errors more gracefully
        if suppress_404 and e.code in [400, 404]:
            _log("DEBUG", f"TVDB API: {url} - item not found (HTTP {e.code}) - this is expected")
            return None
        else:
            _log("WARNING", f"GET {url} failed: HTTP Error {e.code}: {e.reason}")
            return None
    except Exception as e:
        _log("WARNING", f"GET {url} failed: {e}")
        return None


def _parse_date_to_iso(date_str: str) -> Optional[str]:
    """Parse various date formats to ISO string"""
    if not date_str or date_str == "N/A":
        return None
    try:
        if len(date_str) == 10 and date_str[4] == "-":  # YYYY-MM-DD
            dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.isoformat(timespec="seconds")
    except Exception:
        return None


class TVDBClient:
    """The TV Database API client for IMDB to TVDB ID conversion"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("TVDB_API_KEY", "")
        self.base_url = "https://api4.thetvdb.com/v4"
        self._token = None
        self._token_expires = 0
    
    def _get_token(self) -> Optional[str]:
        """Get TVDB auth token (cached)"""
        if not self.api_key:
            _log("DEBUG", "TVDB: No API key provided")
            return None
            
        if time.time() < self._token_expires and self._token:
            return self._token
            
        try:
            _log("DEBUG", f"TVDB: Authenticating with API key: {self.api_key[:8]}...")
            req = UrlRequest(
                f"{self.base_url}/login",
                data=json.dumps({"apikey": self.api_key}).encode('utf-8'),
                headers={"Content-Type": "application/json"}
            )
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                _log("DEBUG", f"TVDB login response: {data}")
                if data.get("status") == "success":
                    self._token = data["data"]["token"]
                    self._token_expires = time.time() + 3600  # 1 hour
                    _log("INFO", f"✅ TVDB: Authentication successful")
                    return self._token
                else:
                    _log("WARNING", f"TVDB login failed: {data}")
        except Exception as e:
            _log("WARNING", f"TVDB login failed: {e}")
        return None
    
    def imdb_to_tvdb_series_id(self, imdb_id: str) -> Optional[str]:
        """Convert IMDB ID to TVDB series ID using TVDB v4 API"""
        token = self._get_token()
        if not token:
            return None
            
        try:
            # Try the official v4 search endpoint first
            # According to docs: /search?query=imdb_id&type=series
            url = f"{self.base_url}/search?query={imdb_id}&type=series&meta=translations"
            headers = {"Authorization": f"Bearer {token}"}
            
            _log("DEBUG", f"TVDB: Searching for {imdb_id} using /search endpoint")
            data = _get_json(url, headers=headers, suppress_404=True)
            
            if data and data.get("status") == "success" and data.get("data"):
                series_list = data["data"]
                _log("DEBUG", f"TVDB search response: found {len(series_list)} results")
                
                # Look for exact IMDB match in results
                for series in series_list:
                    # Check if this series has the IMDB ID we're looking for
                    remote_ids = series.get("remote_ids", [])
                    for remote in remote_ids:
                        if (remote.get("source_name") == "IMDB" and 
                            remote.get("remote_id") == imdb_id):
                            tvdb_id = series.get("tvdb_id") or series.get("id")
                            if tvdb_id:
                                _log("INFO", f"✅ TVDB: Found series {imdb_id} → {tvdb_id}")
                                return str(tvdb_id)
                
                # If no exact match, try the first result if it looks promising
                if series_list:
                    first_result = series_list[0]
                    tvdb_id = first_result.get("tvdb_id") or first_result.get("id")
                    if tvdb_id:
                        _log("INFO", f"✅ TVDB: Found series {imdb_id} → {tvdb_id} (first result)")
                        return str(tvdb_id)
            
            # If search didn't work, try the legacy remoteid endpoint
            _log("DEBUG", f"TVDB: Trying legacy remoteid endpoint for {imdb_id}")
            url = f"{self.base_url}/search/remoteid?remoteId={imdb_id}&type=series"
            data = _get_json(url, headers=headers, suppress_404=True)
            
            if data and data.get("status") == "success" and data.get("data"):
                series_list = data["data"]
                if series_list and len(series_list) > 0:
                    tvdb_id = series_list[0].get("id")
                    if tvdb_id:
                        _log("INFO", f"✅ TVDB: Found series {imdb_id} → {tvdb_id} (legacy endpoint)")
                        return str(tvdb_id)
            
            # If we get here, the series wasn't found in TVDB
            _log("DEBUG", f"TVDB: No series found for IMDb {imdb_id} (not available in TVDB)")
            
        except Exception as e:
            _log("WARNING", f"TVDB API error for {imdb_id}: {e}")
        
        return None


class TMDBClient:
    """The Movie Database API client"""
    
    def __init__(self, api_key: str = None, primary_country: str = "US"):
        self.api_key = api_key or os.environ.get("TMDB_API_KEY", "")
        self.primary_country = primary_country.upper()
        self.enabled = bool(self.api_key)
    
    def _get(self, path: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Make GET request to TMDB API"""
        if not self.enabled:
            return None
        
        params = params or {}
        params["api_key"] = self.api_key
        url = f"https://api.themoviedb.org/3{path}?{urlencode(params)}"
        return _get_json(url, timeout=20)
    
    def find_by_imdb(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """Find movie by IMDb ID"""
        result = self._get(f"/find/{quote(imdb_id)}", {"external_source": "imdb_id"})
        if result and result.get("movie_results"):
            return result["movie_results"][0]
        return None
    
    def get_movie_details(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed movie information"""
        return self._get(f"/movie/{tmdb_id}")
    
    def get_digital_release_date(self, imdb_id: str) -> Optional[str]:
        """Get digital release date for a movie"""
        _log("INFO", f"🔍 TMDB: Looking for digital release date for {imdb_id}")
        movie = self.find_by_imdb(imdb_id)
        if not movie:
            _log("WARNING", f"❌ TMDB: Movie not found for {imdb_id}")
            return None
        
        tmdb_id = movie.get("id")
        _log("INFO", f"✅ TMDB: Found movie ID {tmdb_id} for {imdb_id}")
        if not tmdb_id:
            return None
        
        release_dates = self._get(f"/movie/{tmdb_id}/release_dates")
        if not release_dates:
            _log("WARNING", f"❌ TMDB: No release dates data for movie {tmdb_id}")
            return None
        
        _log("INFO", f"🔍 TMDB: Got release dates data, looking for {self.primary_country} digital releases")
        
        # Debug: Show all available countries
        countries = [entry.get("iso_3166_1") for entry in release_dates.get("results", [])]
        _log("INFO", f"📍 TMDB: Available countries: {countries}")
        
        for entry in release_dates.get("results", []):
            country = entry.get("iso_3166_1", "").upper()
            if country != self.primary_country:
                continue
                
            _log("INFO", f"🎯 TMDB: Found {country} release data")
            releases = entry.get("release_dates", [])
            _log("INFO", f"🎬 TMDB: Release types available: {[r.get('type') for r in releases]}")
            
            # Collect all available releases with their types and dates
            available_releases = []
            for release in releases:
                release_type = release.get("type")
                release_date = release.get("release_date")
                _log("INFO", f"📅 TMDB: Type {release_type}, Date: {release_date}")
                
                if release_date:
                    parsed_date = _parse_date_to_iso(release_date)
                    if parsed_date:
                        available_releases.append((release_type, parsed_date))
            
            # Apply TMDB release type priority order
            tmdb_priority = self._get_tmdb_type_priority()
            for preferred_type in tmdb_priority:
                for release_type, parsed_date in available_releases:
                    if release_type == preferred_type:
                        release_type_names = {
                            1: "Premiere", 2: "Limited Theatrical", 3: "Theatrical", 
                            4: "Digital", 5: "Physical", 6: "TV Premiere"
                        }
                        type_name = release_type_names.get(release_type, f"Type {release_type}")
                        _log("INFO", f"✅ TMDB: Selected {type_name} release date: {parsed_date} (priority: {tmdb_priority})")
                        return parsed_date
        
        _log("WARNING", f"❌ TMDB: No release dates found for {imdb_id} in {self.primary_country}")
        
        # Fallback: First try English-speaking countries, then any country
        english_speaking_countries = {"GB", "CA", "AU", "NZ", "IE"}  # UK, Canada, Australia, New Zealand, Ireland
        
        # First pass: Try English-speaking countries
        _log("INFO", f"🇺🇸 TMDB: Trying English-speaking countries fallback for {imdb_id}")
        for entry in release_dates.get("results", []):
            country = entry.get("iso_3166_1", "").upper()
            if country not in english_speaking_countries:
                continue
                
            _log("INFO", f"🎯 TMDB: Checking English-speaking country {country}")
            
            releases = entry.get("release_dates", [])
            if not releases:
                continue
            
            # Collect all available releases with their types and dates
            available_releases = []
            for release in releases:
                release_type = release.get("type")
                release_date = release.get("release_date")
                
                if release_date:
                    parsed_date = _parse_date_to_iso(release_date)
                    if parsed_date:
                        available_releases.append((release_type, parsed_date))
            
            # Apply TMDB release type priority order
            tmdb_priority = self._get_tmdb_type_priority()
            for preferred_type in tmdb_priority:
                for release_type, parsed_date in available_releases:
                    if release_type == preferred_type:
                        release_type_names = {
                            1: "Premiere", 2: "Limited Theatrical", 3: "Theatrical", 
                            4: "Digital", 5: "Physical", 6: "TV Premiere"
                        }
                        type_name = release_type_names.get(release_type, f"Type {release_type}")
                        _log("INFO", f"✅ TMDB: Using English-speaking {country} {type_name} release date: {parsed_date}")
                        return parsed_date
        
        # Second pass: Try any remaining country as last resort
        _log("INFO", f"🌍 TMDB: Trying any available country as last resort for {imdb_id}")
        for entry in release_dates.get("results", []):
            country = entry.get("iso_3166_1", "").upper()
            if country in english_speaking_countries or country == self.primary_country:
                continue  # Already tried these
                
            _log("INFO", f"🎯 TMDB: Checking fallback country {country}")
            
            releases = entry.get("release_dates", [])
            if not releases:
                continue
            
            # Collect all available releases with their types and dates
            available_releases = []
            for release in releases:
                release_type = release.get("type")
                release_date = release.get("release_date")
                
                if release_date:
                    parsed_date = _parse_date_to_iso(release_date)
                    if parsed_date:
                        available_releases.append((release_type, parsed_date))
            
            # Apply TMDB release type priority order
            tmdb_priority = self._get_tmdb_type_priority()
            for preferred_type in tmdb_priority:
                for release_type, parsed_date in available_releases:
                    if release_type == preferred_type:
                        release_type_names = {
                            1: "Premiere", 2: "Limited Theatrical", 3: "Theatrical", 
                            4: "Digital", 5: "Physical", 6: "TV Premiere"
                        }
                        type_name = release_type_names.get(release_type, f"Type {release_type}")
                        _log("INFO", f"✅ TMDB: Using fallback {country} {type_name} release date: {parsed_date}")
                        return parsed_date
        
        _log("WARNING", f"❌ TMDB: No release dates found for {imdb_id} in any country")
        return None
    
    def _get_tmdb_type_priority(self) -> List[int]:
        """Get TMDB release type priority order from environment"""
        # Default priority: Digital first, then Physical, then Theatrical, then others
        default_priority = "4,5,3,2,6,1"  # digital,physical,theatrical,limited,tv,premiere
        
        priority_str = os.environ.get("TMDB_TYPE_PRIORITY", default_priority)
        try:
            # Parse comma-separated numbers
            priority_list = [int(x.strip()) for x in priority_str.split(",") if x.strip().isdigit()]
            if priority_list:
                _log("DEBUG", f"TMDB type priority: {priority_list}")
                return priority_list
            else:
                _log("WARNING", f"Invalid TMDB_TYPE_PRIORITY '{priority_str}', using default")
                return [4, 5, 3, 2, 6, 1]
        except Exception as e:
            _log("WARNING", f"Error parsing TMDB_TYPE_PRIORITY: {e}, using default")
            return [4, 5, 3, 2, 6, 1]
    
    def get_theatrical_release_date(self, imdb_id: str) -> Optional[str]:
        """Get theatrical release date for a movie"""
        movie = self.find_by_imdb(imdb_id)
        if not movie:
            return None
        
        tmdb_id = movie.get("id")
        if not tmdb_id:
            return None
        
        release_dates = self._get(f"/movie/{tmdb_id}/release_dates")
        if not release_dates:
            return None
        
        for entry in release_dates.get("results", []):
            if entry.get("iso_3166_1", "").upper() != self.primary_country:
                continue
            
            for release in entry.get("release_dates", []):
                if release.get("type") == 3 and release.get("release_date"):  # Theatrical release
                    return _parse_date_to_iso(release["release_date"])
        
        return None
    
    def get_physical_release_date(self, imdb_id: str) -> Optional[str]:
        """Get physical release date (DVD/Blu-ray) for a movie"""
        movie = self.find_by_imdb(imdb_id)
        if not movie:
            return None
        
        tmdb_id = movie.get("id")
        if not tmdb_id:
            return None
        
        release_dates = self._get(f"/movie/{tmdb_id}/release_dates")
        if not release_dates:
            return None
        
        for entry in release_dates.get("results", []):
            if entry.get("iso_3166_1", "").upper() != self.primary_country:
                continue
            
            for release in entry.get("release_dates", []):
                if release.get("type") == 5 and release.get("release_date"):  # Physical release
                    return _parse_date_to_iso(release["release_date"])
        
        return None
    
    def get_tv_season_episodes(self, tv_id: int, season_number: int) -> Dict[int, str]:
        """Get episode air dates for a TV season"""
        result = self._get(f"/tv/{tv_id}/season/{season_number}")
        episodes = {}
        
        if result:
            for episode in result.get("episodes", []):
                ep_num = episode.get("episode_number")
                air_date = episode.get("air_date")
                if isinstance(ep_num, int) and air_date:
                    episodes[ep_num] = air_date
        
        return episodes


class OMDbClient:
    """Open Movie Database API client"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("OMDB_API_KEY", "")
        self.enabled = bool(self.api_key)
    
    def get_movie_details(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """Get movie details from OMDb"""
        if not self.enabled:
            return None
        
        params = {"i": imdb_id, "apikey": self.api_key}
        url = f"http://www.omdbapi.com/?{urlencode(params)}"
        result = _get_json(url, timeout=15)
        
        if result and result.get("Response") == "True":
            return result
        return None
    
    def get_dvd_release_date(self, imdb_id: str) -> Optional[str]:
        """Get DVD/digital release date"""
        details = self.get_movie_details(imdb_id)
        if not details:
            return None
        
        dvd_date = details.get("DVD") or details.get("Released")
        if not dvd_date or dvd_date == "N/A":
            return None
        
        # Try to parse various date formats
        for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(dvd_date, fmt).replace(tzinfo=timezone.utc)
                return dt.isoformat(timespec="seconds")
            except Exception:
                continue
        
        return None
    
    def get_tv_season_episodes(self, imdb_id: str, season_number: int) -> Dict[int, str]:
        """Get episode release dates for a TV season"""
        if not self.enabled:
            return {}
        
        params = {"i": imdb_id, "Season": str(season_number), "apikey": self.api_key}
        url = f"http://www.omdbapi.com/?{urlencode(params)}"
        result = _get_json(url, timeout=15)
        
        episodes = {}
        if result and result.get("Response") == "True":
            for episode in result.get("Episodes", []):
                try:
                    ep_num = int(episode.get("Episode", 0))
                    released = episode.get("Released")
                    if ep_num and released and released != "N/A":
                        episodes[ep_num] = released
                except Exception:
                    continue
        
        return episodes


class JellyseerrClient:
    """Jellyseerr API client"""
    
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = (base_url or os.environ.get("JELLYSEERR_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("JELLYSEERR_API_KEY", "")
        self.enabled = bool(self.base_url and self.api_key)
    
    def _get(self, path: str) -> Optional[Dict[str, Any]]:
        """Make GET request to Jellyseerr API"""
        if not self.enabled:
            return None
        
        url = f"{self.base_url}/api/v1{path}"
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}
        return _get_json(url, timeout=20, headers=headers)
    
    def get_movie_details(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """Get movie details from Jellyseerr"""
        return self._get(f"/movie/{tmdb_id}")
    
    def get_digital_release_dates(self, tmdb_id: int) -> List[str]:
        """Get digital release date candidates from Jellyseerr"""
        details = self.get_movie_details(tmdb_id)
        if not details:
            return []
        
        candidates = []
        
        # Check direct fields
        for field in ("digitalReleaseDate", "physicalReleaseDate", "vodReleaseDate"):
            value = details.get(field)
            if value:
                iso_date = _parse_date_to_iso(value)
                if iso_date:
                    candidates.append(iso_date)
        
        # Check release dates array
        for array_field in ("releaseDates", "releases", "dates"):
            release_array = details.get(array_field)
            if not isinstance(release_array, list):
                continue
            
            for release in release_array:
                if not isinstance(release, dict):
                    continue
                
                release_type = (release.get("type") or release.get("label") or "").lower()
                release_date = release.get("date") or release.get("releaseDate")
                
                if release_date and ("digital" in release_type or "vod" in release_type or "stream" in release_type):
                    iso_date = _parse_date_to_iso(release_date)
                    if iso_date:
                        candidates.append(iso_date)
        
        return candidates


class ExternalClientManager:
    """Manager for all external API clients"""
    
    def __init__(self):
        # Get country from environment, default to US
        tmdb_country = os.environ.get("TMDB_COUNTRY", "US")
        _log("INFO", f"🌍 TMDB: Initializing with country: {tmdb_country}")
        
        self.tmdb = TMDBClient(primary_country=tmdb_country)
        self.omdb = OMDbClient()
        self.jellyseerr = JellyseerrClient()
        self.tvdb = TVDBClient()
    
    def get_release_date_by_priority(self, imdb_id: str, priority_order: List[str], enable_smart_validation: bool = True) -> Optional[Tuple[str, str]]:
        """Get release date using configurable priority order with smart date validation"""
        
        # Get all possible release dates
        release_options = {}
        
        if self.tmdb.enabled:
            # Digital release
            digital_date = self.tmdb.get_digital_release_date(imdb_id)
            if digital_date:
                release_options["digital"] = (digital_date, "tmdb:digital")
            
            # Physical release
            physical_date = self.tmdb.get_physical_release_date(imdb_id)
            if physical_date:
                release_options["physical"] = (physical_date, "tmdb:physical")
            
            # Theatrical release
            theatrical_date = self.tmdb.get_theatrical_release_date(imdb_id)
            if theatrical_date:
                release_options["theatrical"] = (theatrical_date, "tmdb:theatrical")
        
        # Add OMDb options
        if self.omdb.enabled:
            omdb_date = self.omdb.get_dvd_release_date(imdb_id)
            if omdb_date and "physical" not in release_options:
                release_options["physical"] = (omdb_date, "omdb:dvd")
        
        # Add Jellyseerr digital releases
        if self.jellyseerr.enabled and self.tmdb.enabled and "digital" not in release_options:
            tmdb_movie = self.tmdb.find_by_imdb(imdb_id)
            if tmdb_movie:
                tmdb_id = tmdb_movie.get("id")
                if tmdb_id:
                    jellyseerr_dates = self.jellyseerr.get_digital_release_dates(tmdb_id)
                    if jellyseerr_dates:
                        earliest_jellyseerr = min(jellyseerr_dates)
                        release_options["digital"] = (earliest_jellyseerr, "jellyseerr:digital")
        
        # Smart date validation: Check if priority order makes sense given the actual dates
        if enable_smart_validation and len(release_options) > 1:
            validated_choice = self._validate_date_choice(release_options, priority_order)
            if validated_choice:
                return validated_choice
        
        # Return first available option according to priority (fallback behavior)
        for priority in priority_order:
            if priority in release_options:
                return release_options[priority]
        
        return None
    
    def _validate_date_choice(self, release_options: Dict[str, Tuple[str, str]], priority_order: List[str]) -> Optional[Tuple[str, str]]:
        """Validate date choice and prefer theatrical if digital/physical are unreasonably late"""
        from datetime import datetime, timezone
        import os
        
        # Get configuration for maximum gap (default: 10 years)
        max_reasonable_gap_years = int(os.environ.get("MAX_RELEASE_DATE_GAP_YEARS", "10"))
        
        # Parse all available dates
        parsed_dates = {}
        for release_type, (date_str, source) in release_options.items():
            try:
                parsed_dates[release_type] = (datetime.fromisoformat(date_str.replace('Z', '+00:00')), source)
            except Exception:
                continue
        
        if not parsed_dates or "theatrical" not in parsed_dates:
            return None  # No smart validation possible without theatrical date
        
        theatrical_date, theatrical_source = parsed_dates["theatrical"]
        
        # Check each priority option against theatrical date
        for priority in priority_order:
            if priority == "theatrical":
                continue  # Skip theatrical in this validation
            
            if priority in parsed_dates:
                priority_date, priority_source = parsed_dates[priority]
                
                # Calculate the gap in years
                gap = (priority_date - theatrical_date).days / 365.25
                
                # If the gap is too large, skip this priority and continue
                if gap > max_reasonable_gap_years:
                    print(f"[SMART VALIDATION] {priority} date {priority_date.strftime('%Y-%m-%d')} is {gap:.1f} years after theatrical {theatrical_date.strftime('%Y-%m-%d')}, preferring theatrical")
                    continue
                
                # This priority option is reasonable, use it
                return (priority_date.isoformat(timespec="seconds"), f"{priority_source} (validated)")
        
        # If all priority options are unreasonable, fall back to theatrical
        if "theatrical" in release_options:
            theatrical_date_str, theatrical_source = release_options["theatrical"]
            return (theatrical_date_str, f"{theatrical_source} (smart fallback)")
        
        return None
    
    def get_digital_release_candidates(self, imdb_id: str) -> List[Tuple[str, str]]:
        """Get digital release date candidates from all sources (legacy method)"""
        candidates = []
        
        # Try the new priority system with digital-first fallback
        result = self.get_release_date_by_priority(imdb_id, ["digital", "physical", "theatrical"])
        if result:
            candidates.append(result)
        
        return candidates
    
    def get_earliest_digital_release(self, imdb_id: str) -> Optional[Tuple[str, str]]:
        """Get the earliest digital release date (legacy method)"""
        candidates = self.get_digital_release_candidates(imdb_id)
        return candidates[0] if candidates else None
    
    def get_tvdb_series_id(self, imdb_id: str) -> Optional[str]:
        """Get TVDB series ID from IMDB ID"""
        # Check if TVDB lookups are disabled
        if os.environ.get("DISABLE_TVDB", "false").lower() in ["true", "1", "yes"]:
            _log("DEBUG", "TVDB lookups disabled via DISABLE_TVDB environment variable")
            return None
            
        if not self.tvdb.api_key:
            _log("INFO", "TVDB API key not configured, skipping TVDB ID lookup (set TVDB_API_KEY to enable)")
            return None
        
        return self.tvdb.imdb_to_tvdb_series_id(imdb_id)
    
    def get_episode_air_date(self, imdb_id: str, season: int, episode: int) -> Optional[str]:
        """Get episode air date from external sources"""
        _log("DEBUG", f"Looking for air date for {imdb_id} S{season:02d}E{episode:02d}")
        
        # Try TMDB first if available
        if self.tmdb.enabled:
            # Find TV show by IMDB ID
            tv_find_result = self.tmdb._get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
            if tv_find_result and tv_find_result.get("tv_results"):
                tv_show = tv_find_result["tv_results"][0]
                tv_id = tv_show.get("id")
                if tv_id:
                    _log("DEBUG", f"Found TMDB TV ID {tv_id} for {imdb_id}")
                    episodes = self.tmdb.get_tv_season_episodes(tv_id, season)
                    if episode in episodes:
                        air_date = episodes[episode]
                        _log("INFO", f"Found TMDB air date for {imdb_id} S{season:02d}E{episode:02d}: {air_date}")
                        return _parse_date_to_iso(air_date)
        
        # Try OMDb as fallback
        if self.omdb.enabled:
            episodes = self.omdb.get_tv_season_episodes(imdb_id, season)
            if episode in episodes:
                air_date = episodes[episode]
                _log("INFO", f"Found OMDb air date for {imdb_id} S{season:02d}E{episode:02d}: {air_date}")
                return _parse_date_to_iso(air_date)
        
        _log("WARNING", f"No air date found for {imdb_id} S{season:02d}E{episode:02d}")
        return None


if __name__ == "__main__":
    # Test the clients
    manager = ExternalClientManager()
    
    test_imdb = "tt1596343"  # Example IMDb ID
    digital_candidates = manager.get_digital_release_candidates(test_imdb)
    print(f"Digital release candidates for {test_imdb}: {digital_candidates}")
    
    earliest = manager.get_earliest_digital_release(test_imdb)
    if earliest:
        print(f"Earliest digital release: {earliest[0]} ({earliest[1]})")
    else:
        print("No digital release dates found")