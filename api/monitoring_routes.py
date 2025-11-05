"""
Monitoring API Routes for Chronarr
Provides health checks, metrics, and system status endpoints
"""
from fastapi import APIRouter, Response, HTTPException
from typing import Dict, Any, Optional
import time

from monitoring.health import health_checker, HealthStatus
from monitoring.metrics import metrics
try:
    from config.validator import get_configuration_summary
except ImportError:
    def get_configuration_summary():
        return {"status": "Configuration validator not available"}


router = APIRouter(prefix="/api/v1", tags=["monitoring"])


@router.get("/health")
async def get_health_status():
    """
    Get comprehensive health status
    
    Returns detailed health information including:
    - Overall system health
    - Individual component health checks
    - Performance metrics
    - Error status
    """
    try:
        health_status = await health_checker.get_full_health_status()
        
        # Set appropriate HTTP status code
        if health_status.status == HealthStatus.HEALTHY:
            status_code = 200
        elif health_status.status == HealthStatus.DEGRADED:
            status_code = 200  # Still operational
        else:  # UNHEALTHY
            status_code = 503  # Service unavailable
        
        return Response(
            content=health_status.to_dict(),
            status_code=status_code,
            media_type="application/json"
        )
        
    except Exception as e:
        # Return unhealthy status if health check itself fails
        return Response(
            content={
                "status": "unhealthy",
                "message": f"Health check failed: {e}",
                "timestamp": time.time()
            },
            status_code=500,
            media_type="application/json"
        )


@router.get("/health/ready")
async def get_readiness_status():
    """
    Kubernetes readiness probe endpoint
    
    Returns 200 if service is ready to accept traffic
    Returns 503 if service is not ready
    """
    try:
        readiness = await health_checker.get_readiness_status()
        
        status_code = 200 if readiness["ready"] else 503
        
        return Response(
            content=readiness,
            status_code=status_code,
            media_type="application/json"
        )
        
    except Exception as e:
        return Response(
            content={
                "ready": False,
                "message": f"Readiness check failed: {e}",
                "timestamp": time.time()
            },
            status_code=503,
            media_type="application/json"
        )


@router.get("/health/live")
async def get_liveness_status():
    """
    Kubernetes liveness probe endpoint
    
    Returns 200 if service is alive and responsive
    Returns 500 if service should be restarted
    """
    try:
        liveness = await health_checker.get_liveness_status()
        
        status_code = 200 if liveness["alive"] else 500
        
        return Response(
            content=liveness,
            status_code=status_code,
            media_type="application/json"
        )
        
    except Exception as e:
        return Response(
            content={
                "alive": False,
                "message": f"Liveness check failed: {e}",
                "timestamp": time.time()
            },
            status_code=500,
            media_type="application/json"
        )


@router.get("/metrics")
async def get_prometheus_metrics():
    """
    Prometheus-compatible metrics endpoint
    
    Returns metrics in Prometheus text format for scraping
    """
    try:
        prometheus_metrics = metrics.get_prometheus_metrics()
        
        return Response(
            content=prometheus_metrics,
            media_type="text/plain; charset=utf-8"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate metrics: {e}"
        )


@router.get("/metrics/json")
async def get_metrics_json():
    """
    Get all metrics in JSON format
    
    Returns structured metrics data including:
    - System metrics (CPU, memory, disk)
    - Processing metrics (rates, durations)
    - Error metrics (counts, recent errors)
    """
    try:
        all_metrics = metrics.get_all_metrics()
        return all_metrics
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get metrics: {e}"
        )


@router.get("/status")
async def get_system_status():
    """
    Get comprehensive system status
    
    Returns detailed system information including:
    - Health status
    - Configuration summary
    - Performance metrics
    - Recent activity
    """
    try:
        # Get health status
        health_status = await health_checker.get_full_health_status()
        
        # Get metrics
        all_metrics = metrics.get_all_metrics()
        
        # Get configuration summary
        config_summary = get_configuration_summary()
        
        # Combine into comprehensive status
        status_response = {
            "overall_status": health_status.status.value,
            "timestamp": time.time(),
            "uptime_seconds": health_status.uptime_seconds,
            "version": health_status.version,
            "health": health_status.to_dict(),
            "metrics": all_metrics,
            "configuration": config_summary,
            "summary": {
                "service_healthy": health_status.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED],
                "total_webhooks_processed": all_metrics["processing"]["total_webhooks"],
                "total_nfo_files_created": all_metrics["processing"]["total_nfo_created"],
                "total_errors": all_metrics["processing"]["total_errors"],
                "current_processing_rate": all_metrics["processing"]["webhooks_received_per_minute"],
                "average_processing_time": all_metrics["processing"]["average_processing_time_seconds"]
            }
        }
        
        return status_response
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get system status: {e}"
        )


@router.get("/status/brief")
async def get_brief_status():
    """
    Get brief system status for quick monitoring
    
    Returns essential status information without detailed metrics
    """
    try:
        # Get basic health
        liveness = await health_checker.get_liveness_status()
        readiness = await health_checker.get_readiness_status()
        
        # Get basic metrics
        processing_metrics = metrics.get_processing_metrics()
        system_metrics = metrics.get_system_metrics()
        
        return {
            "status": "healthy" if liveness["alive"] and readiness["ready"] else "unhealthy",
            "alive": liveness["alive"],
            "ready": readiness["ready"],
            "uptime_seconds": liveness["uptime_seconds"],
            "webhooks_per_minute": processing_metrics["webhooks_received_per_minute"],
            "active_operations": processing_metrics["active_operations"],
            "total_errors": processing_metrics["total_errors"],
            "cpu_percent": system_metrics.get("cpu_percent", 0),
            "memory_percent": system_metrics.get("memory_percent", 0),
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get brief status: {e}"
        )


@router.get("/metrics/processing")
async def get_processing_metrics():
    """
    Get processing-specific metrics
    
    Returns metrics focused on NFO processing performance
    """
    try:
        processing_metrics = metrics.get_processing_metrics()
        return processing_metrics
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get processing metrics: {e}"
        )


@router.get("/metrics/errors")
async def get_error_metrics():
    """
    Get error-specific metrics
    
    Returns error counts, types, and recent error information
    """
    try:
        error_metrics = metrics.get_error_metrics()
        return error_metrics
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get error metrics: {e}"
        )


@router.get("/metrics/system")
async def get_system_metrics():
    """
    Get system resource metrics
    
    Returns CPU, memory, disk, and process information
    """
    try:
        system_metrics = metrics.get_system_metrics()
        return system_metrics
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get system metrics: {e}"
        )


@router.post("/metrics/reset")
async def reset_metrics(metric_types: Optional[str] = None):
    """
    Reset specific metric types
    
    Parameters:
    - metric_types: Comma-separated list of metric types to reset
                   (counters, histograms, errors, timeseries)
                   If not specified, resets all metrics
    """
    try:
        reset_types = None
        if metric_types:
            reset_types = [t.strip() for t in metric_types.split(",")]
        
        metrics.reset_metrics(reset_types)
        
        return {
            "message": "Metrics reset successfully",
            "reset_types": reset_types or "all",
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset metrics: {e}"
        )


# Legacy endpoints for backwards compatibility
@router.get("/health-check")
async def legacy_health_check():
    """Legacy health check endpoint (redirects to /health)"""
    return await get_brief_status()


@router.get("/ping")
async def ping():
    """Simple ping endpoint for basic connectivity testing"""
    return {
        "message": "pong",
        "timestamp": time.time(),
        "service": "chronarr",
        "version": "2.0.0"
    }