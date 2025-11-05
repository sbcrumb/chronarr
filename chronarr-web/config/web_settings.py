"""
Chronarr Web Interface Configuration
Lightweight configuration for web-only container
"""
import os


def _bool_env(name: str, default: bool = False) -> bool:
    """Convert environment variable to boolean"""
    value = os.environ.get(name, "").lower()
    return value in ("true", "1", "yes", "on")


class WebConfig:
    """Configuration for Chronarr Web Interface"""
    
    def __init__(self):
        self._load_server_settings()
        self._load_database_settings()
        self._load_auth_settings()
        self._load_ui_settings()
    
    def _load_server_settings(self) -> None:
        """Load web server configuration"""
        self.web_host = os.environ.get("WEB_HOST", "0.0.0.0")
        self.web_port = int(os.environ.get("WEB_PORT", "8081"))
        self.web_workers = int(os.environ.get("WEB_WORKERS", "1"))
        self.web_debug = _bool_env("WEB_DEBUG", False)
        
        # Core Chronarr API connection (for some operations)
        self.core_api_host = os.environ.get("CORE_API_HOST", "chronarr")
        self.core_api_port = int(os.environ.get("CORE_API_PORT", "8080"))
        self.core_api_url = f"http://{self.core_api_host}:{self.core_api_port}"
    
    def _load_database_settings(self) -> None:
        """Load database configuration (read-only access)"""
        self.db_type = os.environ.get("DB_TYPE", "postgresql").lower()
        self.db_host = os.environ.get("DB_HOST", "chronarr-db")
        self.db_port = int(os.environ.get("DB_PORT", "5432"))
        self.db_name = os.environ.get("DB_NAME", "chronarr")
        self.db_user = os.environ.get("DB_USER", "chronarr")
        self.db_password = os.environ.get("DB_PASSWORD", "")
        
        if not self.db_password:
            raise ValueError("DB_PASSWORD must be set for web interface database access")
    
    def _load_auth_settings(self) -> None:
        """Load web interface authentication settings"""
        self.web_auth_enabled = _bool_env("WEB_AUTH_ENABLED", False)
        self.web_auth_username = os.environ.get("WEB_AUTH_USERNAME", "admin")
        self.web_auth_password = os.environ.get("WEB_AUTH_PASSWORD", "")
        self.web_auth_session_timeout = int(os.environ.get("WEB_AUTH_SESSION_TIMEOUT", "3600"))
        
        if self.web_auth_enabled and not self.web_auth_password:
            raise ValueError("WEB_AUTH_PASSWORD must be set when authentication is enabled")
    
    def _load_ui_settings(self) -> None:
        """Load UI-specific settings"""
        self.app_title = os.environ.get("APP_TITLE", "Chronarr")
        self.app_subtitle = os.environ.get("APP_SUBTITLE", "Database Management & Reporting")
        self.pagination_limit = int(os.environ.get("PAGINATION_LIMIT", "50"))
        self.refresh_interval = int(os.environ.get("REFRESH_INTERVAL", "30"))  # seconds
        
        # Logo configuration
        self.logo_enabled = _bool_env("LOGO_ENABLED", True)
        self.logo_path = "/static/logo/ChronarrLogoPlain.png"


# Global config instance
web_config = WebConfig()