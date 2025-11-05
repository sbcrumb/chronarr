"""
Runtime Configuration Validator for Chronarr
Provides validation of configuration at runtime with health checks
"""
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import aiohttp
import sqlite3
import psycopg2

from config.validator import ValidationIssue, ValidationResult, ValidationSeverity
from utils.exceptions import ConfigurationError, NetworkRetryableError, DatabaseError


@dataclass
class HealthCheckResult:
    """Result of a runtime health check"""
    component: str
    is_healthy: bool
    response_time_ms: Optional[float] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "is_healthy": self.is_healthy,
            "response_time_ms": self.response_time_ms,
            "message": self.message,
            "details": self.details,
            "timestamp": time.time()
        }


class RuntimeValidator:
    """Runtime configuration and system health validator"""
    
    def __init__(self, config):
        self.config = config
        self._health_cache = {}
        self._cache_ttl = 60  # Cache health results for 60 seconds
    
    async def validate_runtime_config(self) -> ValidationResult:
        """Perform runtime validation of configuration"""
        result = ValidationResult(is_valid=True)
        
        # Validate filesystem access
        await self._validate_filesystem_access(result)
        
        # Validate database connectivity
        await self._validate_database_connectivity(result)
        
        # Validate external API connectivity
        await self._validate_api_connectivity(result)
        
        # Validate permissions
        await self._validate_permissions(result)
        
        # Validate resource availability
        await self._validate_resources(result)
        
        return result
    
    async def _validate_filesystem_access(self, result: ValidationResult) -> None:
        """Validate filesystem access for media paths"""
        all_paths = []
        
        # Collect all media paths
        all_paths.extend(self.config.tv_paths)
        all_paths.extend(self.config.movie_paths)
        
        for path in all_paths:
            try:
                # Check if path exists and is accessible
                if not path.exists():
                    result.add_issue(ValidationIssue(
                        setting="media_paths",
                        severity=ValidationSeverity.ERROR,
                        message=f"Media path does not exist: {path}",
                        current_value=str(path)
                    ))
                    continue
                
                # Check if path is readable
                test_file = None
                try:
                    # Try to list directory contents
                    list(path.iterdir())
                except PermissionError:
                    result.add_issue(ValidationIssue(
                        setting="media_paths",
                        severity=ValidationSeverity.ERROR,
                        message=f"No read permission for media path: {path}",
                        current_value=str(path)
                    ))
                    continue
                except OSError as e:
                    result.add_issue(ValidationIssue(
                        setting="media_paths",
                        severity=ValidationSeverity.WARNING,
                        message=f"Error accessing media path: {e}",
                        current_value=str(path)
                    ))
                    continue
                
                # Check write permissions (needed for NFO files)
                try:
                    test_file = path / ".chronarr_write_test"
                    test_file.write_text("test")
                    test_file.unlink()
                except PermissionError:
                    result.add_issue(ValidationIssue(
                        setting="media_paths",
                        severity=ValidationSeverity.ERROR,
                        message=f"No write permission for media path: {path}",
                        current_value=str(path),
                        details={"required_for": "NFO file creation"}
                    ))
                except OSError as e:
                    result.add_issue(ValidationIssue(
                        setting="media_paths",
                        severity=ValidationSeverity.WARNING,
                        message=f"Write test failed for media path: {e}",
                        current_value=str(path)
                    ))
                finally:
                    # Cleanup test file if it exists
                    if test_file and test_file.exists():
                        try:
                            test_file.unlink()
                        except:
                            pass
                            
            except Exception as e:
                result.add_issue(ValidationIssue(
                    setting="media_paths",
                    severity=ValidationSeverity.ERROR,
                    message=f"Unexpected error accessing path: {e}",
                    current_value=str(path)
                ))
        
        # Validate database directory
        db_path = Path(self.config.db_path)
        db_dir = db_path.parent
        
        if not db_dir.exists():
            try:
                db_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                result.add_issue(ValidationIssue(
                    setting="DB_PATH",
                    severity=ValidationSeverity.ERROR,
                    message=f"Cannot create database directory: {db_dir}",
                    current_value=str(db_path)
                ))
            except OSError as e:
                result.add_issue(ValidationIssue(
                    setting="DB_PATH",
                    severity=ValidationSeverity.ERROR,
                    message=f"Error creating database directory: {e}",
                    current_value=str(db_path)
                ))
        
        # Test database file access
        if not db_path.exists():
            try:
                # Try to create the database
                with sqlite3.connect(str(db_path)) as conn:
                    conn.execute("SELECT 1")
            except PermissionError:
                result.add_issue(ValidationIssue(
                    setting="DB_PATH",
                    severity=ValidationSeverity.ERROR,
                    message=f"Cannot create database file: {db_path}",
                    current_value=str(db_path)
                ))
            except sqlite3.Error as e:
                result.add_issue(ValidationIssue(
                    setting="DB_PATH",
                    severity=ValidationSeverity.ERROR,
                    message=f"Database error: {e}",
                    current_value=str(db_path)
                ))
    
    async def _validate_database_connectivity(self, result: ValidationResult) -> None:
        """Validate database connectivity"""
        # Test Radarr database if configured
        if hasattr(self.config, 'db_type') or 'RADARR_DB_TYPE' in os.environ:
            import os
            db_type = getattr(self.config, 'db_type', os.environ.get('RADARR_DB_TYPE', '')).lower()
            
            if db_type == 'postgresql':
                await self._test_postgresql_connection(result)
            elif db_type == 'sqlite':
                await self._test_sqlite_connection(result)
        
        # Test local SQLite database
        await self._test_local_database(result)
    
    async def _test_postgresql_connection(self, result: ValidationResult) -> None:
        """Test PostgreSQL connection"""
        import os
        
        try:
            host = os.environ.get('RADARR_DB_HOST')
            port = int(os.environ.get('RADARR_DB_PORT', 5432))
            database = os.environ.get('RADARR_DB_NAME')
            user = os.environ.get('RADARR_DB_USER')
            password = os.environ.get('RADARR_DB_PASSWORD', '')
            
            start_time = time.time()
            
            # Use asyncio to run blocking DB call
            def test_connection():
                conn = psycopg2.connect(
                    host=host, port=port, database=database,
                    user=user, password=password,
                    connect_timeout=10
                )
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                return conn
            
            conn = await asyncio.get_event_loop().run_in_executor(None, test_connection)
            conn.close()
            
            response_time = (time.time() - start_time) * 1000
            
            if response_time > 5000:  # 5 seconds
                result.add_issue(ValidationIssue(
                    setting="RADARR_DB",
                    severity=ValidationSeverity.WARNING,
                    message=f"Slow database connection ({response_time:.0f}ms)",
                    details={"response_time_ms": response_time}
                ))
                
        except psycopg2.OperationalError as e:
            result.add_issue(ValidationIssue(
                setting="RADARR_DB",
                severity=ValidationSeverity.ERROR,
                message=f"Cannot connect to PostgreSQL database: {e}",
                details={"error_type": "connection_failed"}
            ))
        except Exception as e:
            result.add_issue(ValidationIssue(
                setting="RADARR_DB",
                severity=ValidationSeverity.ERROR,
                message=f"Database connection error: {e}",
                details={"error_type": "unexpected_error"}
            ))
    
    async def _test_local_database(self, result: ValidationResult) -> None:
        """Test local SQLite database"""
        try:
            db_path = Path(self.config.db_path)
            
            start_time = time.time()
            
            def test_db():
                with sqlite3.connect(str(db_path), timeout=10) as conn:
                    conn.execute("SELECT 1")
                    return True
            
            await asyncio.get_event_loop().run_in_executor(None, test_db)
            
            response_time = (time.time() - start_time) * 1000
            
            if response_time > 1000:  # 1 second is slow for SQLite
                result.add_issue(ValidationIssue(
                    setting="DB_PATH",
                    severity=ValidationSeverity.WARNING,
                    message=f"Slow local database access ({response_time:.0f}ms)",
                    current_value=str(db_path),
                    details={"response_time_ms": response_time}
                ))
                
        except sqlite3.OperationalError as e:
            result.add_issue(ValidationIssue(
                setting="DB_PATH",
                severity=ValidationSeverity.ERROR,
                message=f"Local database error: {e}",
                current_value=str(self.config.db_path)
            ))
    
    async def _validate_api_connectivity(self, result: ValidationResult) -> None:
        """Validate external API connectivity"""
        apis = []
        
        if hasattr(self.config, 'radarr_url') and self.config.radarr_url:
            apis.append(("Radarr", self.config.radarr_url))
        
        if hasattr(self.config, 'sonarr_url') and self.config.sonarr_url:
            apis.append(("Sonarr", self.config.sonarr_url))
        
        for api_name, base_url in apis:
            await self._test_api_connectivity(result, api_name, base_url)
    
    async def _test_api_connectivity(self, result: ValidationResult, api_name: str, base_url: str) -> None:
        """Test connectivity to a specific API"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                
                # Test basic connectivity
                test_url = f"{base_url.rstrip('/')}/api/v1/health"
                
                async with session.get(test_url) as response:
                    response_time = (time.time() - start_time) * 1000
                    
                    if response.status == 200:
                        if response_time > 5000:  # 5 seconds
                            result.add_issue(ValidationIssue(
                                setting=f"{api_name.upper()}_URL",
                                severity=ValidationSeverity.WARNING,
                                message=f"Slow {api_name} API response ({response_time:.0f}ms)",
                                current_value=base_url,
                                details={"response_time_ms": response_time}
                            ))
                    else:
                        result.add_issue(ValidationIssue(
                            setting=f"{api_name.upper()}_URL",
                            severity=ValidationSeverity.WARNING,
                            message=f"{api_name} API returned HTTP {response.status}",
                            current_value=base_url,
                            details={"status_code": response.status}
                        ))
                        
        except asyncio.TimeoutError:
            result.add_issue(ValidationIssue(
                setting=f"{api_name.upper()}_URL",
                severity=ValidationSeverity.WARNING,
                message=f"{api_name} API connection timeout",
                current_value=base_url,
                details={"error_type": "timeout"}
            ))
        except Exception as e:
            result.add_issue(ValidationIssue(
                setting=f"{api_name.upper()}_URL",
                severity=ValidationSeverity.WARNING,
                message=f"{api_name} API connection error: {e}",
                current_value=base_url,
                details={"error_type": "connection_error"}
            ))
    
    async def _validate_permissions(self, result: ValidationResult) -> None:
        """Validate file system permissions"""
        # This is partially covered in filesystem validation
        # Additional permission checks can be added here
        pass
    
    async def _validate_resources(self, result: ValidationResult) -> None:
        """Validate system resources"""
        import shutil
        
        try:
            # Check disk space for database directory
            db_path = Path(self.config.db_path)
            db_dir = db_path.parent if not db_path.is_dir() else db_path
            
            if db_dir.exists():
                free_space = shutil.disk_usage(str(db_dir)).free
                free_space_mb = free_space / (1024 * 1024)
                
                if free_space_mb < 100:  # Less than 100MB
                    result.add_issue(ValidationIssue(
                        setting="DB_PATH",
                        severity=ValidationSeverity.ERROR,
                        message=f"Low disk space in database directory ({free_space_mb:.1f}MB free)",
                        current_value=str(db_path),
                        details={"free_space_mb": free_space_mb}
                    ))
                elif free_space_mb < 1000:  # Less than 1GB
                    result.add_issue(ValidationIssue(
                        setting="DB_PATH",
                        severity=ValidationSeverity.WARNING,
                        message=f"Low disk space in database directory ({free_space_mb:.1f}MB free)",
                        current_value=str(db_path),
                        details={"free_space_mb": free_space_mb}
                    ))
                    
        except Exception as e:
            result.add_issue(ValidationIssue(
                setting="system_resources",
                severity=ValidationSeverity.WARNING,
                message=f"Could not check disk space: {e}",
                details={"error_type": "resource_check_failed"}
            ))
    
    async def get_system_health(self) -> Dict[str, HealthCheckResult]:
        """Get comprehensive system health status"""
        health_checks = {}
        
        # Database health
        health_checks["database"] = await self._check_database_health()
        
        # Filesystem health
        health_checks["filesystem"] = await self._check_filesystem_health()
        
        # API health
        health_checks["external_apis"] = await self._check_api_health()
        
        return health_checks
    
    async def _check_database_health(self) -> HealthCheckResult:
        """Check database health"""
        try:
            start_time = time.time()
            
            def test_db():
                with sqlite3.connect(str(self.config.db_path), timeout=5) as conn:
                    conn.execute("SELECT COUNT(*) FROM sqlite_master")
                    return True
            
            await asyncio.get_event_loop().run_in_executor(None, test_db)
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                component="database",
                is_healthy=True,
                response_time_ms=response_time,
                message="Database accessible",
                details={"db_path": str(self.config.db_path)}
            )
            
        except Exception as e:
            return HealthCheckResult(
                component="database",
                is_healthy=False,
                message=f"Database error: {e}",
                details={"db_path": str(self.config.db_path), "error": str(e)}
            )
    
    async def _check_filesystem_health(self) -> HealthCheckResult:
        """Check filesystem health"""
        try:
            accessible_paths = 0
            total_paths = len(self.config.tv_paths) + len(self.config.movie_paths)
            
            for path in list(self.config.tv_paths) + list(self.config.movie_paths):
                if path.exists() and path.is_dir():
                    try:
                        # Quick access test
                        next(path.iterdir(), None)
                        accessible_paths += 1
                    except:
                        pass
            
            is_healthy = accessible_paths == total_paths
            health_percentage = (accessible_paths / total_paths * 100) if total_paths > 0 else 0
            
            return HealthCheckResult(
                component="filesystem",
                is_healthy=is_healthy,
                message=f"{accessible_paths}/{total_paths} media paths accessible ({health_percentage:.1f}%)",
                details={
                    "accessible_paths": accessible_paths,
                    "total_paths": total_paths,
                    "health_percentage": health_percentage
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                component="filesystem",
                is_healthy=False,
                message=f"Filesystem check error: {e}",
                details={"error": str(e)}
            )
    
    async def _check_api_health(self) -> HealthCheckResult:
        """Check external API health"""
        apis_tested = 0
        apis_healthy = 0
        api_details = {}
        
        try:
            # Test configured APIs
            if hasattr(self.config, 'radarr_url') and self.config.radarr_url:
                apis_tested += 1
                healthy = await self._test_single_api("Radarr", self.config.radarr_url)
                if healthy:
                    apis_healthy += 1
                api_details["radarr"] = {"healthy": healthy}
            
            if hasattr(self.config, 'sonarr_url') and self.config.sonarr_url:
                apis_tested += 1
                healthy = await self._test_single_api("Sonarr", self.config.sonarr_url)
                if healthy:
                    apis_healthy += 1
                api_details["sonarr"] = {"healthy": healthy}
            
            if apis_tested == 0:
                return HealthCheckResult(
                    component="external_apis",
                    is_healthy=True,
                    message="No external APIs configured",
                    details={"apis_configured": 0}
                )
            
            is_healthy = apis_healthy == apis_tested
            health_percentage = (apis_healthy / apis_tested * 100) if apis_tested > 0 else 0
            
            return HealthCheckResult(
                component="external_apis",
                is_healthy=is_healthy,
                message=f"{apis_healthy}/{apis_tested} APIs healthy ({health_percentage:.1f}%)",
                details={
                    "healthy_apis": apis_healthy,
                    "total_apis": apis_tested,
                    "health_percentage": health_percentage,
                    "api_status": api_details
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                component="external_apis",
                is_healthy=False,
                message=f"API health check error: {e}",
                details={"error": str(e)}
            )
    
    async def _test_single_api(self, api_name: str, base_url: str) -> bool:
        """Test a single API for health"""
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                test_url = f"{base_url.rstrip('/')}/api/v1/health"
                
                async with session.get(test_url) as response:
                    return response.status == 200
                    
        except:
            return False


# Import needed for database validation
import os