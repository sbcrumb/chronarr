"""
Metrics Collection System for Chronarr
Provides performance monitoring, counters, and operational metrics
"""
import time
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import contextmanager
import asyncio


@dataclass
class MetricValue:
    """Individual metric value with timestamp"""
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass 
class TimeSeriesMetric:
    """Time series metric with historical data"""
    name: str
    values: deque = field(default_factory=lambda: deque(maxlen=1000))
    total: float = 0.0
    count: int = 0
    
    def add_value(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Add a new metric value"""
        metric_value = MetricValue(value, labels=labels or {})
        self.values.append(metric_value)
        self.total += value
        self.count += 1
    
    def get_average(self, window_seconds: int = 300) -> float:
        """Get average value over time window"""
        cutoff_time = time.time() - window_seconds
        recent_values = [v.value for v in self.values if v.timestamp > cutoff_time]
        return sum(recent_values) / len(recent_values) if recent_values else 0.0
    
    def get_rate_per_minute(self, window_seconds: int = 300) -> float:
        """Get rate per minute over time window"""
        cutoff_time = time.time() - window_seconds
        recent_count = len([v for v in self.values if v.timestamp > cutoff_time])
        return (recent_count / window_seconds) * 60 if window_seconds > 0 else 0.0


class MetricsCollector:
    """Central metrics collection system"""
    
    def __init__(self):
        self._metrics: Dict[str, TimeSeriesMetric] = {}
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._start_time = time.time()
        self._lock = threading.RLock()
        
        # Processing metrics
        self._active_operations = 0
        self._operation_durations = deque(maxlen=1000)
        
        # Error tracking
        self._error_counts = defaultdict(int)
        self._last_errors = deque(maxlen=100)
        
        # System metrics
        self._system_stats_cache = {}
        self._system_stats_last_update = 0
        self._system_stats_cache_ttl = 30  # 30 seconds
    
    def increment_counter(self, name: str, value: int = 1, labels: Optional[Dict[str, str]] = None):
        """Increment a counter metric"""
        with self._lock:
            full_name = self._build_metric_name(name, labels)
            self._counters[full_name] += value
            
            # Also track in time series for rate calculations
            if name not in self._metrics:
                self._metrics[name] = TimeSeriesMetric(name)
            self._metrics[name].add_value(value, labels)
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge metric value"""
        with self._lock:
            full_name = self._build_metric_name(name, labels)
            self._gauges[full_name] = value
    
    def record_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a histogram value"""
        with self._lock:
            full_name = self._build_metric_name(name, labels)
            self._histograms[full_name].append(value)
            
            # Keep only recent values (last 1000)
            if len(self._histograms[full_name]) > 1000:
                self._histograms[full_name] = self._histograms[full_name][-1000:]
            
            # Also track in time series
            if name not in self._metrics:
                self._metrics[name] = TimeSeriesMetric(name)
            self._metrics[name].add_value(value, labels)
    
    def record_operation_duration(self, operation: str, duration: float, success: bool = True):
        """Record operation duration and outcome"""
        with self._lock:
            # Record duration
            self.record_histogram(f"operation_duration_{operation}", duration)
            
            # Record outcome
            outcome = "success" if success else "error"
            self.increment_counter(f"operation_total", 1, {"operation": operation, "outcome": outcome})
            
            # Track active operations
            if operation.endswith("_start"):
                self._active_operations += 1
            elif operation.endswith("_end"):
                self._active_operations = max(0, self._active_operations - 1)
    
    def record_error(self, error_type: str, error_message: str, operation: Optional[str] = None):
        """Record an error occurrence"""
        with self._lock:
            self._error_counts[error_type] += 1
            
            error_info = {
                "type": error_type,
                "message": error_message,
                "operation": operation,
                "timestamp": time.time()
            }
            self._last_errors.append(error_info)
            
            # Increment error counter
            labels = {"error_type": error_type}
            if operation:
                labels["operation"] = operation
            self.increment_counter("errors_total", 1, labels)
    
    @contextmanager
    def operation_timer(self, operation: str):
        """Context manager for timing operations"""
        start_time = time.time()
        success = True
        
        try:
            self.record_operation_duration(f"{operation}_start", 0)
            yield
        except Exception as e:
            success = False
            self.record_error("operation_error", str(e), operation)
            raise
        finally:
            duration = time.time() - start_time
            self.record_operation_duration(operation, duration, success)
            self.record_operation_duration(f"{operation}_end", 0)
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system resource metrics"""
        now = time.time()
        
        # Use cached values if recent
        if (now - self._system_stats_last_update) < self._system_stats_cache_ttl:
            return self._system_stats_cache
        
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            
            # Memory metrics
            memory = psutil.virtual_memory()
            
            # Disk metrics for database path
            try:
                from config.settings import config
                db_disk = psutil.disk_usage(str(config.db_path.parent))
            except:
                db_disk = None
            
            # Process metrics
            process = psutil.Process()
            process_memory = process.memory_info()
            
            self._system_stats_cache = {
                "cpu_percent": cpu_percent,
                "cpu_count": cpu_count,
                "memory_total": memory.total,
                "memory_available": memory.available,
                "memory_percent": memory.percent,
                "process_memory_rss": process_memory.rss,
                "process_memory_vms": process_memory.vms,
                "db_disk_free": db_disk.free if db_disk else None,
                "db_disk_total": db_disk.total if db_disk else None,
                "active_operations": self._active_operations,
                "uptime_seconds": now - self._start_time
            }
            
            self._system_stats_last_update = now
            
        except Exception as e:
            # Return basic metrics if detailed collection fails
            self._system_stats_cache = {
                "uptime_seconds": now - self._start_time,
                "active_operations": self._active_operations,
                "error": str(e)
            }
        
        return self._system_stats_cache
    
    def get_processing_metrics(self) -> Dict[str, Any]:
        """Get processing-related metrics"""
        with self._lock:
            # Calculate rates and averages
            webhook_rate = self._metrics.get("webhooks_received", TimeSeriesMetric("webhooks_received")).get_rate_per_minute()
            nfo_rate = self._metrics.get("nfo_created", TimeSeriesMetric("nfo_created")).get_rate_per_minute()
            
            avg_processing_time = 0.0
            if "processing_duration" in self._metrics:
                avg_processing_time = self._metrics["processing_duration"].get_average()
            
            return {
                "webhooks_received_per_minute": webhook_rate,
                "nfo_files_created_per_minute": nfo_rate,
                "average_processing_time_seconds": avg_processing_time,
                "active_operations": self._active_operations,
                "total_webhooks": self._counters.get("webhooks_received", 0),
                "total_nfo_created": self._counters.get("nfo_created", 0),
                "total_errors": sum(self._error_counts.values())
            }
    
    def get_error_metrics(self) -> Dict[str, Any]:
        """Get error-related metrics"""
        with self._lock:
            recent_errors = []
            cutoff_time = time.time() - 3600  # Last hour
            
            for error in self._last_errors:
                if error["timestamp"] > cutoff_time:
                    recent_errors.append({
                        "type": error["type"],
                        "message": error["message"][:100],  # Truncate long messages
                        "operation": error["operation"],
                        "timestamp": error["timestamp"]
                    })
            
            return {
                "error_counts_by_type": dict(self._error_counts),
                "recent_errors": recent_errors[-10:],  # Last 10 errors
                "total_errors": sum(self._error_counts.values()),
                "error_rate_per_minute": len([e for e in self._last_errors if e["timestamp"] > time.time() - 300]) / 5
            }
    
    def get_prometheus_metrics(self) -> str:
        """Generate Prometheus-compatible metrics format"""
        lines = []
        
        # Add help and type information
        lines.append("# HELP chronarr_webhooks_total Total number of webhooks received")
        lines.append("# TYPE chronarr_webhooks_total counter")
        
        with self._lock:
            # Counters
            for name, value in self._counters.items():
                metric_name = f"chronarr_{name.replace('-', '_')}"
                lines.append(f"{metric_name} {value}")
            
            # Gauges
            lines.append("# HELP chronarr_active_operations Current number of active operations")
            lines.append("# TYPE chronarr_active_operations gauge")
            lines.append(f"chronarr_active_operations {self._active_operations}")
            
            # System metrics
            system_metrics = self.get_system_metrics()
            for key, value in system_metrics.items():
                if isinstance(value, (int, float)) and value is not None:
                    metric_name = f"chronarr_system_{key}"
                    lines.append(f"{metric_name} {value}")
        
        return "\n".join(lines)
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics in a structured format"""
        return {
            "system": self.get_system_metrics(),
            "processing": self.get_processing_metrics(),
            "errors": self.get_error_metrics(),
            "timestamp": time.time(),
            "uptime_seconds": time.time() - self._start_time
        }
    
    def reset_metrics(self, metric_types: Optional[List[str]] = None):
        """Reset specific metric types or all metrics"""
        with self._lock:
            if not metric_types or "counters" in metric_types:
                self._counters.clear()
            
            if not metric_types or "histograms" in metric_types:
                self._histograms.clear()
            
            if not metric_types or "errors" in metric_types:
                self._error_counts.clear()
                self._last_errors.clear()
            
            if not metric_types or "timeseries" in metric_types:
                self._metrics.clear()
    
    def _build_metric_name(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """Build metric name with labels"""
        if not labels:
            return name
        
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Global metrics collector instance
metrics = MetricsCollector()


# Convenience functions for common operations
def track_webhook_received(webhook_type: str):
    """Track webhook received"""
    metrics.increment_counter("webhooks_received", 1, {"type": webhook_type})


def track_nfo_created(media_type: str, success: bool = True):
    """Track NFO file creation"""
    outcome = "success" if success else "error"
    metrics.increment_counter("nfo_created", 1, {"media_type": media_type, "outcome": outcome})


def track_api_call(api_name: str, duration: float, success: bool = True):
    """Track external API call"""
    metrics.record_histogram(f"api_call_duration", duration, {"api": api_name})
    outcome = "success" if success else "error" 
    metrics.increment_counter("api_calls_total", 1, {"api": api_name, "outcome": outcome})


def track_database_operation(operation: str, duration: float, success: bool = True):
    """Track database operation"""
    metrics.record_histogram("database_operation_duration", duration, {"operation": operation})
    outcome = "success" if success else "error"
    metrics.increment_counter("database_operations_total", 1, {"operation": operation, "outcome": outcome})


def track_file_operation(operation: str, duration: float, success: bool = True):
    """Track file system operation"""
    metrics.record_histogram("file_operation_duration", duration, {"operation": operation})
    outcome = "success" if success else "error"
    metrics.increment_counter("file_operations_total", 1, {"operation": operation, "outcome": outcome})