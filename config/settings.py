"""
Chronarr Configuration Module
Handles all configuration loading and validation with comprehensive error reporting
"""
import os
import sys
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from utils.exceptions import ConfigurationError


logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool) -> bool:
    """Convert environment variable to boolean"""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")


class ChronarrConfig:
    """Configuration class for Chronarr with integrated validation"""
    
    def __init__(self, validate_on_init: bool = True, strict_validation: bool = False):
        """
        Initialize Chronarr configuration
        
        Args:
            validate_on_init: Run validation during initialization
            strict_validation: Treat warnings as errors
        """
        self.strict_validation = strict_validation
        self._validation_issues = []
        
        # Initialize configuration
        self._load_configuration()
        
        # Run validation if requested
        if validate_on_init:
            self._validate_configuration()
    
    def _load_configuration(self) -> None:
        """Load all configuration from environment variables"""
        # Server configuration
        self._load_server_settings()
        
        # Core paths - Required
        self._load_paths()
        
        # Core settings
        self.manage_nfo = _bool_env("MANAGE_NFO", True)
        self.fix_dir_mtimes = _bool_env("FIX_DIR_MTIMES", True)
        self.lock_metadata = _bool_env("LOCK_METADATA", True)
        self.debug = _bool_env("DEBUG", False)
        self.manager_brand = os.environ.get("MANAGER_BRAND", "Chronarr")
        
        # Batching and performance
        self.batch_delay = self._get_float_env("BATCH_DELAY", 5.0, 0.1, 300.0)
        self.max_concurrent = self._get_int_env("MAX_CONCURRENT_SERIES", 3, 1, 10)
        self.sequential_delay = self._get_float_env("SEQUENTIAL_DELAY", 20.0, 0.0, 60.0)  # Delay between sequential episodes (default 20s)
        
        # Database
        self.db_type = os.environ.get("DB_TYPE", "sqlite").lower()
        self.db_path = Path(os.environ.get("DB_PATH", "/app/data/media_dates.db"))
        
        # PostgreSQL database settings
        if self.db_type == "postgresql":
            self.db_host = os.environ.get("DB_HOST", "localhost")
            self.db_port = self._get_int_env("DB_PORT", 5432, 1, 65535)
            self.db_name = os.environ.get("DB_NAME", "chronarr")
            self.db_user = os.environ.get("DB_USER", "chronarr")
            self.db_password = os.environ.get("DB_PASSWORD", "")
        
        # External connections
        self._load_external_connections()
        
        # Movie processing
        self._load_movie_settings()
        
        # TV processing
        self._load_tv_settings()
        
        # Web interface authentication
        self._load_auth_settings()
    
    def _load_paths(self) -> None:
        """Load and validate path configuration"""
        tv_paths_env = os.environ.get("TV_PATHS", "")
        movie_paths_env = os.environ.get("MOVIE_PATHS", "")
        
        if not tv_paths_env:
            raise ConfigurationError(
                setting="TV_PATHS",
                reason="TV_PATHS environment variable is required but not set"
            )
        
        if not movie_paths_env:
            raise ConfigurationError(
                setting="MOVIE_PATHS", 
                reason="MOVIE_PATHS environment variable is required but not set"
            )
            
        # Parse paths
        self.tv_paths = [Path(p.strip()) for p in tv_paths_env.split(",") if p.strip()]
        self.movie_paths = [Path(p.strip()) for p in movie_paths_env.split(",") if p.strip()]
        
        if not self.tv_paths:
            raise ConfigurationError(
                setting="TV_PATHS",
                reason="No valid TV paths found after parsing",
                current_value=tv_paths_env
            )
        
        if not self.movie_paths:
            raise ConfigurationError(
                setting="MOVIE_PATHS",
                reason="No valid movie paths found after parsing", 
                current_value=movie_paths_env
            )
    
    def _load_server_settings(self) -> None:
        """Load server configuration"""
        # Core API settings (webhooks, processing, database management)
        self.core_api_host = os.environ.get("CORE_API_HOST", "0.0.0.0")
        self.core_api_port = self._get_int_env("CORE_API_PORT", 8080, 1024, 65535)
        
        # Web API settings (dashboard, web interface) - for reference/connection
        self.web_api_host = os.environ.get("WEB_API_HOST", "0.0.0.0")
        self.web_api_port = self._get_int_env("WEB_API_PORT", 8081, 1024, 65535)
    
    def _load_external_connections(self) -> None:
        """Load external API and database connection settings"""
        # API URLs
        self.radarr_url = os.environ.get("RADARR_URL", "")
        self.sonarr_url = os.environ.get("SONARR_URL", "")
        self.jellyseerr_url = os.environ.get("JELLYSEERR_URL", "")
        
        # Radarr database settings
        self.radarr_db_type = os.environ.get("RADARR_DB_TYPE", "").lower()
        self.radarr_db_host = os.environ.get("RADARR_DB_HOST", "")
        self.radarr_db_port = self._get_int_env("RADARR_DB_PORT", 5432, 1, 65535) 
        self.radarr_db_name = os.environ.get("RADARR_DB_NAME", "")
        self.radarr_db_user = os.environ.get("RADARR_DB_USER", "")
        
        # Timeout settings
        self.timeout_seconds = self._get_int_env("TIMEOUT_SECONDS", 45, 10, 300)
    
    def _load_movie_settings(self) -> None:
        """Load movie processing settings"""
        self.movie_priority = os.environ.get("MOVIE_PRIORITY", "import_then_digital").lower()
        self.prefer_release_dates_over_file_dates = _bool_env("PREFER_RELEASE_DATES_OVER_FILE_DATES", True)
        self.allow_file_date_fallback = _bool_env("ALLOW_FILE_DATE_FALLBACK", False)
        
        # Manual scan behavior
        self.manual_scan_prioritize_nfo = _bool_env("MANUAL_SCAN_PRIORITIZE_NFO", False)
        
        # Release date settings
        release_priority_env = os.environ.get("RELEASE_DATE_PRIORITY", "digital,physical,theatrical")
        self.release_date_priority = [p.strip() for p in release_priority_env.split(",") if p.strip()]
        
        self.enable_smart_date_validation = _bool_env("ENABLE_SMART_DATE_VALIDATION", True)
        self.max_release_date_gap_years = self._get_int_env("MAX_RELEASE_DATE_GAP_YEARS", 10, 1, 50)
        self.movie_poll_mode = os.environ.get("MOVIE_POLL_MODE", "always").lower()
        self.movie_update_mode = os.environ.get("MOVIE_DATE_UPDATE_MODE", "backfill_only").lower()
    
    def _load_tv_settings(self) -> None:
        """Load TV processing settings"""
        self.tv_season_dir_format = os.environ.get("TV_SEASON_DIR_FORMAT", "Season {season:02d}")
        self.tv_season_dir_pattern = os.environ.get("TV_SEASON_DIR_PATTERN", "season ").lower()
        self.tv_webhook_processing_mode = os.environ.get("TV_WEBHOOK_PROCESSING_MODE", "targeted").lower()
        
    def get_season_dir_name(self, season: int) -> str:
        """Get the directory name for a specific season, handling Season 0 as 'Specials'"""
        if season == 0:
            return "Specials"
        return self.tv_season_dir_format.format(season=season)
    
    def _load_auth_settings(self) -> None:
        """Load web interface authentication settings"""
        self.web_auth_enabled = _bool_env("WEB_AUTH_ENABLED", False)
        self.web_auth_username = os.environ.get("WEB_AUTH_USERNAME", "admin")
        self.web_auth_password = os.environ.get("WEB_AUTH_PASSWORD", "")
        self.web_auth_session_timeout = self._get_int_env("WEB_AUTH_SESSION_TIMEOUT", 3600, 300, 86400)  # 1 hour default, 5min-24h range
    
    def _get_int_env(self, name: str, default: int, min_val: int, max_val: int) -> int:
        """Get integer environment variable with validation"""
        value_str = os.environ.get(name)
        if not value_str:
            return default
        
        try:
            value = int(value_str)
            if value < min_val or value > max_val:
                raise ConfigurationError(
                    setting=name,
                    reason=f"Value must be between {min_val} and {max_val}",
                    current_value=value_str
                )
            return value
        except ValueError:
            raise ConfigurationError(
                setting=name,
                reason=f"Invalid integer value",
                current_value=value_str
            )
    
    def _get_float_env(self, name: str, default: float, min_val: float, max_val: float) -> float:
        """Get float environment variable with validation"""
        value_str = os.environ.get(name)
        if not value_str:
            return default
        
        try:
            value = float(value_str)
            if value < min_val or value > max_val:
                raise ConfigurationError(
                    setting=name,
                    reason=f"Value must be between {min_val} and {max_val}",
                    current_value=value_str
                )
            return value
        except ValueError:
            raise ConfigurationError(
                setting=name,
                reason=f"Invalid float value",
                current_value=value_str
            )
    
    def _validate_configuration(self) -> None:
        """Validate configuration using the validator"""
        try:
            # Import here to avoid circular imports
            from config.validator import validate_configuration_and_raise
            validate_configuration_and_raise()
            
        except ImportError:
            # Fallback to basic validation if validator not available
            logger.warning("Configuration validator not available, using basic validation")
            self._basic_validation()
        except ConfigurationError:
            if self.strict_validation:
                raise
            else:
                # Log warning but continue
                logger.warning("Configuration validation found issues", exc_info=True)
    
    def _basic_validation(self) -> None:
        """Basic fallback validation"""
        # Validate that paths exist (basic check)
        for path_list, path_type in [(self.tv_paths, "TV"), (self.movie_paths, "Movie")]:
            for path in path_list:
                if not path.is_absolute():
                    logger.warning(f"{path_type} path should be absolute: {path}")
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get a summary of current configuration"""
        return {
            "tv_paths": [str(p) for p in self.tv_paths],
            "movie_paths": [str(p) for p in self.movie_paths],
            "database": {
                "type": self.db_type,
                "path": str(self.db_path) if self.db_type == "sqlite" else None,
                "host": getattr(self, 'db_host', None) if self.db_type == "postgresql" else None,
                "port": getattr(self, 'db_port', None) if self.db_type == "postgresql" else None,
                "name": getattr(self, 'db_name', None) if self.db_type == "postgresql" else None
            },
            "external_apis": {
                "radarr": bool(self.radarr_url),
                "sonarr": bool(self.sonarr_url),
                "jellyseerr": bool(self.jellyseerr_url)
            },
            "radarr_database": {
                "type": getattr(self, 'radarr_db_type', None),
                "configured": bool(getattr(self, 'radarr_db_type', None) and getattr(self, 'radarr_db_host', None))
            },
            "performance": {
                "batch_delay": self.batch_delay,
                "max_concurrent": self.max_concurrent,
                "timeout_seconds": self.timeout_seconds
            },
            "features": {
                "manage_nfo": self.manage_nfo,
                "fix_dir_mtimes": self.fix_dir_mtimes,
                "lock_metadata": self.lock_metadata,
                "debug": self.debug,
                "manual_scan_prioritize_nfo": self.manual_scan_prioritize_nfo
            }
        }
    
    def validate_runtime_access(self) -> Dict[str, bool]:
        """Quick runtime validation of critical paths"""
        results = {
            "tv_paths_accessible": True,
            "movie_paths_accessible": True,
            "database_writable": True
        }
        
        # Test TV paths
        for path in self.tv_paths:
            if not path.exists() or not path.is_dir():
                results["tv_paths_accessible"] = False
                break
        
        # Test movie paths  
        for path in self.movie_paths:
            if not path.exists() or not path.is_dir():
                results["movie_paths_accessible"] = False
                break
        
        # Test database directory
        db_dir = self.db_path.parent
        try:
            if not db_dir.exists():
                db_dir.mkdir(parents=True, exist_ok=True)
            
            # Test write access
            test_file = db_dir / ".chronarr_write_test"
            test_file.write_text("test")
            test_file.unlink()
        except (PermissionError, OSError):
            results["database_writable"] = False
        
        return results


# Global config instance - Initialize with validation disabled by default for backwards compatibility
# Applications can enable validation by creating their own instance with validate_on_init=True
config = ChronarrConfig(validate_on_init=False)