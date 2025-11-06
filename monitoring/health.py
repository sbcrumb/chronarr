"""
Health Check System for Chronarr
Provides health and readiness endpoints for monitoring and orchestration
"""
import time
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from config.runtime_validator import RuntimeValidator, HealthCheckResult
from monitoring.metrics import metrics
from version_utils import get_version


class HealthStatus(Enum):
    """Health check status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    """Individual health check result"""
    name: str
    status: HealthStatus
    message: str
    duration_ms: float
    details: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 2),
            "details": self.details or {}
        }


@dataclass
class OverallHealth:
    """Overall system health status"""
    status: HealthStatus
    checks: List[HealthCheck]
    timestamp: float
    uptime_seconds: float
    version: str = field(default_factory=get_version)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "version": self.version,
            "checks": [check.to_dict() for check in self.checks],
            "summary": {
                "total_checks": len(self.checks),
                "healthy_checks": len([c for c in self.checks if c.status == HealthStatus.HEALTHY]),
                "degraded_checks": len([c for c in self.checks if c.status == HealthStatus.DEGRADED]),
                "unhealthy_checks": len([c for c in self.checks if c.status == HealthStatus.UNHEALTHY])
            }
        }


class HealthChecker:
    """Comprehensive health checking system"""
    
    def __init__(self):
        self.start_time = time.time()
        self._last_health_check = None
        self._health_check_cache_ttl = 30  # Cache for 30 seconds
        self._runtime_validator = None
    
    def _get_runtime_validator(self):
        """Get runtime validator instance"""
        if self._runtime_validator is None:
            try:
                from config.settings import config
                self._runtime_validator = RuntimeValidator(config)
            except Exception as e:
                # Create a dummy validator if config fails
                self._runtime_validator = None
        return self._runtime_validator
    
    async def check_basic_health(self) -> HealthCheck:
        """Basic health check - always succeeds if service is running"""
        start_time = time.time()
        
        try:
            # Basic service availability
            uptime = time.time() - self.start_time
            
            if uptime < 30:
                status = HealthStatus.DEGRADED
                message = f"Service starting up (uptime: {uptime:.1f}s)"
            else:
                status = HealthStatus.HEALTHY
                message = f"Service running normally (uptime: {uptime:.1f}s)"
            
            return HealthCheck(
                name="basic",
                status=status,
                message=message,
                duration_ms=(time.time() - start_time) * 1000,
                details={"uptime_seconds": uptime}
            )
            
        except Exception as e:
            return HealthCheck(
                name="basic",
                status=HealthStatus.UNHEALTHY,
                message=f"Basic health check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000
            )
    
    async def check_filesystem_health(self) -> HealthCheck:
        """Check filesystem access for media paths"""
        start_time = time.time()
        
        try:
            from config.settings import config
            
            accessible_paths = 0
            total_paths = len(config.tv_paths) + len(config.movie_paths)
            issues = []
            
            # Check TV paths
            for path in config.tv_paths:
                try:
                    if path.exists() and path.is_dir():
                        # Try to read directory
                        list(path.iterdir())
                        accessible_paths += 1
                    else:
                        issues.append(f"TV path not accessible: {path}")
                except PermissionError:
                    issues.append(f"TV path permission denied: {path}")
                except Exception as e:
                    issues.append(f"TV path error {path}: {e}")
            
            # Check movie paths
            for path in config.movie_paths:
                try:
                    if path.exists() and path.is_dir():
                        list(path.iterdir())
                        accessible_paths += 1
                    else:
                        issues.append(f"Movie path not accessible: {path}")
                except PermissionError:
                    issues.append(f"Movie path permission denied: {path}")
                except Exception as e:
                    issues.append(f"Movie path error {path}: {e}")
            
            # Determine status
            if accessible_paths == total_paths:
                status = HealthStatus.HEALTHY
                message = f"All {total_paths} media paths accessible"
            elif accessible_paths > 0:
                status = HealthStatus.DEGRADED
                message = f"{accessible_paths}/{total_paths} media paths accessible"
            else:
                status = HealthStatus.UNHEALTHY
                message = "No media paths accessible"
            
            return HealthCheck(
                name="filesystem",
                status=status,
                message=message,
                duration_ms=(time.time() - start_time) * 1000,
                details={
                    "accessible_paths": accessible_paths,
                    "total_paths": total_paths,
                    "issues": issues[:5]  # Limit to first 5 issues
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="filesystem",
                status=HealthStatus.UNHEALTHY,
                message=f"Filesystem check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000
            )
    
    async def check_database_health(self) -> HealthCheck:
        """Check database connectivity and performance"""
        start_time = time.time()
        
        try:
            import sqlite3
            from config.settings import config
            
            # Test local database
            db_path = config.db_path
            
            def test_db():
                with sqlite3.connect(str(db_path), timeout=5) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                    table_count = cursor.fetchone()[0]
                    return table_count
            
            # Run database test
            table_count = await asyncio.get_event_loop().run_in_executor(None, test_db)
            
            duration = (time.time() - start_time) * 1000
            
            if duration < 100:  # < 100ms is good
                status = HealthStatus.HEALTHY
                message = f"Database responsive ({duration:.1f}ms, {table_count} tables)"
            elif duration < 1000:  # < 1s is acceptable
                status = HealthStatus.DEGRADED
                message = f"Database slow ({duration:.1f}ms, {table_count} tables)"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"Database very slow ({duration:.1f}ms)"
            
            return HealthCheck(
                name="database",
                status=status,
                message=message,
                duration_ms=duration,
                details={
                    "db_path": str(db_path),
                    "table_count": table_count,
                    "response_time_category": "fast" if duration < 100 else "slow" if duration < 1000 else "very_slow"
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000,
                details={"error": str(e)}
            )
    
    async def check_external_apis_health(self) -> HealthCheck:
        """Check external API connectivity"""
        start_time = time.time()
        
        try:
            import aiohttp
            from config.settings import config
            
            api_results = []
            apis_tested = 0
            apis_healthy = 0
            
            timeout = aiohttp.ClientTimeout(total=5)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Test Radarr API if configured
                if hasattr(config, 'radarr_url') and config.radarr_url:
                    apis_tested += 1
                    try:
                        test_url = f"{config.radarr_url.rstrip('/')}/api/v3/health"
                        async with session.get(test_url) as response:
                            if response.status == 200:
                                apis_healthy += 1
                                api_results.append({"api": "radarr", "status": "healthy"})
                            else:
                                api_results.append({"api": "radarr", "status": f"unhealthy (HTTP {response.status})"})
                    except Exception as e:
                        api_results.append({"api": "radarr", "status": f"error: {str(e)[:50]}"})
                
                # Test Sonarr API if configured
                if hasattr(config, 'sonarr_url') and config.sonarr_url:
                    apis_tested += 1
                    try:
                        test_url = f"{config.sonarr_url.rstrip('/')}/api/v3/health"
                        async with session.get(test_url) as response:
                            if response.status == 200:
                                apis_healthy += 1
                                api_results.append({"api": "sonarr", "status": "healthy"})
                            else:
                                api_results.append({"api": "sonarr", "status": f"unhealthy (HTTP {response.status})"})
                    except Exception as e:
                        api_results.append({"api": "sonarr", "status": f"error: {str(e)[:50]}"})
            
            # Determine overall API health
            if apis_tested == 0:
                status = HealthStatus.HEALTHY
                message = "No external APIs configured"
            elif apis_healthy == apis_tested:
                status = HealthStatus.HEALTHY
                message = f"All {apis_tested} external APIs healthy"
            elif apis_healthy > 0:
                status = HealthStatus.DEGRADED
                message = f"{apis_healthy}/{apis_tested} external APIs healthy"
            else:
                status = HealthStatus.UNHEALTHY
                message = "No external APIs responding"
            
            return HealthCheck(
                name="external_apis",
                status=status,
                message=message,
                duration_ms=(time.time() - start_time) * 1000,
                details={
                    "apis_tested": apis_tested,
                    "apis_healthy": apis_healthy,
                    "api_results": api_results
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="external_apis",
                status=HealthStatus.UNHEALTHY,
                message=f"API health check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000
            )
    
    async def check_performance_health(self) -> HealthCheck:
        """Check system performance metrics"""
        start_time = time.time()
        
        try:
            system_metrics = metrics.get_system_metrics()
            processing_metrics = metrics.get_processing_metrics()
            
            issues = []
            warnings = []
            
            # Check CPU usage
            cpu_percent = system_metrics.get("cpu_percent", 0)
            if cpu_percent > 90:
                issues.append(f"High CPU usage: {cpu_percent:.1f}%")
            elif cpu_percent > 70:
                warnings.append(f"Elevated CPU usage: {cpu_percent:.1f}%")
            
            # Check memory usage
            memory_percent = system_metrics.get("memory_percent", 0)
            if memory_percent > 90:
                issues.append(f"High memory usage: {memory_percent:.1f}%")
            elif memory_percent > 80:
                warnings.append(f"Elevated memory usage: {memory_percent:.1f}%")
            
            # Check disk space
            if "db_disk_free" in system_metrics and system_metrics["db_disk_free"]:
                free_space_gb = system_metrics["db_disk_free"] / (1024**3)
                if free_space_gb < 1:
                    issues.append(f"Low disk space: {free_space_gb:.1f}GB free")
                elif free_space_gb < 5:
                    warnings.append(f"Low disk space: {free_space_gb:.1f}GB free")
            
            # Check active operations
            active_ops = system_metrics.get("active_operations", 0)
            if active_ops > 10:
                warnings.append(f"High concurrent operations: {active_ops}")
            
            # Determine status
            if issues:
                status = HealthStatus.UNHEALTHY
                message = f"Performance issues detected: {', '.join(issues[:2])}"
            elif warnings:
                status = HealthStatus.DEGRADED
                message = f"Performance warnings: {', '.join(warnings[:2])}"
            else:
                status = HealthStatus.HEALTHY
                message = "System performance normal"
            
            return HealthCheck(
                name="performance",
                status=status,
                message=message,
                duration_ms=(time.time() - start_time) * 1000,
                details={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "active_operations": active_ops,
                    "issues": issues,
                    "warnings": warnings
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="performance",
                status=HealthStatus.DEGRADED,
                message=f"Performance check failed: {e}",
                duration_ms=(time.time() - start_time) * 1000
            )
    
    async def get_full_health_status(self) -> OverallHealth:
        """Get comprehensive health status"""
        start_time = time.time()
        
        # Run all health checks concurrently
        checks = await asyncio.gather(
            self.check_basic_health(),
            self.check_filesystem_health(),
            self.check_database_health(),
            self.check_external_apis_health(),
            self.check_performance_health(),
            return_exceptions=True
        )
        
        # Filter out any exceptions and convert to HealthCheck objects
        valid_checks = []
        for check in checks:
            if isinstance(check, HealthCheck):
                valid_checks.append(check)
            elif isinstance(check, Exception):
                valid_checks.append(HealthCheck(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check exception: {check}",
                    duration_ms=0
                ))
        
        # Determine overall status
        unhealthy_count = len([c for c in valid_checks if c.status == HealthStatus.UNHEALTHY])
        degraded_count = len([c for c in valid_checks if c.status == HealthStatus.DEGRADED])
        
        if unhealthy_count > 0:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY
        
        return OverallHealth(
            status=overall_status,
            checks=valid_checks,
            timestamp=start_time,
            uptime_seconds=time.time() - self.start_time
        )
    
    async def get_readiness_status(self) -> Dict[str, Any]:
        """Get readiness status for Kubernetes readiness probes"""
        # Readiness is simpler - just check critical components
        checks = await asyncio.gather(
            self.check_basic_health(),
            self.check_filesystem_health(),
            self.check_database_health(),
            return_exceptions=True
        )
        
        critical_failures = 0
        for check in checks:
            if isinstance(check, HealthCheck) and check.status == HealthStatus.UNHEALTHY:
                critical_failures += 1
        
        is_ready = critical_failures == 0
        
        return {
            "ready": is_ready,
            "timestamp": time.time(),
            "critical_failures": critical_failures,
            "message": "Service ready" if is_ready else f"{critical_failures} critical failures"
        }
    
    async def get_liveness_status(self) -> Dict[str, Any]:
        """Get liveness status for Kubernetes liveness probes"""
        # Liveness is even simpler - just check if service is responsive
        basic_check = await self.check_basic_health()
        
        is_alive = basic_check.status != HealthStatus.UNHEALTHY
        
        return {
            "alive": is_alive,
            "timestamp": time.time(),
            "uptime_seconds": time.time() - self.start_time,
            "message": basic_check.message
        }


# Global health checker instance
health_checker = HealthChecker()