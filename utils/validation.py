"""
Validation utilities for Chronarr
Provides runtime validation and type checking for critical paths
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable, TypeVar, Type
from datetime import datetime

from utils.exceptions import ConfigurationError, ChronarrException


T = TypeVar('T')


def validate_imdb_id(imdb_id: str) -> bool:
    """
    Validate IMDb ID format
    
    Args:
        imdb_id: IMDb ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not imdb_id or not isinstance(imdb_id, str):
        return False
    
    # Must start with 'tt' followed by 7+ digits
    return bool(re.match(r'^tt\d{7,}$', imdb_id))


def validate_tmdb_id(tmdb_id: str) -> bool:
    """
    Validate TMDB ID format
    
    Args:
        tmdb_id: TMDB ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not tmdb_id or not isinstance(tmdb_id, str):
        return False
    
    # Can be numeric or have tmdb- prefix
    if tmdb_id.startswith('tmdb-'):
        return tmdb_id[5:].isdigit()
    return tmdb_id.isdigit()


def validate_season_episode(season: int, episode: int) -> bool:
    """
    Validate season and episode numbers
    
    Args:
        season: Season number
        episode: Episode number
        
    Returns:
        True if valid, False otherwise
    """
    return (
        isinstance(season, int) and season >= 0 and
        isinstance(episode, int) and episode >= 1
    )


def validate_date_string(date_str: str) -> bool:
    """
    Validate date string format (ISO format)
    
    Args:
        date_str: Date string to validate
        
    Returns:
        True if valid ISO date, False otherwise
    """
    if not date_str or not isinstance(date_str, str):
        return False
    
    try:
        datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False


def validate_path_exists(path: Union[str, Path]) -> bool:
    """
    Validate that a path exists
    
    Args:
        path: Path to validate
        
    Returns:
        True if path exists, False otherwise
    """
    try:
        return Path(path).exists()
    except (OSError, ValueError):
        return False


def validate_video_file(file_path: Union[str, Path]) -> bool:
    """
    Validate that a file is a video file
    
    Args:
        file_path: Path to validate
        
    Returns:
        True if valid video file, False otherwise
    """
    try:
        path = Path(file_path)
        video_extensions = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.ts'}
        return path.is_file() and path.suffix.lower() in video_extensions
    except (OSError, ValueError):
        return False


def validate_webhook_payload(payload: Dict[str, Any], required_fields: List[str]) -> List[str]:
    """
    Validate webhook payload has required fields
    
    Args:
        payload: Webhook payload to validate
        required_fields: List of required field names
        
    Returns:
        List of missing field names (empty if all present)
    """
    missing_fields = []
    for field in required_fields:
        if field not in payload or payload[field] is None:
            missing_fields.append(field)
    return missing_fields


def validate_config_paths(paths: List[Union[str, Path]], path_type: str) -> None:
    """
    Validate configuration paths exist and are directories
    
    Args:
        paths: List of paths to validate
        path_type: Type of paths for error messages (e.g., "TV", "Movie")
        
    Raises:
        ConfigurationError: If any paths are invalid
    """
    invalid_paths = []
    
    for path in paths:
        try:
            path_obj = Path(path)
            if not path_obj.exists():
                invalid_paths.append(f"{path} (does not exist)")
            elif not path_obj.is_dir():
                invalid_paths.append(f"{path} (not a directory)")
        except (OSError, ValueError) as e:
            invalid_paths.append(f"{path} (invalid: {e})")
    
    if invalid_paths:
        raise ConfigurationError(
            f"{path_type.lower()}_paths",
            f"Invalid {path_type} paths found",
            {"invalid_paths": invalid_paths}
        )


def require_type(value: Any, expected_type: Type[T], name: str) -> T:
    """
    Require value to be of specific type
    
    Args:
        value: Value to check
        expected_type: Expected type
        name: Name of the value for error messages
        
    Returns:
        The value if it matches the type
        
    Raises:
        TypeError: If value is not of expected type
    """
    if not isinstance(value, expected_type):
        raise TypeError(
            f"{name} must be {expected_type.__name__}, got {type(value).__name__}"
        )
    return value


def require_non_empty(value: Optional[str], name: str) -> str:
    """
    Require string value to be non-empty
    
    Args:
        value: String value to check
        name: Name of the value for error messages
        
    Returns:
        The value if it's non-empty
        
    Raises:
        ValueError: If value is None or empty
    """
    if not value:
        raise ValueError(f"{name} cannot be None or empty")
    return value


def validate_and_clean_imdb_id(imdb_id: Optional[str]) -> Optional[str]:
    """
    Validate and clean IMDb ID
    
    Args:
        imdb_id: IMDb ID to validate and clean
        
    Returns:
        Cleaned IMDb ID or None if invalid
    """
    if not imdb_id:
        return None
    
    # Clean the ID
    cleaned = imdb_id.strip().lower()
    
    # Remove common prefixes
    if cleaned.startswith('imdb-'):
        cleaned = cleaned[5:]
    elif cleaned.startswith('imdb_'):
        cleaned = cleaned[5:]
    
    # Ensure it starts with 'tt'
    if not cleaned.startswith('tt'):
        cleaned = f'tt{cleaned}'
    
    # Validate format
    if validate_imdb_id(cleaned):
        return cleaned
    
    return None


def create_validator(validation_func: Callable[[Any], bool], error_message: str) -> Callable:
    """
    Create a validator decorator
    
    Args:
        validation_func: Function that returns True if value is valid
        error_message: Error message to raise if validation fails
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            # Apply validation to first argument
            if args and not validation_func(args[0]):
                raise ValueError(error_message.format(args[0]))
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Common validators
validate_imdb_required = create_validator(
    lambda x: validate_imdb_id(x),
    "Invalid IMDb ID format: {}"
)

validate_path_required = create_validator(
    lambda x: validate_path_exists(x),
    "Path does not exist: {}"
)

validate_date_required = create_validator(
    lambda x: validate_date_string(x),
    "Invalid date format: {}"
)


class ValidationError(ChronarrException):
    """Raised when validation fails"""
    
    def __init__(self, field_name: str, value: Any, reason: str):
        details = {
            "field_name": field_name,
            "value": str(value),
            "reason": reason
        }
        message = f"Validation failed for {field_name}: {reason}"
        super().__init__(message, details)


def validate_episode_file_pattern(filename: str) -> Optional[Dict[str, int]]:
    """
    Validate and extract episode information from filename
    
    Args:
        filename: Filename to validate
        
    Returns:
        Dictionary with season and episode if valid, None otherwise
    """
    # Episode patterns
    patterns = [
        r'[sS](\d{1,2})[eE](\d{1,3})',  # S01E01
        r'(\d{1,2})x(\d{1,3})',         # 1x01
        r'[sS](\d{1,2})\.?[eE](\d{1,3})', # S01.E01
    ]
    
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            if validate_season_episode(season, episode):
                return {"season": season, "episode": episode}
    
    return None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing invalid characters
    
    Args:
        filename: Filename to sanitize
        
    Returns:
        Sanitized filename
    """
    # Remove invalid characters for most filesystems
    invalid_chars = r'<>:"/\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Ensure it's not empty
    if not filename:
        filename = 'unnamed'
    
    return filename


def validate_url_format(url: str) -> bool:
    """
    Validate URL format
    
    Args:
        url: URL to validate
        
    Returns:
        True if valid URL format, False otherwise
    """
    if not url or not isinstance(url, str):
        return False
    
    # Basic URL validation
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return bool(url_pattern.match(url))