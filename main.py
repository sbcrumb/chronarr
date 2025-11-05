#!/usr/bin/env python3
"""
Chronarr Core - Automated NFO file management and processing engine
Core processing container with webhooks, scanning, and database management
Web interface separated to chronarr-web container
"""
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
# from core.nfo_manager import NFOManager  # Phase 3: Removed - no longer needed
from core.path_mapper import PathMapper

# Import clients
from clients.external_clients import ExternalClientManager

# Import processors
from processors.tv_processor import TVProcessor
from processors.movie_processor import MovieProcessor

# Import webhook handling
from webhooks.webhook_batcher import WebhookBatcher

# Import API routes
from api.routes import register_routes

# Global shutdown event for graceful shutdown coordination
shutdown_event = asyncio.Event()

def get_version() -> str:
    """Get application version"""
    try:
        version = (Path(__file__).parent / "VERSION").read_text().strip()
    except:
        version = "0.1.0"

    # Check if running from dev branch (detect at runtime)
    try:
        # Try to read git branch from .git/HEAD
        git_head_path = Path(__file__).parent / ".git" / "HEAD"
        if git_head_path.exists():
            head_content = git_head_path.read_text().strip()
            if "ref: refs/heads/dev" in head_content:
                version = f"{version}-dev"
            elif head_content.startswith("ref: refs/heads/"):
                # Extract branch name for other branches
                branch = head_content.split("refs/heads/")[-1]
                if branch != "main":
                    version = f"{version}-{branch}"
    except Exception:
        # If git detection fails, that's fine - use base version
        pass

    # Check for build source (only add -gitea for local Gitea builds)
    build_source = os.environ.get("BUILD_SOURCE", "")
    if build_source == "gitea":
        if "gitea" not in version:  # Don't double-add gitea suffix
            version = f"{version}-gitea"

    return version


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    version = get_version()
    
    app = FastAPI(
        title="Chronarr",
        description="Webhook server for preserving media import dates",
        version=version
    )
    
    return app


def initialize_components():
    """Initialize all application components"""
    start_time = datetime.now(timezone.utc)
    
    # Initialize core components
    db = ChronarrDatabase(config=config)
    # nfo_manager = NFOManager(config.manager_brand, config.debug)  # Phase 3: Removed
    path_mapper = PathMapper(config)

    # Initialize processors (nfo_manager=None for backward compatibility)
    tv_processor = TVProcessor(db, None, path_mapper)
    movie_processor = MovieProcessor(db, None, path_mapper)

    # Initialize webhook batcher (no longer needs nfo_manager - Phase 3)
    batcher = WebhookBatcher(nfo_manager=None)
    batcher.set_processors(tv_processor, movie_processor)

    return {
        "db": db,
        # "nfo_manager": nfo_manager,  # Phase 3: Removed
        "path_mapper": path_mapper,
        "tv_processor": tv_processor,
        "movie_processor": movie_processor,
        "batcher": batcher,
        "start_time": start_time,
        "config": config,
        "version": get_version(),
        "shutdown_event": shutdown_event
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
    
    # Create FastAPI app
    app = create_app()
    
    # Initialize components
    dependencies = initialize_components()
    
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