"""Logging utilities for Chronarr"""

from datetime import datetime, timezone
import os

def _get_local_timezone():
    """Get the local timezone, respecting TZ environment variable"""
    tz_name = os.environ.get('TZ', 'UTC')
    
    try:
        # Try zoneinfo first (Python 3.9+)
        from zoneinfo import ZoneInfo
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
    """Basic logging function that writes to console"""
    tz = _get_local_timezone()
    print(f"[{datetime.now(tz).isoformat(timespec='seconds')}] {level}: {msg}")

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