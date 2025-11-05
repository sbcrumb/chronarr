#!/usr/bin/env python3
"""
Configuration Validation CLI for Chronarr
Provides command-line validation and reporting of configuration issues
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from config.validator import validate_configuration, ValidationSeverity
from config.runtime_validator import RuntimeValidator
from config.settings import ChronarrConfig


class ValidationReporter:
    """Formats and displays validation results"""
    
    def __init__(self, verbose: bool = False, json_output: bool = False):
        self.verbose = verbose
        self.json_output = json_output
        
        # Color codes for terminal output
        self.colors = {
            'error': '\033[91m',    # Red
            'warning': '\033[93m',  # Yellow
            'info': '\033[94m',     # Blue
            'success': '\033[92m',  # Green
            'reset': '\033[0m',     # Reset
            'bold': '\033[1m'       # Bold
        }
    
    def report_validation_results(self, result, runtime_result=None) -> int:
        """
        Report validation results
        
        Returns:
            Exit code (0 for success, 1 for warnings, 2 for errors)
        """
        if self.json_output:
            return self._report_json(result, runtime_result)
        else:
            return self._report_human_readable(result, runtime_result)
    
    def _report_json(self, result, runtime_result=None) -> int:
        """Report results in JSON format"""
        output = {
            "timestamp": datetime.now().isoformat(),
            "validation": result.to_dict()
        }
        
        if runtime_result:
            output["runtime_validation"] = runtime_result.to_dict()
        
        print(json.dumps(output, indent=2))
        
        if result.errors_count > 0:
            return 2
        elif result.warnings_count > 0:
            return 1
        return 0
    
    def _report_human_readable(self, result, runtime_result=None) -> int:
        """Report results in human-readable format"""
        print(f"{self.colors['bold']}Chronarr Configuration Validation Report{self.colors['reset']}")
        print("=" * 50)
        
        # Overall status
        if result.is_valid:
            status_color = self.colors['success']
            status_text = "✓ VALID"
        else:
            status_color = self.colors['error']
            status_text = "✗ INVALID"
        
        print(f"Status: {status_color}{status_text}{self.colors['reset']}")
        print(f"Errors: {result.errors_count}")
        print(f"Warnings: {result.warnings_count}")
        print(f"Total Issues: {len(result.issues)}")
        print()
        
        # Report issues by severity
        if result.issues:
            self._report_issues_by_severity(result.issues)
        
        # Report runtime validation if available
        if runtime_result:
            print(f"\n{self.colors['bold']}Runtime Validation{self.colors['reset']}")
            print("-" * 20)
            if runtime_result.issues:
                self._report_issues_by_severity(runtime_result.issues, "Runtime")
            else:
                print(f"{self.colors['success']}✓ All runtime checks passed{self.colors['reset']}")
        
        # Summary and recommendations
        self._report_summary_and_recommendations(result)
        
        # Return appropriate exit code
        if result.errors_count > 0 or (runtime_result and runtime_result.errors_count > 0):
            return 2
        elif result.warnings_count > 0 or (runtime_result and runtime_result.warnings_count > 0):
            return 1
        return 0
    
    def _report_issues_by_severity(self, issues: List, context: str = "Configuration") -> None:
        """Report issues grouped by severity"""
        errors = [issue for issue in issues if issue.severity == ValidationSeverity.ERROR]
        warnings = [issue for issue in issues if issue.severity == ValidationSeverity.WARNING]
        info_issues = [issue for issue in issues if issue.severity == ValidationSeverity.INFO]
        
        if errors:
            print(f"{self.colors['error']}{self.colors['bold']}ERRORS ({len(errors)}):{self.colors['reset']}")
            for issue in errors:
                self._format_issue(issue)
            print()
        
        if warnings:
            print(f"{self.colors['warning']}{self.colors['bold']}WARNINGS ({len(warnings)}):{self.colors['reset']}")
            for issue in warnings:
                self._format_issue(issue)
            print()
        
        if info_issues and self.verbose:
            print(f"{self.colors['info']}{self.colors['bold']}INFO ({len(info_issues)}):{self.colors['reset']}")
            for issue in info_issues:
                self._format_issue(issue)
            print()
    
    def _format_issue(self, issue) -> None:
        """Format a single validation issue"""
        severity_colors = {
            ValidationSeverity.ERROR: self.colors['error'],
            ValidationSeverity.WARNING: self.colors['warning'],
            ValidationSeverity.INFO: self.colors['info']
        }
        
        color = severity_colors.get(issue.severity, '')
        
        print(f"  {color}• {issue.setting}:{self.colors['reset']} {issue.message}")
        
        if issue.current_value is not None:
            print(f"    Current: {issue.current_value}")
        
        if issue.suggested_value is not None:
            print(f"    Suggested: {issue.suggested_value}")
        
        if self.verbose and issue.details:
            print(f"    Details: {issue.details}")
    
    def _report_summary_and_recommendations(self, result) -> None:
        """Report summary and general recommendations"""
        print(f"\n{self.colors['bold']}Summary{self.colors['reset']}")
        print("-" * 10)
        
        if result.is_valid:
            print(f"{self.colors['success']}✓ Your configuration is valid and ready to use!{self.colors['reset']}")
        else:
            print(f"{self.colors['error']}✗ Your configuration has issues that need to be resolved.{self.colors['reset']}")
        
        # Provide specific recommendations based on issue types
        recommendations = self._generate_recommendations(result)
        if recommendations:
            print(f"\n{self.colors['bold']}Recommendations{self.colors['reset']}")
            print("-" * 15)
            for rec in recommendations:
                print(f"  {self.colors['info']}• {rec}{self.colors['reset']}")
    
    def _generate_recommendations(self, result) -> List[str]:
        """Generate recommendations based on validation results"""
        recommendations = []
        
        # Check for common patterns
        path_issues = [issue for issue in result.issues if 'path' in issue.setting.lower()]
        if path_issues:
            recommendations.append("Verify all file paths are correct for your environment")
            recommendations.append("Ensure paths are absolute when using Docker")
        
        db_issues = [issue for issue in result.issues if 'db' in issue.setting.lower()]
        if db_issues:
            recommendations.append("Check database connection settings and credentials")
        
        url_issues = [issue for issue in result.issues if 'url' in issue.setting.lower()]
        if url_issues:
            recommendations.append("Verify API URLs are reachable and include the correct port")
        
        perf_issues = [issue for issue in result.issues if any(perf in issue.setting.lower() 
                      for perf in ['concurrent', 'delay', 'timeout'])]
        if perf_issues:
            recommendations.append("Consider adjusting performance settings based on your system resources")
        
        # General recommendations
        if result.errors_count > 0:
            recommendations.append("Fix all ERROR-level issues before starting Chronarr")
        
        if result.warnings_count > 0:
            recommendations.append("Review WARNING-level issues to optimize performance and reliability")
        
        return recommendations


async def run_validation(args) -> int:
    """Run configuration validation"""
    reporter = ValidationReporter(verbose=args.verbose, json_output=args.json)
    
    try:
        # Run static validation
        print("Running configuration validation..." if not args.json else "", file=sys.stderr)
        result = validate_configuration()
        
        runtime_result = None
        
        # Run runtime validation if requested
        if args.runtime:
            print("Running runtime validation..." if not args.json else "", file=sys.stderr)
            try:
                config = ChronarrConfig()
                runtime_validator = RuntimeValidator(config)
                runtime_result = await runtime_validator.validate_runtime_config()
            except Exception as e:
                if not args.json:
                    print(f"Runtime validation failed: {e}", file=sys.stderr)
                # Continue with static validation results
        
        # Report results
        return reporter.report_validation_results(result, runtime_result)
        
    except Exception as e:
        if args.json:
            error_output = {
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "message": str(e),
                    "type": type(e).__name__
                }
            }
            print(json.dumps(error_output, indent=2))
        else:
            print(f"Validation failed: {e}", file=sys.stderr)
        return 2


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Validate Chronarr configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Basic validation
  %(prog)s --runtime          # Include runtime checks
  %(prog)s --verbose          # Show detailed information
  %(prog)s --json             # Output JSON format
  %(prog)s --runtime --json   # Runtime validation with JSON output
        """
    )
    
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Perform runtime validation (tests actual connectivity and permissions)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output including info-level messages"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    
    args = parser.parse_args()
    
    # Run validation
    import asyncio
    try:
        exit_code = asyncio.run(run_validation(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("Validation interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()