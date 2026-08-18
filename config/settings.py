"""
Chronarr Configuration Module
Handles all configuration loading and validation with comprehensive error reporting
"""
import os
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from utils.exceptions import ConfigurationError


logger = logging.getLogger(__name__)


# Reserved env var segments that are NOT instance names
_RADARR_RESERVED = {"DB", "WEBHOOK"}
_SONARR_RESERVED = {"DB", "WEBHOOK"}


@dataclass
class RadarrInstance:
    """Configuration for one Radarr instance"""
    name: str               # "radarr" for default, "radarr_4k" for RADARR_4K_*
    url: str
    api_key: str
    root_folders: List[str]
    movie_paths: List[str]
    webhook_path: str       # e.g. "/radarr/webhook" or "/radarr_4k/webhook"
    db_type: str = ""       # "postgresql", "sqlite", or "" (API-only)
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_path: str = ""       # sqlite only


@dataclass
class SonarrInstance:
    """Configuration for one Sonarr instance"""
    name: str               # "sonarr" for default, "sonarr_4k" for SONARR_4K_*
    url: str
    api_key: str
    root_folders: List[str]
    tv_paths: List[str]
    webhook_path: str       # e.g. "/sonarr/webhook" or "/sonarr_4k/webhook"
    db_type: str = ""
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_path: str = ""       # sqlite only


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
        # Discover all Radarr and Sonarr instances from env
        self.radarr_instances: List[RadarrInstance] = self._discover_radarr_instances()
        self.sonarr_instances: List[SonarrInstance] = self._discover_sonarr_instances()

        # Backward-compat shims — point at the first (default) instance if present
        self.radarr_url = self.radarr_instances[0].url if self.radarr_instances else ""
        self.sonarr_url = self.sonarr_instances[0].url if self.sonarr_instances else ""
        self.radarr_db_type = self.radarr_instances[0].db_type if self.radarr_instances else ""

        self.jellyseerr_url = os.environ.get("JELLYSEERR_URL", "")

        # Timeout settings
        self.timeout_seconds = self._get_int_env("TIMEOUT_SECONDS", 45, 10, 300)

    # ------------------------------------------------------------------
    # Instance discovery helpers
    # ------------------------------------------------------------------

    def _load_radarr_instance(self, name_segment: str, url: str) -> RadarrInstance:
        """Build a RadarrInstance from env vars for the given name segment.

        name_segment is the part between RADARR_ and _URL, e.g. "4K" for
        RADARR_4K_URL.  Empty string means the default (RADARR_URL) instance.
        """
        prefix = f"RADARR_{name_segment}_" if name_segment else "RADARR_"
        instance_name = f"radarr_{name_segment.lower()}" if name_segment else "radarr"
        webhook_path = f"/{instance_name}/webhook"

        root_folders = [
            p.strip()
            for p in os.environ.get(f"{prefix}ROOT_FOLDERS", "").split(",")
            if p.strip()
        ]
        movie_paths = [
            p.strip()
            for p in os.environ.get(f"{prefix}MOVIE_PATHS",
                                    os.environ.get("MOVIE_PATHS", "")).split(",")
            if p.strip()
        ]

        db_type = os.environ.get(f"{prefix}DB_TYPE", "").lower()
        db_port_str = os.environ.get(f"{prefix}DB_PORT", "5432")
        try:
            db_port = int(db_port_str)
        except ValueError:
            db_port = 5432

        return RadarrInstance(
            name=instance_name,
            url=url,
            api_key=os.environ.get(f"{prefix}API_KEY", ""),
            root_folders=root_folders,
            movie_paths=movie_paths,
            webhook_path=webhook_path,
            db_type=db_type,
            db_host=os.environ.get(f"{prefix}DB_HOST", ""),
            db_port=db_port,
            db_name=os.environ.get(f"{prefix}DB_NAME", ""),
            db_user=os.environ.get(f"{prefix}DB_USER", ""),
            db_password=os.environ.get(f"{prefix}DB_PASSWORD", ""),
            db_path=os.environ.get(f"{prefix}DB_PATH", ""),
        )

    def _discover_radarr_instances(self) -> List[RadarrInstance]:
        """Discover all configured Radarr instances from environment variables.

        Looks for RADARR_URL (default instance) and RADARR_{NAME}_URL (named
        instances). The default instance is always first in the returned list.
        """
        instances = []

        # Default instance
        default_url = os.environ.get("RADARR_URL", "")
        if default_url:
            instances.append(self._load_radarr_instance("", default_url))

        # Named instances — scan for RADARR_*_URL
        seen = set()
        for key in sorted(os.environ.keys()):
            if not key.startswith("RADARR_") or not key.endswith("_URL"):
                continue
            if key == "RADARR_URL":
                continue
            name_segment = key[len("RADARR_"):-len("_URL")]
            # Skip reserved segments (DB, WEBHOOK) and duplicates
            if name_segment in _RADARR_RESERVED or name_segment in seen:
                continue
            seen.add(name_segment)
            url = os.environ[key]
            if url:
                instances.append(self._load_radarr_instance(name_segment, url))

        return instances

    def _load_sonarr_instance(self, name_segment: str, url: str) -> SonarrInstance:
        """Build a SonarrInstance from env vars for the given name segment."""
        prefix = f"SONARR_{name_segment}_" if name_segment else "SONARR_"
        instance_name = f"sonarr_{name_segment.lower()}" if name_segment else "sonarr"
        webhook_path = f"/{instance_name}/webhook"

        root_folders = [
            p.strip()
            for p in os.environ.get(f"{prefix}ROOT_FOLDERS", "").split(",")
            if p.strip()
        ]
        tv_paths = [
            p.strip()
            for p in os.environ.get(f"{prefix}TV_PATHS",
                                    os.environ.get("TV_PATHS", "")).split(",")
            if p.strip()
        ]

        db_type = os.environ.get(f"{prefix}DB_TYPE", "").lower()
        db_port_str = os.environ.get(f"{prefix}DB_PORT", "5432")
        try:
            db_port = int(db_port_str)
        except ValueError:
            db_port = 5432

        return SonarrInstance(
            name=instance_name,
            url=url,
            api_key=os.environ.get(f"{prefix}API_KEY", ""),
            root_folders=root_folders,
            tv_paths=tv_paths,
            webhook_path=webhook_path,
            db_type=db_type,
            db_host=os.environ.get(f"{prefix}DB_HOST", ""),
            db_port=db_port,
            db_name=os.environ.get(f"{prefix}DB_NAME", ""),
            db_user=os.environ.get(f"{prefix}DB_USER", ""),
            db_password=os.environ.get(f"{prefix}DB_PASSWORD", ""),
            db_path=os.environ.get(f"{prefix}DB_PATH", ""),
        )

    def _discover_sonarr_instances(self) -> List[SonarrInstance]:
        """Discover all configured Sonarr instances from environment variables."""
        instances = []

        default_url = os.environ.get("SONARR_URL", "")
        if default_url:
            instances.append(self._load_sonarr_instance("", default_url))

        seen = set()
        for key in sorted(os.environ.keys()):
            if not key.startswith("SONARR_") or not key.endswith("_URL"):
                continue
            if key == "SONARR_URL":
                continue
            name_segment = key[len("SONARR_"):-len("_URL")]
            if name_segment in _SONARR_RESERVED or name_segment in seen:
                continue
            seen.add(name_segment)
            url = os.environ[key]
            if url:
                instances.append(self._load_sonarr_instance(name_segment, url))

        return instances

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
        self.web_auth_secure_cookie = _bool_env("WEB_AUTH_SECURE_COOKIE", False)  # Set True when serving over HTTPS
        self.radarr_webhook_secret = os.environ.get("RADARR_WEBHOOK_SECRET", "")
        self.sonarr_webhook_secret = os.environ.get("SONARR_WEBHOOK_SECRET", "")
    
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