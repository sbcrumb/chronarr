"""
Enhanced Logging System for Chronarr
Provides structured logging with correlation IDs, request tracing, and monitoring integration
"""
import logging
import json
import time
import uuid
import threading
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime
import sys
import traceback

from monitoring.metrics import metrics


# Thread-local storage for correlation context
_context = threading.local()


@dataclass
class LogContext:
    """Logging context with correlation and tracing information"""
    correlation_id: str
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    operation: Optional[str] = None
    media_type: Optional[str] = None
    media_title: Optional[str] = None
    webhook_type: Optional[str] = None
    processing_stage: Optional[str] = None
    additional_fields: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for logging"""
        context = {
            "correlation_id": self.correlation_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Add non-None fields
        for field_name in ["request_id", "user_id", "operation", "media_type", 
                          "media_title", "webhook_type", "processing_stage"]:
            value = getattr(self, field_name)
            if value is not None:
                context[field_name] = value
        
        # Add additional fields
        context.update(self.additional_fields)
        
        return context


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def __init__(self, include_context: bool = True):
        super().__init__()
        self.include_context = include_context
    
    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add thread information
        log_entry["thread"] = {
            "id": record.thread,
            "name": record.threadName
        }
        
        # Add correlation context if available
        if self.include_context and hasattr(_context, 'log_context'):
            log_entry["context"] = _context.log_context.to_dict()
        
        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # Add any extra fields passed to log call
        if hasattr(record, 'extra_fields') and record.extra_fields:
            log_entry["extra"] = record.extra_fields
        
        # Add performance metrics if available
        if hasattr(record, 'performance_data') and record.performance_data:
            log_entry["performance"] = record.performance_data
        
        return json.dumps(log_entry, default=str, ensure_ascii=False)


class CorrelationIDFilter(logging.Filter):
    """Filter to add correlation ID to log records"""
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Add correlation ID to record if available
        if hasattr(_context, 'log_context'):
            record.correlation_id = _context.log_context.correlation_id
        else:
            record.correlation_id = "no-correlation"
        
        return True


class EnhancedLogger:
    """Enhanced logger with correlation IDs and structured logging"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name
        
        # Track log events for metrics
        self._log_counts = {"debug": 0, "info": 0, "warning": 0, "error": 0, "critical": 0}
    
    def _log_with_context(self, level: int, message: str, extra_fields: Optional[Dict[str, Any]] = None,
                         performance_data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log with enhanced context and metrics tracking"""
        
        # Track log counts for metrics
        level_name = logging.getLevelName(level).lower()
        if level_name in self._log_counts:
            self._log_counts[level_name] += 1
            metrics.increment_counter(f"log_messages", 1, {"level": level_name, "logger": self.name})
        
        # Create log record with extra data
        extra = {}
        if extra_fields:
            extra['extra_fields'] = extra_fields
        if performance_data:
            extra['performance_data'] = performance_data
        
        # Log the message
        self.logger.log(level, message, extra=extra, **kwargs)
        
        # Track errors in metrics
        if level >= logging.ERROR:
            metrics.record_error("logging_error", message, self.name)
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self._log_with_context(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        self._log_with_context(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self._log_with_context(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message"""
        self._log_with_context(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message"""
        self._log_with_context(logging.CRITICAL, message, **kwargs)
    
    def exception(self, message: str, **kwargs):
        """Log exception with traceback"""
        kwargs['exc_info'] = True
        self._log_with_context(logging.ERROR, message, **kwargs)
    
    def log_operation_start(self, operation: str, **context_fields):
        """Log the start of an operation"""
        self.info(f"Starting operation: {operation}", 
                 extra_fields={"operation_event": "start", "operation": operation, **context_fields})
    
    def log_operation_end(self, operation: str, success: bool = True, duration: Optional[float] = None, **context_fields):
        """Log the end of an operation"""
        outcome = "success" if success else "failure"
        extra = {"operation_event": "end", "operation": operation, "outcome": outcome, **context_fields}
        
        if duration is not None:
            extra["duration_seconds"] = duration
        
        level = logging.INFO if success else logging.ERROR
        self._log_with_context(level, f"Operation {outcome}: {operation}", extra_fields=extra)
    
    def log_webhook_received(self, webhook_type: str, payload_size: int, **context_fields):
        """Log webhook reception"""
        self.info(f"Webhook received: {webhook_type}", 
                 extra_fields={
                     "event_type": "webhook_received",
                     "webhook_type": webhook_type,
                     "payload_size_bytes": payload_size,
                     **context_fields
                 })
    
    def log_nfo_operation(self, operation: str, file_path: str, success: bool = True, **context_fields):
        """Log NFO file operations"""
        outcome = "success" if success else "failure"
        level = logging.INFO if success else logging.ERROR
        
        self._log_with_context(level, f"NFO {operation} {outcome}: {file_path}",
                              extra_fields={
                                  "event_type": "nfo_operation",
                                  "nfo_operation": operation,
                                  "file_path": file_path,
                                  "outcome": outcome,
                                  **context_fields
                              })
    
    def log_performance_metrics(self, operation: str, duration: float, success: bool = True, **metrics_data):
        """Log performance metrics"""
        self.debug(f"Performance: {operation} took {duration:.3f}s",
                  performance_data={
                      "operation": operation,
                      "duration_seconds": duration,
                      "success": success,
                      **metrics_data
                  })
    
    def get_log_stats(self) -> Dict[str, int]:
        """Get logging statistics"""
        return self._log_counts.copy()


def setup_enhanced_logging(
    log_level: str = "INFO", 
    structured: bool = True,
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> None:
    """Setup enhanced logging configuration"""
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    if structured:
        # Use structured JSON formatter
        formatter = StructuredFormatter(include_context=True)
    else:
        # Use simple text formatter with correlation ID
        formatter = logging.Formatter(
            '%(asctime)s [%(correlation_id)s] %(levelname)s %(name)s: %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    console_handler.addFilter(CorrelationIDFilter())
    root_logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        from logging.handlers import RotatingFileHandler
        
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(CorrelationIDFilter())
        root_logger.addHandler(file_handler)
    
    # Reduce noise from external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def get_enhanced_logger(name: str) -> EnhancedLogger:
    """Get enhanced logger instance"""
    return EnhancedLogger(name)


def set_log_context(
    correlation_id: Optional[str] = None,
    request_id: Optional[str] = None,
    operation: Optional[str] = None,
    **kwargs
) -> LogContext:
    """Set logging context for current thread"""
    
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    
    context = LogContext(
        correlation_id=correlation_id,
        request_id=request_id,
        operation=operation,
        **kwargs
    )
    
    _context.log_context = context
    return context


def get_log_context() -> Optional[LogContext]:
    """Get current logging context"""
    return getattr(_context, 'log_context', None)


def clear_log_context():
    """Clear logging context for current thread"""
    if hasattr(_context, 'log_context'):
        delattr(_context, 'log_context')


@contextmanager
def log_context(correlation_id: Optional[str] = None, **context_fields):
    """Context manager for scoped logging context"""
    original_context = get_log_context()
    
    try:
        # Set new context
        new_context = set_log_context(correlation_id=correlation_id, **context_fields)
        yield new_context
    finally:
        # Restore original context
        if original_context:
            _context.log_context = original_context
        else:
            clear_log_context()


@contextmanager
def log_operation(operation: str, logger: Optional[EnhancedLogger] = None, **context_fields):
    """Context manager for logging operation start/end with timing"""
    if logger is None:
        logger = get_enhanced_logger(__name__)
    
    start_time = time.time()
    success = True
    
    # Update context with operation
    current_context = get_log_context()
    if current_context:
        current_context.operation = operation
        current_context.processing_stage = "executing"
    
    logger.log_operation_start(operation, **context_fields)
    
    try:
        yield
    except Exception as e:
        success = False
        logger.exception(f"Operation failed: {operation}", 
                        extra_fields={"operation": operation, "error": str(e), **context_fields})
        raise
    finally:
        duration = time.time() - start_time
        logger.log_operation_end(operation, success, duration, **context_fields)
        
        # Update metrics
        metrics.record_operation_duration(operation, duration, success)


def trace_request(request_id: Optional[str] = None, **context_fields):
    """Decorator/context manager for request tracing"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            correlation_id = str(uuid.uuid4())
            req_id = request_id or f"req_{int(time.time())}"
            
            with log_context(correlation_id=correlation_id, request_id=req_id, **context_fields):
                return func(*args, **kwargs)
        return wrapper
    
    # Can be used as context manager or decorator
    if request_id is None and len(context_fields) == 1 and callable(list(context_fields.values())[0]):
        # Used as decorator without parentheses
        func = list(context_fields.values())[0]
        return decorator(func)
    else:
        # Used as decorator with parameters or context manager
        return decorator


# Module-level logger for this module
logger = get_enhanced_logger(__name__)


def get_logging_stats() -> Dict[str, Any]:
    """Get comprehensive logging statistics"""
    # Collect stats from all enhanced loggers
    total_stats = {"debug": 0, "info": 0, "warning": 0, "error": 0, "critical": 0}
    
    # This is a simplified version - in practice you'd track all logger instances
    return {
        "total_log_messages": sum(total_stats.values()),
        "by_level": total_stats,
        "structured_logging_enabled": True,
        "correlation_tracking_enabled": True
    }