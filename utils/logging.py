"""
Logging utilities for Chronarr
"""
import os
import re
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A RotatingFileHandler that handles missing backup files gracefully"""
    
    def doRollover(self):
        """
        Override doRollover to handle missing backup files gracefully
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        
        if self.backupCount > 0:
            # Remove the oldest backup if it exists
            oldest_backup = f"{self.baseFilename}.{self.backupCount}"
            if os.path.exists(oldest_backup):
                try:
                    os.remove(oldest_backup)
                except (OSError, FileNotFoundError):
                    pass  # Ignore if file doesn't exist or can't be removed
            
            # Rename existing backups, skipping missing ones
            for i in range(self.backupCount - 1, 0, -1):
                sfn = f"{self.baseFilename}.{i}"
                dfn = f"{self.baseFilename}.{i + 1}"
                if os.path.exists(sfn):
                    try:
                        os.rename(sfn, dfn)
                    except (OSError, FileNotFoundError):
                        pass  # Skip if source doesn't exist or rename fails
            
            # Rename the main log file
            dfn = f"{self.baseFilename}.1"
            if os.path.exists(self.baseFilename):
                try:
                    os.rename(self.baseFilename, dfn)
                except (OSError, FileNotFoundError):
                    pass  # Skip if main file doesn't exist
        
        # Open the new log file
        if not self.delay:
            self.stream = self._open()


class TimezoneAwareFormatter(logging.Formatter):
    """Formatter that respects the container timezone"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone = self._get_local_timezone()
    
    def _get_local_timezone(self):
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
            # If zone name is invalid, fallback to UTC
            return timezone.utc
    
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self.timezone)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec='seconds')


def _setup_file_logging():
    """Setup file logging for Chronarr"""
    log_dir = Path(os.environ.get("LOG_DIR", "/app/data/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("Chronarr")
    logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Try to set up file logging
    file_logging_enabled = False
    try:
        file_handler = SafeRotatingFileHandler(
            log_dir / "chronarr.log", maxBytes=50*1024*1024, backupCount=3
        )

        formatter = TimezoneAwareFormatter(
            '[%(asctime)s] %(levelname)s: %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        file_logging_enabled = True
    except Exception as e:
        # If RotatingFileHandler fails, try regular FileHandler
        try:
            file_handler = logging.FileHandler(log_dir / "chronarr.log")
            formatter = TimezoneAwareFormatter(
                '[%(asctime)s] %(levelname)s: %(message)s'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            file_logging_enabled = True
        except Exception as e2:
            # File logging not available (e.g., read-only filesystem)
            # Fall back to console-only logging silently
            pass

    # If file logging failed, ensure console handler is added
    if not file_logging_enabled:
        console_handler = logging.StreamHandler()
        formatter = TimezoneAwareFormatter(
            '[%(asctime)s] %(levelname)s: %(message)s'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


def _mask_sensitive_data(msg: str) -> str:
    """Mask API keys and other sensitive data in log messages"""
    # List of patterns to mask
    sensitive_patterns = [
        (r'api_key=([a-zA-Z0-9_\-]+)', r'api_key=***masked***'),
        (r'password=([^\s&]+)', r'password=***masked***'),
        (r'token=([a-zA-Z0-9_\-]+)', r'token=***masked***'),
        (r'key=([a-zA-Z0-9_\-]{8,})', r'key=***masked***'),  # Keys longer than 8 chars
        (r'([a-zA-Z0-9]{32,})', lambda m: m.group(1)[:8] + '***masked***' if len(m.group(1)) > 16 else m.group(1))  # Long strings likely to be keys
    ]
    
    masked_msg = msg
    for pattern, replacement in sensitive_patterns:
        if isinstance(replacement, str):
            masked_msg = re.sub(pattern, replacement, masked_msg, flags=re.IGNORECASE)
        else:
            masked_msg = re.sub(pattern, replacement, masked_msg, flags=re.IGNORECASE)
    
    return masked_msg


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
        # If zone name is invalid, fallback to UTC
        return timezone.utc


def _log(level: str, msg: str):
    """Enhanced logging that writes to both console and file with sensitive data masking"""
    masked_msg = _mask_sensitive_data(msg)
    tz = _get_local_timezone()
    print(f"[{datetime.now(tz).isoformat(timespec='seconds')}] {level}: {masked_msg}")
    
    try:
        file_logger = _setup_file_logging()
        getattr(file_logger, level.lower(), file_logger.info)(masked_msg)
    except Exception as e:
        print(f"File logging error: {e}")


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


def _load_environment_files():
    """Load environment variables from .env and optionally .env.secrets"""
    from pathlib import Path
    
    # Try to load from python-dotenv if available
    try:
        from dotenv import load_dotenv
        
        # Load main .env file
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)
            _log("INFO", f"Loaded environment from {env_file}")
        
        # Load secrets file if it exists
        secrets_file = Path(".env.secrets")
        if secrets_file.exists():
            load_dotenv(secrets_file)
            _log("INFO", f"Loaded secrets from {secrets_file}")
            
    except ImportError:
        _log("WARNING", "python-dotenv not available - environment files not loaded")


# Initialize logging and load environment files
_setup_file_logging()
_load_environment_files()