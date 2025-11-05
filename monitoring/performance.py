"""
Performance Monitoring and Profiling for Chronarr
Provides detailed performance analysis and optimization insights
"""
import time
import asyncio
import threading
import functools
from typing import Dict, Any, List, Optional, Callable, TypeVar, Union
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
import traceback
import sys

from monitoring.metrics import metrics


T = TypeVar('T')


@dataclass
class PerformanceProfile:
    """Performance profile for an operation"""
    operation_name: str
    total_calls: int = 0
    total_duration: float = 0.0
    min_duration: float = float('inf')
    max_duration: float = 0.0
    recent_durations: deque = field(default_factory=lambda: deque(maxlen=100))
    error_count: int = 0
    concurrent_calls: int = 0
    
    def add_measurement(self, duration: float, success: bool = True):
        """Add a performance measurement"""
        self.total_calls += 1
        self.total_duration += duration
        self.min_duration = min(self.min_duration, duration)
        self.max_duration = max(self.max_duration, duration)
        self.recent_durations.append(duration)
        
        if not success:
            self.error_count += 1
    
    def get_average_duration(self) -> float:
        """Get average duration across all calls"""
        return self.total_duration / self.total_calls if self.total_calls > 0 else 0.0
    
    def get_recent_average(self, window: int = 50) -> float:
        """Get average of recent calls"""
        recent = list(self.recent_durations)[-window:]
        return sum(recent) / len(recent) if recent else 0.0
    
    def get_percentiles(self) -> Dict[str, float]:
        """Get duration percentiles for recent calls"""
        recent = sorted(list(self.recent_durations))
        if not recent:
            return {"p50": 0, "p95": 0, "p99": 0}
        
        length = len(recent)
        return {
            "p50": recent[int(length * 0.5)] if length > 0 else 0,
            "p95": recent[int(length * 0.95)] if length > 0 else 0,
            "p99": recent[int(length * 0.99)] if length > 0 else 0
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        percentiles = self.get_percentiles()
        
        return {
            "operation_name": self.operation_name,
            "total_calls": self.total_calls,
            "error_count": self.error_count,
            "error_rate": self.error_count / self.total_calls if self.total_calls > 0 else 0,
            "concurrent_calls": self.concurrent_calls,
            "duration_stats": {
                "average": round(self.get_average_duration(), 4),
                "recent_average": round(self.get_recent_average(), 4),
                "min": round(self.min_duration if self.min_duration != float('inf') else 0, 4),
                "max": round(self.max_duration, 4),
                "p50": round(percentiles["p50"], 4),
                "p95": round(percentiles["p95"], 4),
                "p99": round(percentiles["p99"], 4)
            },
            "performance_rating": self._get_performance_rating()
        }
    
    def _get_performance_rating(self) -> str:
        """Get performance rating based on metrics"""
        avg_duration = self.get_recent_average()
        error_rate = self.error_count / self.total_calls if self.total_calls > 0 else 0
        
        if error_rate > 0.1:  # >10% error rate
            return "poor"
        elif avg_duration > 5.0:  # >5 seconds average
            return "slow"
        elif avg_duration > 1.0:  # >1 second average
            return "acceptable"
        else:
            return "excellent"


class PerformanceMonitor:
    """Advanced performance monitoring system"""
    
    def __init__(self):
        self._profiles: Dict[str, PerformanceProfile] = {}
        self._active_operations: Dict[str, float] = {}  # operation_id -> start_time
        self._lock = threading.RLock()
        
        # Slow operation tracking
        self._slow_operation_threshold = 1.0  # 1 second
        self._slow_operations = deque(maxlen=100)
        
        # Memory monitoring
        self._memory_samples = deque(maxlen=1000)
        self._memory_monitoring_enabled = True
        
        # Async operation tracking
        self._async_tasks = {}
        self._task_counter = 0
    
    def get_profile(self, operation_name: str) -> PerformanceProfile:
        """Get or create performance profile for operation"""
        with self._lock:
            if operation_name not in self._profiles:
                self._profiles[operation_name] = PerformanceProfile(operation_name)
            return self._profiles[operation_name]
    
    @contextmanager
    def monitor_operation(self, operation_name: str, **kwargs):
        """Context manager for monitoring synchronous operations"""
        start_time = time.time()
        operation_id = f"{operation_name}_{id(threading.current_thread())}_{time.time()}"
        success = True
        
        profile = self.get_profile(operation_name)
        
        with self._lock:
            profile.concurrent_calls += 1
            self._active_operations[operation_id] = start_time
        
        try:
            yield
        except Exception as e:
            success = False
            metrics.record_error("performance_monitor", str(e), operation_name)
            raise
        finally:
            end_time = time.time()
            duration = end_time - start_time
            
            with self._lock:
                profile.concurrent_calls = max(0, profile.concurrent_calls - 1)
                self._active_operations.pop(operation_id, None)
                
                # Record measurement
                profile.add_measurement(duration, success)
                
                # Track slow operations
                if duration > self._slow_operation_threshold:
                    self._slow_operations.append({
                        "operation": operation_name,
                        "duration": duration,
                        "timestamp": end_time,
                        "success": success,
                        "metadata": kwargs
                    })
                
                # Update metrics
                metrics.record_histogram(f"operation_duration", duration, {"operation": operation_name})
                if not success:
                    metrics.increment_counter("operation_errors", 1, {"operation": operation_name})
    
    @asynccontextmanager
    async def monitor_async_operation(self, operation_name: str, **kwargs):
        """Context manager for monitoring asynchronous operations"""
        start_time = time.time()
        task_id = f"{operation_name}_{self._task_counter}"
        self._task_counter += 1
        success = True
        
        profile = self.get_profile(operation_name)
        
        with self._lock:
            profile.concurrent_calls += 1
            self._async_tasks[task_id] = {
                "operation": operation_name,
                "start_time": start_time,
                "metadata": kwargs
            }
        
        try:
            yield
        except Exception as e:
            success = False
            metrics.record_error("async_performance_monitor", str(e), operation_name)
            raise
        finally:
            end_time = time.time()
            duration = end_time - start_time
            
            with self._lock:
                profile.concurrent_calls = max(0, profile.concurrent_calls - 1)
                self._async_tasks.pop(task_id, None)
                
                # Record measurement
                profile.add_measurement(duration, success)
                
                # Track slow operations
                if duration > self._slow_operation_threshold:
                    self._slow_operations.append({
                        "operation": operation_name,
                        "duration": duration,
                        "timestamp": end_time,
                        "success": success,
                        "async": True,
                        "metadata": kwargs
                    })
                
                # Update metrics
                metrics.record_histogram(f"async_operation_duration", duration, {"operation": operation_name})
                if not success:
                    metrics.increment_counter("async_operation_errors", 1, {"operation": operation_name})
    
    def monitor_function(self, operation_name: Optional[str] = None):
        """Decorator for monitoring function performance"""
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            name = operation_name or f"{func.__module__}.{func.__name__}"
            
            if asyncio.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    async with self.monitor_async_operation(name):
                        return await func(*args, **kwargs)
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    with self.monitor_operation(name):
                        return func(*args, **kwargs)
                return sync_wrapper
        
        return decorator
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary"""
        with self._lock:
            # Get top operations by various metrics
            profiles = list(self._profiles.values())
            
            # Sort by total calls
            most_called = sorted(profiles, key=lambda p: p.total_calls, reverse=True)[:10]
            
            # Sort by average duration
            slowest_avg = sorted(profiles, key=lambda p: p.get_average_duration(), reverse=True)[:10]
            
            # Sort by recent average
            slowest_recent = sorted(profiles, key=lambda p: p.get_recent_average(), reverse=True)[:10]
            
            # Sort by error rate
            highest_errors = sorted(
                [p for p in profiles if p.total_calls > 0],
                key=lambda p: p.error_count / p.total_calls,
                reverse=True
            )[:10]
            
            # Get active operations count
            total_active = sum(p.concurrent_calls for p in profiles)
            
            # Get slow operations
            recent_slow = list(self._slow_operations)[-20:]  # Last 20 slow operations
            
            return {
                "overview": {
                    "total_operations_tracked": len(profiles),
                    "total_active_operations": total_active,
                    "slow_operation_threshold_seconds": self._slow_operation_threshold,
                    "total_slow_operations": len(self._slow_operations)
                },
                "top_operations": {
                    "most_called": [p.to_dict() for p in most_called],
                    "slowest_average": [p.to_dict() for p in slowest_avg],
                    "slowest_recent": [p.to_dict() for p in slowest_recent],
                    "highest_error_rate": [p.to_dict() for p in highest_errors]
                },
                "recent_slow_operations": recent_slow,
                "performance_insights": self._generate_performance_insights(profiles)
            }
    
    def get_operation_detail(self, operation_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed performance data for specific operation"""
        with self._lock:
            if operation_name not in self._profiles:
                return None
            
            profile = self._profiles[operation_name]
            
            # Get related slow operations
            related_slow = [
                op for op in self._slow_operations
                if op["operation"] == operation_name
            ]
            
            detail = profile.to_dict()
            detail.update({
                "detailed_stats": {
                    "total_duration": round(profile.total_duration, 4),
                    "recent_durations": list(profile.recent_durations)[-20:],  # Last 20 calls
                    "slow_operations_count": len(related_slow),
                    "recent_slow_operations": related_slow[-10:]  # Last 10 slow calls
                },
                "recommendations": self._get_operation_recommendations(profile)
            })
            
            return detail
    
    def _generate_performance_insights(self, profiles: List[PerformanceProfile]) -> List[str]:
        """Generate performance optimization insights"""
        insights = []
        
        # Check for very slow operations
        very_slow = [p for p in profiles if p.get_recent_average() > 5.0]
        if very_slow:
            insights.append(f"Found {len(very_slow)} operations with >5s average duration - consider optimization")
        
        # Check for high error rates
        high_error_rate = [p for p in profiles if p.total_calls > 10 and (p.error_count / p.total_calls) > 0.1]
        if high_error_rate:
            insights.append(f"Found {len(high_error_rate)} operations with >10% error rate - investigate failures")
        
        # Check for high concurrency
        high_concurrency = [p for p in profiles if p.concurrent_calls > 5]
        if high_concurrency:
            insights.append(f"Found {len(high_concurrency)} operations with high concurrency - may need rate limiting")
        
        # Check total active operations
        total_active = sum(p.concurrent_calls for p in profiles)
        if total_active > 20:
            insights.append(f"High total concurrent operations ({total_active}) - system may be under load")
        
        # Performance trends
        recent_slow_count = len([op for op in self._slow_operations if op["timestamp"] > time.time() - 300])
        if recent_slow_count > 10:
            insights.append(f"Many slow operations recently ({recent_slow_count} in last 5 minutes)")
        
        if not insights:
            insights.append("No significant performance issues detected")
        
        return insights
    
    def _get_operation_recommendations(self, profile: PerformanceProfile) -> List[str]:
        """Get recommendations for optimizing specific operation"""
        recommendations = []
        
        avg_duration = profile.get_recent_average()
        error_rate = profile.error_count / profile.total_calls if profile.total_calls > 0 else 0
        
        if avg_duration > 5.0:
            recommendations.append("Consider breaking down this operation into smaller parts")
            recommendations.append("Review database queries and file I/O for optimization opportunities")
        elif avg_duration > 1.0:
            recommendations.append("Monitor for potential optimization opportunities")
        
        if error_rate > 0.1:
            recommendations.append("High error rate - investigate common failure causes")
            recommendations.append("Consider adding retry logic or better error handling")
        
        if profile.concurrent_calls > 5:
            recommendations.append("High concurrency - consider adding rate limiting")
            recommendations.append("Review resource usage and potential bottlenecks")
        
        percentiles = profile.get_percentiles()
        if percentiles["p99"] > percentiles["p50"] * 3:
            recommendations.append("High latency variance - investigate outlier causes")
        
        if not recommendations:
            recommendations.append("Performance appears optimal for this operation")
        
        return recommendations
    
    def set_slow_operation_threshold(self, threshold_seconds: float):
        """Set threshold for what constitutes a slow operation"""
        with self._lock:
            self._slow_operation_threshold = threshold_seconds
    
    def clear_profiles(self, operation_names: Optional[List[str]] = None):
        """Clear performance profiles for specific operations or all"""
        with self._lock:
            if operation_names:
                for name in operation_names:
                    self._profiles.pop(name, None)
            else:
                self._profiles.clear()
                self._slow_operations.clear()


# Global performance monitor instance
performance_monitor = PerformanceMonitor()

# Decorator shortcuts
def monitor_performance(operation_name: Optional[str] = None):
    """Shortcut decorator for performance monitoring"""
    return performance_monitor.monitor_function(operation_name)

def monitor_sync_operation(operation_name: str, **kwargs):
    """Shortcut for synchronous operation monitoring"""
    return performance_monitor.monitor_operation(operation_name, **kwargs)

def monitor_async_operation(operation_name: str, **kwargs):
    """Shortcut for asynchronous operation monitoring"""
    return performance_monitor.monitor_async_operation(operation_name, **kwargs)