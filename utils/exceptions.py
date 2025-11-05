"""
Custom exceptions for Chronarr
Provides structured error handling and better error reporting
"""
from typing import Optional, Dict, Any


class ChronarrException(Exception):
    """Base exception for all Chronarr errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for structured logging"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details
        }


class MediaPathNotFoundError(ChronarrException):
    """Raised when media directory cannot be found"""
    
    def __init__(self, media_type: str, title: str, imdb_id: Optional[str] = None, search_paths: Optional[list] = None):
        details = {
            "media_type": media_type,
            "title": title,
            "imdb_id": imdb_id,
            "search_paths": [str(p) for p in (search_paths or [])]
        }
        message = f"{media_type.title()} directory not found: {title}"
        if imdb_id:
            message += f" (IMDb: {imdb_id})"
        super().__init__(message, details)


class IMDbIDNotFoundError(ChronarrException):
    """Raised when IMDb ID cannot be extracted from path or files"""
    
    def __init__(self, path: str, media_type: str = "media"):
        details = {
            "path": path,
            "media_type": media_type
        }
        message = f"No IMDb ID found for {media_type}: {path}"
        super().__init__(message, details)


class WebhookProcessingError(ChronarrException):
    """Raised when webhook processing fails"""
    
    def __init__(self, webhook_type: str, reason: str, payload: Optional[Dict] = None):
        details = {
            "webhook_type": webhook_type,
            "reason": reason,
            "payload": payload
        }
        message = f"{webhook_type} webhook processing failed: {reason}"
        super().__init__(message, details)


class ExternalAPIError(ChronarrException):
    """Raised when external API calls fail"""
    
    def __init__(self, api_name: str, operation: str, status_code: Optional[int] = None, response: Optional[str] = None):
        details = {
            "api_name": api_name,
            "operation": operation,
            "status_code": status_code,
            "response": response
        }
        message = f"{api_name} API error during {operation}"
        if status_code:
            message += f" (HTTP {status_code})"
        super().__init__(message, details)


class DatabaseError(ChronarrException):
    """Raised when database operations fail"""
    
    def __init__(self, operation: str, table: Optional[str] = None, original_error: Optional[Exception] = None):
        details = {
            "operation": operation,
            "table": table,
            "original_error": str(original_error) if original_error else None
        }
        message = f"Database error during {operation}"
        if table:
            message += f" on table {table}"
        super().__init__(message, details)


class NFOCreationError(ChronarrException):
    """Raised when NFO file creation fails"""
    
    def __init__(self, nfo_path: str, reason: str, media_type: str = "media"):
        details = {
            "nfo_path": nfo_path,
            "reason": reason,
            "media_type": media_type
        }
        message = f"Failed to create {media_type} NFO file: {reason}"
        super().__init__(message, details)


class ConfigurationError(ChronarrException):
    """Raised when configuration is invalid or missing"""
    
    def __init__(self, setting: str, reason: str, current_value: Optional[Any] = None):
        details = {
            "setting": setting,
            "reason": reason,
            "current_value": current_value
        }
        message = f"Configuration error for {setting}: {reason}"
        super().__init__(message, details)


class FileOperationError(ChronarrException):
    """Raised when file operations fail"""
    
    def __init__(self, operation: str, file_path: str, reason: str):
        details = {
            "operation": operation,
            "file_path": file_path,
            "reason": reason
        }
        message = f"File {operation} failed for {file_path}: {reason}"
        super().__init__(message, details)


class DateProcessingError(ChronarrException):
    """Raised when date processing or parsing fails"""
    
    def __init__(self, date_value: str, operation: str, media_type: str = "media"):
        details = {
            "date_value": date_value,
            "operation": operation,
            "media_type": media_type
        }
        message = f"Date processing error during {operation} for {media_type}: {date_value}"
        super().__init__(message, details)


class RetryableError(ChronarrException):
    """Base class for errors that can be retried"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, retry_after: Optional[int] = None):
        super().__init__(message, details)
        self.retry_after = retry_after  # Seconds to wait before retry


class NetworkRetryableError(RetryableError):
    """Network errors that can be retried"""
    
    def __init__(self, url: str, reason: str, retry_after: Optional[int] = 30):
        details = {"url": url, "reason": reason}
        message = f"Network error for {url}: {reason}"
        super().__init__(message, details, retry_after)


class TemporaryFileError(RetryableError):
    """Temporary file system errors that can be retried"""
    
    def __init__(self, file_path: str, operation: str, reason: str, retry_after: Optional[int] = 5):
        details = {"file_path": file_path, "operation": operation, "reason": reason}
        message = f"Temporary file error during {operation} for {file_path}: {reason}"
        super().__init__(message, details, retry_after)