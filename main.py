#!/usr/bin/env python3
"""Chronarr core — webhook processor, scanner, and scheduling engine."""
import os
import sys
import signal
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

# Import configuration first
from config.settings import config

# Authentication removed - handled by separate web container
from utils.logging import _log

# Import core components
from core.database import ChronarrDatabase
from core.instance_registry import build_registry
from core.path_mapper import PathMapper

# Import processors
from processors.tv_processor import TVProcessor
from processors.movie_processor import MovieProcessor

# Import webhook handling
from webhooks.webhook_batcher import WebhookBatcher

# Import API routes
from api.routes import register_routes

# Version — single source of truth
from version_utils import get_version

# Global shutdown event for graceful shutdown coordination
shutdown_event = asyncio.Event()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    from contextlib import asynccontextmanager

    version = get_version()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifespan - startup and shutdown events"""
        # Startup
        try:
            from scheduler.cleanup_scheduler import get_cleanup_scheduler

            # Get dependencies from the global variable (set in main())
            if hasattr(signal_handler, 'dependencies'):
                cleanup_scheduler = await get_cleanup_scheduler(signal_handler.dependencies)
                _log("INFO", "Cleanup scheduler started successfully")
        except Exception as e:
            _log("ERROR", f"Failed to start cleanup scheduler: {e}")

        yield

        # Shutdown
        try:
            from scheduler.cleanup_scheduler import shutdown_cleanup_scheduler
            await shutdown_cleanup_scheduler()
            _log("INFO", "Cleanup scheduler stopped successfully")
        except Exception as e:
            _log("ERROR", f"Error stopping cleanup scheduler: {e}")

    app = FastAPI(
        title="Chronarr",
        description="Webhook server for preserving media import dates",
        version=version,
        lifespan=lifespan
    )

    return app


def _noop_mapper() -> PathMapper:
    """Return an empty PathMapper — used when a default instance isn't configured."""
    return PathMapper(root_folders=[], container_paths=[])


def initialize_components(registry=None):
    start_time = datetime.now(timezone.utc)

    db = ChronarrDatabase(config=config)

    # Use the registry built at startup if passed in; otherwise build it now.
    if registry is None:
        registry = build_registry(config)

    # Processors get the default instance's client and mapper. Multi-instance
    # requests pass instance name explicitly at process time; the processors look
    # up the right client from the registry during their DB writes.
    default_radarr_mapper = registry.radarr_mapper("radarr")
    default_sonarr_mapper = registry.sonarr_mapper("sonarr")

    tv_processor = TVProcessor(
        db, None,
        default_sonarr_mapper or _noop_mapper(),
        sonarr_client=registry.sonarr("sonarr"),
    )
    movie_processor = MovieProcessor(
        db, None,
        default_radarr_mapper or _noop_mapper(),
        radarr_client=registry.radarr("radarr"),
    )

    batcher = WebhookBatcher(nfo_manager=None)
    batcher.set_processors(tv_processor, movie_processor)

    return {
        "db": db,
        "registry": registry,
        "tv_processor": tv_processor,
        "movie_processor": movie_processor,
        "batcher": batcher,
        "start_time": start_time,
        "config": config,
        "version": get_version(),
        "shutdown_event": shutdown_event,
    }


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    _log("INFO", f"Received signal {signum}, shutting down gracefully...")
    
    # Set shutdown event to notify background tasks
    shutdown_event.set()
    
    # Get the global dependencies if they exist
    if hasattr(signal_handler, 'dependencies') and signal_handler.dependencies:
        deps = signal_handler.dependencies
        
        # Shutdown webhook batcher cleanly
        if 'batcher' in deps:
            try:
                _log("INFO", "Shutting down webhook batcher...")
                deps['batcher'].shutdown()
            except Exception as e:
                _log("WARNING", f"Error during batcher shutdown: {e}")
        
        # Close database connection
        if 'db' in deps:
            try:
                _log("INFO", "Closing database connection...")
                deps['db'].close()
            except Exception as e:
                _log("WARNING", f"Error closing database: {e}")
    
    _log("INFO", "Graceful shutdown complete")
    
    # Force exit after 2 seconds if graceful shutdown doesn't work
    import threading
    def force_exit():
        import time
        time.sleep(2)
        _log("WARNING", "Force exiting after timeout")
        os._exit(0)
    
    force_thread = threading.Thread(target=force_exit, daemon=True)
    force_thread.start()
    
    sys.exit(0)


def test_database_connections(registry=None):
    """Report all database connection statuses at startup."""
    import psycopg2
    import sqlite3

    print("\n" + "="*70)
    print("  DATABASE CONNECTION STATUS")
    print("="*70)

    # Chronarr's own DB — always present
    print(f"\n  Chronarr Database:")
    if config.db_type == "postgresql":
        print(f"  Type: PostgreSQL  Host: {config.db_host}:{config.db_port}  Database: {config.db_name}")
        try:
            conn = psycopg2.connect(
                host=config.db_host, port=config.db_port,
                database=config.db_name, user=config.db_user, password=config.db_password
            )
            conn.cursor().execute("SELECT 1")
            conn.close()
            print(f"  Status: ✅ CONNECTED")
        except Exception as e:
            print(f"  Status: ❌ ERROR - {str(e)[:60]}")
    else:
        print(f"  Type: SQLite  Path: {config.db_path}")
        try:
            if Path(config.db_path).exists():
                conn = sqlite3.connect(config.db_path)
                conn.cursor().execute("SELECT 1")
                conn.close()
                print(f"  Status: ✅ CONNECTED")
            else:
                print(f"  Status: ⚠️  Will be created on first use")
        except Exception as e:
            print(f"  Status: ❌ ERROR - {str(e)[:60]}")

    if not registry:
        print("\n" + "="*70 + "\n")
        return

    # Radarr instances — one line each
    print(f"\n  Radarr:")
    if not config.radarr_instances:
        print(f"  No Radarr instances configured")
    else:
        for inst in config.radarr_instances:
            status = registry.radarr_status(inst.name)
            if not status["connected"]:
                print(f"  [{inst.name}]  ⚠️  No client — check URL, API key, and DB settings in .env")
            elif status["method"] == "direct_db":
                print(f"  [{inst.name}]  ✅ CONNECTED (direct DB)")
            else:
                print(f"  [{inst.name}]  ✅ CONNECTED (API)")

    # Sonarr instances — one line each
    print(f"\n  Sonarr:")
    if not config.sonarr_instances:
        print(f"  No Sonarr instances configured")
    else:
        for inst in config.sonarr_instances:
            status = registry.sonarr_status(inst.name)
            if not status["connected"]:
                print(f"  [{inst.name}]  ⚠️  No client — check URL, API key, and DB settings in .env")
            elif status["method"] == "direct_db":
                print(f"  [{inst.name}]  ✅ CONNECTED (direct DB)")
            else:
                print(f"  [{inst.name}]  ✅ CONNECTED (API)")

    # Summary warning — flag any instance without a working client
    no_client = (
        [n for n, s in registry.all_radarr_statuses().items() if not s["connected"]]
        + [n for n, s in registry.all_sonarr_statuses().items() if not s["connected"]]
    )
    if no_client:
        print(f"\n  ⚠️  {len(no_client)} instance(s) have no client: {', '.join(no_client)}")
        print(f"  Webhooks received for these instances will be ignored until resolved.")

    print("\n" + "="*70 + "\n")


def main():
    """Main application entry point"""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    version = get_version()

    _log("INFO", "Starting Chronarr")
    _log("INFO", f"Version: {version}")
    _log("INFO", f"TV paths: {[str(p) for p in config.tv_paths]}")
    _log("INFO", f"Movie paths: {[str(p) for p in config.movie_paths]}")
    if config.db_type == "postgresql":
        _log("INFO", f"Database: PostgreSQL at {config.db_host}:{config.db_port}/{config.db_name}")
        _log("INFO", f"Database user: {config.db_user}")
    else:
        _log("INFO", f"Database: {config.db_path}")
    _log("INFO", f"Config: manage_nfo={config.manage_nfo}, fix_mtimes={config.fix_dir_mtimes}")
    _log("INFO", f"Movie priority: {config.movie_priority}")

    # Build registry once — used for connection status display and component init
    registry = build_registry(config)

    # Test and display all database connections
    test_database_connections(registry)

    # Create FastAPI app
    app = create_app()

    # Initialize components
    dependencies = initialize_components(registry=registry)
    
    # Note: Authentication and web interface handled by separate chronarr-web container
    _log("INFO", "Core API: Authentication handled by separate web container")
    
    # Store dependencies globally for signal handler access
    signal_handler.dependencies = dependencies
    
    # Register routes
    register_routes(app, dependencies)
    
    try:
        # Core API configuration (webhooks, processing, database management)
        core_host = config.core_api_host if hasattr(config, 'core_api_host') else "0.0.0.0"
        core_port = config.core_api_port if hasattr(config, 'core_api_port') else 8080
        
        _log("INFO", f"🚀 Starting Chronarr Core API on {core_host}:{core_port}")
        
        uvicorn.run(
            app,
            host=core_host, 
            port=core_port,
            reload=False,
            access_log=False,  # Reduce logging overhead
            server_header=False,  # Reduce response overhead
            timeout_graceful_shutdown=15  # Give more time for graceful shutdown
        )
    except KeyboardInterrupt:
        _log("INFO", "Chronarr stopped by user")
    except Exception as e:
        _log("ERROR", f"Chronarr crashed: {e}")
        sys.exit(1)
    finally:
        # Ensure cleanup happens even if uvicorn doesn't trigger signal handler
        if hasattr(signal_handler, 'dependencies') and signal_handler.dependencies:
            deps = signal_handler.dependencies
            
            if 'batcher' in deps:
                try:
                    deps['batcher'].shutdown()
                except Exception:
                    pass
            
            if 'db' in deps:
                try:
                    deps['db'].close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()