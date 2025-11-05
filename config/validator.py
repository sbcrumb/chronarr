"""
Configuration Validator for Chronarr
Provides comprehensive validation of all configuration settings with detailed error reporting
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Type, Callable
from dataclasses import dataclass, field
from enum import Enum

from utils.exceptions import ConfigurationError
from utils.validation import validate_url_format


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    ERROR = "error"      # Configuration is invalid, will cause failures
    WARNING = "warning"  # Configuration may cause issues but is workable
    INFO = "info"        # Configuration could be improved


@dataclass
class ValidationIssue:
    """Represents a configuration validation issue"""
    setting: str
    severity: ValidationSeverity
    message: str
    current_value: Any = None
    suggested_value: Any = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for structured logging"""
        return {
            "setting": self.setting,
            "severity": self.severity.value,
            "message": self.message,
            "current_value": str(self.current_value) if self.current_value is not None else None,
            "suggested_value": str(self.suggested_value) if self.suggested_value is not None else None,
            "details": self.details
        }


@dataclass
class ValidationResult:
    """Results of configuration validation"""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings_count: int = 0
    errors_count: int = 0
    
    def add_issue(self, issue: ValidationIssue) -> None:
        """Add a validation issue"""
        self.issues.append(issue)
        if issue.severity == ValidationSeverity.ERROR:
            self.errors_count += 1
            self.is_valid = False
        elif issue.severity == ValidationSeverity.WARNING:
            self.warnings_count += 1
    
    def get_errors(self) -> List[ValidationIssue]:
        """Get only error-level issues"""
        return [issue for issue in self.issues if issue.severity == ValidationSeverity.ERROR]
    
    def get_warnings(self) -> List[ValidationIssue]:
        """Get only warning-level issues"""
        return [issue for issue in self.issues if issue.severity == ValidationSeverity.WARNING]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for structured logging"""
        return {
            "is_valid": self.is_valid,
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "issues": [issue.to_dict() for issue in self.issues]
        }


class ConfigValidator:
    """Comprehensive configuration validator for Chronarr"""
    
    def __init__(self):
        self.result = ValidationResult(is_valid=True)
        
        # Define validation rules
        self._path_settings = {
            "TV_PATHS", "MOVIE_PATHS", "RADARR_ROOT_FOLDERS", 
            "SONARR_ROOT_FOLDERS", "DB_PATH", "LOG_DIR"
        }
        
        self._url_settings = {
            "RADARR_URL", "SONARR_URL", "JELLYSEERR_URL"
        }
        
        self._required_settings = {
            "TV_PATHS", "MOVIE_PATHS"
        }
        
        self._numeric_settings = {
            "BATCH_DELAY": (float, 0.1, 300.0),
            "MAX_CONCURRENT_SERIES": (int, 1, 10),
            "TIMEOUT_SECONDS": (int, 10, 300),
            "PORT": (int, 1024, 65535),
            "RADARR_DB_PORT": (int, 1, 65535),
            "MAX_RELEASE_DATE_GAP_YEARS": (int, 1, 50)
        }
        
        self._boolean_settings = {
            "MANAGE_NFO", "FIX_DIR_MTIMES", "LOCK_METADATA", "DEBUG",
            "PREFER_RELEASE_DATES_OVER_FILE_DATES", "ALLOW_FILE_DATE_FALLBACK",
            "ENABLE_SMART_DATE_VALIDATION", "PATH_DEBUG", "SUPPRESS_TVDB_WARNINGS"
        }
        
        self._choice_settings = {
            "MOVIE_PRIORITY": ["import_then_digital", "digital_first", "file_date_only"],
            "MOVIE_POLL_MODE": ["always", "missing_only", "never"],
            "MOVIE_DATE_UPDATE_MODE": ["overwrite", "backfill_only", "preserve_existing"],
            "TV_WEBHOOK_PROCESSING_MODE": ["targeted", "full_scan", "hybrid"],
            "UPDATE_MODE": ["always", "missing_only", "never"],
            "MTIME_BEHAVIOR": ["update", "leave_alone"],
            "RADARR_DB_TYPE": ["postgresql", "sqlite"]
        }
    
    def validate_all(self) -> ValidationResult:
        """Validate all configuration settings"""
        self.result = ValidationResult(is_valid=True)
        
        # Validate required settings
        self._validate_required_settings()
        
        # Validate paths
        self._validate_paths()
        
        # Validate URLs
        self._validate_urls()
        
        # Validate numeric settings
        self._validate_numeric_settings()
        
        # Validate boolean settings
        self._validate_boolean_settings()
        
        # Validate choice settings
        self._validate_choice_settings()
        
        # Validate database configuration
        self._validate_database_config()
        
        # Validate release date configuration
        self._validate_release_date_config()
        
        # Validate performance settings
        self._validate_performance_settings()
        
        # Validate cross-setting dependencies
        self._validate_dependencies()
        
        return self.result
    
    def _validate_required_settings(self) -> None:
        """Validate required environment variables are set"""
        for setting in self._required_settings:
            value = os.environ.get(setting)
            if not value:
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.ERROR,
                    message=f"Required setting {setting} is not set",
                    current_value=value
                ))
            elif not value.strip():
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.ERROR,
                    message=f"Required setting {setting} is empty",
                    current_value=value
                ))
    
    def _validate_paths(self) -> None:
        """Validate all path-related settings"""
        for setting in self._path_settings:
            value = os.environ.get(setting)
            if not value:
                if setting in self._required_settings:
                    continue  # Already handled in required validation
                else:
                    # Optional path settings
                    continue
            
            if setting in {"TV_PATHS", "MOVIE_PATHS", "RADARR_ROOT_FOLDERS", "SONARR_ROOT_FOLDERS"}:
                # Multi-path settings
                paths = [p.strip() for p in value.split(",") if p.strip()]
                if not paths:
                    self.result.add_issue(ValidationIssue(
                        setting=setting,
                        severity=ValidationSeverity.ERROR,
                        message=f"No valid paths found in {setting}",
                        current_value=value
                    ))
                    continue
                
                for path_str in paths:
                    self._validate_single_path(setting, path_str)
            else:
                # Single path settings
                self._validate_single_path(setting, value)
    
    def _validate_single_path(self, setting: str, path_str: str) -> None:
        """Validate a single path"""
        try:
            path = Path(path_str)
            
            # Check if path is absolute (recommended for Docker)
            if not path.is_absolute():
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.WARNING,
                    message=f"Path should be absolute for reliable Docker operation",
                    current_value=path_str,
                    suggested_value=f"Use absolute path like /media/..."
                ))
            
            # For media paths, check existence if not in container
            if setting in {"TV_PATHS", "MOVIE_PATHS"} and not self._is_likely_container_path(path_str):
                if not path.exists():
                    self.result.add_issue(ValidationIssue(
                        setting=setting,
                        severity=ValidationSeverity.WARNING,
                        message=f"Path does not exist (may be valid in container)",
                        current_value=path_str,
                        details={"path_type": "media"}
                    ))
                elif not path.is_dir():
                    self.result.add_issue(ValidationIssue(
                        setting=setting,
                        severity=ValidationSeverity.ERROR,
                        message=f"Path exists but is not a directory",
                        current_value=path_str
                    ))
            
            # Check for database directory
            if setting == "DB_PATH":
                parent_dir = path.parent
                if not self._is_likely_container_path(str(parent_dir)) and not parent_dir.exists():
                    self.result.add_issue(ValidationIssue(
                        setting=setting,
                        severity=ValidationSeverity.WARNING,
                        message=f"Database directory does not exist: {parent_dir}",
                        current_value=path_str
                    ))
                    
        except (OSError, ValueError) as e:
            self.result.add_issue(ValidationIssue(
                setting=setting,
                severity=ValidationSeverity.ERROR,
                message=f"Invalid path format: {e}",
                current_value=path_str
            ))
    
    def _is_likely_container_path(self, path: str) -> bool:
        """Check if path looks like a container path"""
        container_indicators = ["/app/", "/media/", "/config/", "/data/"]
        return any(indicator in path for indicator in container_indicators)
    
    def _validate_urls(self) -> None:
        """Validate URL settings"""
        for setting in self._url_settings:
            value = os.environ.get(setting)
            if value and not validate_url_format(value):
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid URL format",
                    current_value=value,
                    suggested_value="Use format: http://hostname:port or https://hostname:port"
                ))
    
    def _validate_numeric_settings(self) -> None:
        """Validate numeric settings"""
        for setting, (type_class, min_val, max_val) in self._numeric_settings.items():
            value = os.environ.get(setting)
            if not value:
                continue
                
            try:
                numeric_value = type_class(value)
                if numeric_value < min_val or numeric_value > max_val:
                    self.result.add_issue(ValidationIssue(
                        setting=setting,
                        severity=ValidationSeverity.ERROR,
                        message=f"Value must be between {min_val} and {max_val}",
                        current_value=value,
                        suggested_value=f"Use value between {min_val}-{max_val}"
                    ))
            except (ValueError, TypeError):
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid {type_class.__name__} value",
                    current_value=value,
                    suggested_value=f"Use a valid {type_class.__name__} between {min_val}-{max_val}"
                ))
    
    def _validate_boolean_settings(self) -> None:
        """Validate boolean settings"""
        valid_true = {"1", "true", "yes", "y", "on"}
        valid_false = {"0", "false", "no", "n", "off"}
        valid_values = valid_true | valid_false
        
        for setting in self._boolean_settings:
            value = os.environ.get(setting)
            if value and value.lower() not in valid_values:
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid boolean value",
                    current_value=value,
                    suggested_value="Use: true/false, 1/0, yes/no, y/n, on/off"
                ))
    
    def _validate_choice_settings(self) -> None:
        """Validate settings with predefined choices"""
        for setting, valid_choices in self._choice_settings.items():
            value = os.environ.get(setting)
            if value and value.lower() not in [choice.lower() for choice in valid_choices]:
                self.result.add_issue(ValidationIssue(
                    setting=setting,
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid choice",
                    current_value=value,
                    suggested_value=f"Use one of: {', '.join(valid_choices)}"
                ))
    
    def _validate_database_config(self) -> None:
        """Validate database configuration"""
        db_type = os.environ.get("RADARR_DB_TYPE", "").lower()
        
        if db_type == "postgresql":
            # Check required PostgreSQL settings
            required_pg_settings = ["RADARR_DB_HOST", "RADARR_DB_NAME", "RADARR_DB_USER"]
            for setting in required_pg_settings:
                if not os.environ.get(setting):
                    self.result.add_issue(ValidationIssue(
                        setting=setting,
                        severity=ValidationSeverity.ERROR,
                        message=f"Required for PostgreSQL database connection",
                        current_value=os.environ.get(setting)
                    ))
    
    def _validate_release_date_config(self) -> None:
        """Validate release date processing configuration"""
        priority = os.environ.get("RELEASE_DATE_PRIORITY", "")
        if priority:
            priorities = [p.strip().lower() for p in priority.split(",")]
            valid_priorities = {"digital", "physical", "theatrical"}
            
            invalid_priorities = [p for p in priorities if p not in valid_priorities]
            if invalid_priorities:
                self.result.add_issue(ValidationIssue(
                    setting="RELEASE_DATE_PRIORITY",
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid release date priorities: {', '.join(invalid_priorities)}",
                    current_value=priority,
                    suggested_value="Use: digital, physical, theatrical"
                ))
            
            if len(set(priorities)) != len(priorities):
                self.result.add_issue(ValidationIssue(
                    setting="RELEASE_DATE_PRIORITY",
                    severity=ValidationSeverity.WARNING,
                    message="Duplicate priorities found",
                    current_value=priority
                ))
    
    def _validate_performance_settings(self) -> None:
        """Validate performance-related settings"""
        batch_delay = os.environ.get("BATCH_DELAY")
        max_concurrent = os.environ.get("MAX_CONCURRENT_SERIES")
        
        # Performance recommendations
        if batch_delay:
            try:
                delay = float(batch_delay)
                if delay < 1.0:
                    self.result.add_issue(ValidationIssue(
                        setting="BATCH_DELAY",
                        severity=ValidationSeverity.WARNING,
                        message="Very low batch delay may increase system load",
                        current_value=batch_delay,
                        suggested_value="Consider using 1.0 or higher for better stability"
                    ))
            except ValueError:
                pass  # Already caught in numeric validation
        
        if max_concurrent:
            try:
                concurrent = int(max_concurrent)
                if concurrent > 5:
                    self.result.add_issue(ValidationIssue(
                        setting="MAX_CONCURRENT_SERIES",
                        severity=ValidationSeverity.WARNING,
                        message="High concurrency may overload system resources",
                        current_value=max_concurrent,
                        suggested_value="Consider using 3-5 for optimal balance"
                    ))
            except ValueError:
                pass  # Already caught in numeric validation
    
    def _validate_dependencies(self) -> None:
        """Validate cross-setting dependencies"""
        # If database is configured, recommend using database over API
        db_type = os.environ.get("RADARR_DB_TYPE")
        radarr_url = os.environ.get("RADARR_URL")
        
        if db_type and radarr_url:
            self.result.add_issue(ValidationIssue(
                setting="RADARR_DB_TYPE",
                severity=ValidationSeverity.INFO,
                message="Database connection preferred over API for better performance",
                details={"recommendation": "Database access is faster and more reliable"}
            ))
        
        # Check path mapping consistency
        tv_paths = os.environ.get("TV_PATHS", "").split(",")
        sonarr_paths = os.environ.get("SONARR_ROOT_FOLDERS", "").split(",")
        
        if len([p for p in tv_paths if p.strip()]) != len([p for p in sonarr_paths if p.strip()]):
            self.result.add_issue(ValidationIssue(
                setting="TV_PATHS",
                severity=ValidationSeverity.WARNING,
                message="TV_PATHS and SONARR_ROOT_FOLDERS should have matching number of paths",
                details={
                    "tv_paths_count": len([p for p in tv_paths if p.strip()]),
                    "sonarr_paths_count": len([p for p in sonarr_paths if p.strip()])
                }
            ))


def validate_configuration() -> ValidationResult:
    """
    Validate the complete Chronarr configuration
    
    Returns:
        ValidationResult with all validation issues found
    """
    validator = ConfigValidator()
    return validator.validate_all()


def validate_configuration_and_raise() -> None:
    """
    Validate configuration and raise ConfigurationError if invalid
    
    Raises:
        ConfigurationError: If configuration validation fails
    """
    result = validate_configuration()
    
    if not result.is_valid:
        error_messages = []
        for error in result.get_errors():
            error_messages.append(f"{error.setting}: {error.message}")
        
        raise ConfigurationError(
            setting="configuration",
            reason=f"Configuration validation failed with {result.errors_count} errors",
            current_value={
                "errors": error_messages,
                "warnings_count": result.warnings_count,
                "validation_details": result.to_dict()
            }
        )


def get_configuration_summary() -> Dict[str, Any]:
    """
    Get a summary of current configuration status
    
    Returns:
        Dictionary with configuration summary
    """
    result = validate_configuration()
    
    return {
        "is_valid": result.is_valid,
        "errors_count": result.errors_count,
        "warnings_count": result.warnings_count,
        "total_issues": len(result.issues),
        "critical_issues": [
            issue.to_dict() for issue in result.issues 
            if issue.severity == ValidationSeverity.ERROR
        ],
        "recommendations": [
            issue.to_dict() for issue in result.issues 
            if issue.severity == ValidationSeverity.WARNING
        ]
    }