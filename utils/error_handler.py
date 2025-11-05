"""
Error handling utilities for Chronarr
Provides structured error handling, retry mechanisms, and error reporting
"""
import time
import functools
from typing import Callable, Optional, Type, Union, List, Any
from pathlib import Path

from utils.logging import _log
from utils.exceptions import (
    ChronarrException,
    RetryableError,
    NetworkRetryableError,
    TemporaryFileError,
    ExternalAPIError,
    FileOperationError
)


def with_error_handling(
    operation_name: str,
    log_errors: bool = True,
    reraise: bool = True,
    fallback_value: Any = None
):
    """
    Decorator for standardized error handling
    
    Args:
        operation_name: Name of the operation for logging
        log_errors: Whether to log errors automatically
        reraise: Whether to reraise exceptions after logging
        fallback_value: Value to return if error occurs and reraise=False
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ChronarrException as e:
                if log_errors:
                    _log("ERROR", f"{operation_name} failed: {e.message}")
                    if e.details:
                        _log("DEBUG", f"{operation_name} error details: {e.details}")
                if reraise:
                    raise
                return fallback_value
            except Exception as e:
                if log_errors:
                    _log("ERROR", f"{operation_name} failed with unexpected error: {e}")
                if reraise:
                    # Wrap unexpected errors in our custom exception
                    raise ChronarrException(
                        f"{operation_name} failed: {str(e)}",
                        {"original_error": str(e), "error_type": type(e).__name__}
                    )
                return fallback_value
        return wrapper
    return decorator


def with_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    retry_on: Union[Type[Exception], List[Type[Exception]]] = None
):
    """
    Decorator for retry logic on retryable errors
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff_factor: Factor to multiply delay by after each attempt
        retry_on: Exception types to retry on (defaults to RetryableError)
    """
    if retry_on is None:
        retry_on = [RetryableError]
    elif not isinstance(retry_on, list):
        retry_on = [retry_on]
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Check if this is a retryable error
                    should_retry = any(isinstance(e, exc_type) for exc_type in retry_on)
                    
                    if not should_retry or attempt == max_attempts - 1:
                        # Don't retry or max attempts reached
                        raise
                    
                    # Use custom retry delay if available
                    retry_delay = current_delay
                    if isinstance(e, RetryableError) and e.retry_after:
                        retry_delay = e.retry_after
                    
                    _log("WARNING", f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    current_delay *= backoff_factor
            
            # This should never be reached, but just in case
            raise last_exception
        return wrapper
    return decorator


def safe_file_operation(
    operation: str,
    file_path: Union[str, Path],
    operation_func: Callable,
    *args,
    **kwargs
) -> Any:
    """
    Safely perform file operations with error handling
    
    Args:
        operation: Description of the operation
        file_path: Path to the file being operated on
        operation_func: Function to execute
        *args, **kwargs: Arguments to pass to operation_func
    
    Returns:
        Result of operation_func or None if error
    
    Raises:
        FileOperationError: If file operation fails
    """
    try:
        return operation_func(*args, **kwargs)
    except PermissionError as e:
        raise FileOperationError(operation, str(file_path), f"Permission denied: {e}")
    except FileNotFoundError as e:
        raise FileOperationError(operation, str(file_path), f"File not found: {e}")
    except OSError as e:
        # Check if this might be a temporary error
        if e.errno in [28, 122]:  # No space left, quota exceeded
            raise TemporaryFileError(str(file_path), operation, f"Disk space issue: {e}")
        raise FileOperationError(operation, str(file_path), f"OS error: {e}")
    except Exception as e:
        raise FileOperationError(operation, str(file_path), f"Unexpected error: {e}")


def safe_api_call(
    api_name: str,
    operation: str,
    api_func: Callable,
    *args,
    **kwargs
) -> Any:
    """
    Safely perform API calls with error handling
    
    Args:
        api_name: Name of the API (e.g., "Sonarr", "TMDB")
        operation: Description of the operation
        api_func: Function to execute
        *args, **kwargs: Arguments to pass to api_func
    
    Returns:
        Result of api_func
    
    Raises:
        ExternalAPIError: If API call fails
        NetworkRetryableError: If network error that can be retried
    """
    try:
        return api_func(*args, **kwargs)
    except ConnectionError as e:
        raise NetworkRetryableError(f"{api_name} API", f"Connection error: {e}")
    except TimeoutError as e:
        raise NetworkRetryableError(f"{api_name} API", f"Timeout error: {e}")
    except Exception as e:
        # Check if it's an HTTP error with status code
        status_code = getattr(e, 'status_code', None) or getattr(e, 'response', {}).get('status_code')
        response_text = getattr(e, 'text', None) or str(e)
        
        # Retry on certain HTTP status codes
        if status_code in [429, 502, 503, 504]:  # Rate limit, bad gateway, service unavailable, gateway timeout
            raise NetworkRetryableError(f"{api_name} API", f"HTTP {status_code}: {response_text}")
        
        raise ExternalAPIError(api_name, operation, status_code, response_text)


def log_structured_error(error: ChronarrException, context: Optional[str] = None) -> None:
    """
    Log structured error information
    
    Args:
        error: ChronarrException to log
        context: Additional context for the error
    """
    error_dict = error.to_dict()
    if context:
        error_dict['context'] = context
    
    _log("ERROR", f"Structured error: {error.message}")
    _log("DEBUG", f"Error details: {error_dict}")


def create_error_response(error: ChronarrException, include_details: bool = False) -> dict:
    """
    Create standardized error response for API endpoints
    
    Args:
        error: ChronarrException to convert
        include_details: Whether to include detailed error information
    
    Returns:
        Dictionary suitable for JSON response
    """
    response = {
        "status": "error",
        "error_type": error.__class__.__name__,
        "message": error.message
    }
    
    if include_details and error.details:
        response["details"] = error.details
    
    return response


def validate_required_config(config_dict: dict, required_keys: List[str]) -> None:
    """
    Validate that required configuration keys are present and not empty
    
    Args:
        config_dict: Configuration dictionary to validate
        required_keys: List of required configuration keys
    
    Raises:
        ConfigurationError: If required configuration is missing or invalid
    """
    from utils.exceptions import ConfigurationError
    
    missing_keys = []
    empty_keys = []
    
    for key in required_keys:
        if key not in config_dict:
            missing_keys.append(key)
        elif not config_dict[key]:
            empty_keys.append(key)
    
    if missing_keys:
        raise ConfigurationError(
            "missing_required_config",
            f"Missing required configuration keys: {missing_keys}",
            {"missing_keys": missing_keys}
        )
    
    if empty_keys:
        raise ConfigurationError(
            "empty_required_config",
            f"Required configuration keys are empty: {empty_keys}",
            {"empty_keys": empty_keys}
        )


class ErrorContext:
    """Context manager for adding context to errors"""
    
    def __init__(self, context: str):
        self.context = context
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type and issubclass(exc_type, ChronarrException):
            exc_val.details = exc_val.details or {}
            exc_val.details['error_context'] = self.context
        return False  # Don't suppress the exception