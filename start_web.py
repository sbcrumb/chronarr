#!/usr/bin/env python3
"""
Chronarr Web Interface Starter
Simple script to start web interface using existing config system
"""
import os
import sys
import time
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Import existing configuration (keep using core config for simplicity)
from config.settings import config

# Import existing database and components
from core.database import ChronarrDatabase

# Import web routes from existing system (now includes DELETE route)
from api.web_routes import register_web_routes

# Import authentication system
from api.auth import SimpleAuthMiddleware, AuthSession

# Import version utility
from version_utils import get_version


def create_web_app() -> FastAPI:
    """Create FastAPI web application"""
    app = FastAPI(
        title="Chronarr Web Interface",
        description="Web interface for Chronarr media database management",
        version=get_version(),
        docs_url=None,  # Disable docs in production
        redoc_url=None
    )

    return app


def setup_static_files(app: FastAPI) -> None:
    """Mount static file directories"""
    static_path = os.path.join(os.path.dirname(__file__), "chronarr-web", "static")
    logo_path = os.path.join(os.path.dirname(__file__), "logo")
    
    print(f"🔍 Checking static path: {static_path} (exists: {os.path.exists(static_path)})")
    print(f"🔍 Checking logo path: {logo_path} (exists: {os.path.exists(logo_path)})")
    
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")
        print(f"✅ Mounted static files from: {static_path}")
    else:
        print(f"❌ Static path not found: {static_path}")
    
    if os.path.exists(logo_path):
        app.mount("/logo", StaticFiles(directory=logo_path), name="logo")
        print(f"✅ Mounted logo files from: {logo_path}")
    else:
        print(f"❌ Logo path not found: {logo_path}")
    
    # Serve index.html at root
    @app.get("/")
    async def serve_index():
        index_file = os.path.join(static_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        else:
            return {"message": "Chronarr Web Interface", "status": "running"}
    
    # Serve favicon
    @app.get("/favicon.ico")
    async def serve_favicon():
        # Try to serve favicon from logo directory or static files
        favicon_paths = [
            os.path.join(logo_path, "favicon.ico"),
            os.path.join(static_path, "favicon.ico"),
            os.path.join(logo_path, "ChronarrLogo.png")  # Fallback to new logo
        ]
        
        for favicon_path in favicon_paths:
            if os.path.exists(favicon_path):
                return FileResponse(favicon_path)
        
        # Return 204 No Content if no favicon found
        from fastapi import Response
        return Response(status_code=204)
    
    # Health check endpoint for Docker
    @app.get("/health")
    async def health_check():
        """Health check endpoint for Docker container monitoring"""
        try:
            # Basic health check - verify the web service is responsive
            return {
                "status": "healthy",
                "service": "chronarr-web",
                "timestamp": time.time(),
                "version": get_version()
            }
        except Exception as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail=f"Health check failed: {e}")


def test_database_connection():
    """Test and report Chronarr database connection (web container only needs this)"""
    import psycopg2
    import sqlite3
    from pathlib import Path

    print("\n" + "="*70)
    print("  WEB INTERFACE - DATABASE CONNECTION")
    print("="*70)

    print(f"\n  Chronarr Database:")
    if config.db_type == "postgresql":
        print(f"  Type: PostgreSQL")
        print(f"  Host: {config.db_host}:{config.db_port}")
        print(f"  Database: {config.db_name}")
        print(f"  User: {config.db_user}")

        try:
            # Attempt actual connection
            conn = psycopg2.connect(
                host=config.db_host,
                port=config.db_port,
                database=config.db_name,
                user=config.db_user,
                password=config.db_password
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            print(f"  Status: ✅ CONNECTED")
        except Exception as e:
            print(f"  Status: ❌ ERROR - {str(e)[:50]}")
    else:
        print(f"  Type: SQLite")
        print(f"  Path: {config.db_path}")
        try:
            if Path(config.db_path).exists():
                conn = sqlite3.connect(config.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                conn.close()
                print(f"  Status: ✅ CONNECTED")
            else:
                print(f"  Status: ⚠️  Database file will be created on first use")
        except Exception as e:
            print(f"  Status: ❌ ERROR - {str(e)[:50]}")

    print("\n  Note: Radarr/Sonarr database connections tested in Core container")
    print("="*70 + "\n")


def main():
    """Main entry point for Chronarr Web Interface"""
    print("🌐 Starting Chronarr Web Interface...")

    # Use existing config system
    web_host = os.environ.get("WEB_HOST", "0.0.0.0")
    web_port = int(os.environ.get("WEB_PORT", "8081"))

    print(f"📊 Configuration: Port {web_port}")

    # Create FastAPI app
    app = create_web_app()

    # Initialize database using existing system
    try:
        db = ChronarrDatabase(config)
        print(f"✅ Connected to database: {config.db_host}:{config.db_port}/{config.db_name}")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)

    # Test and display Chronarr database connection
    test_database_connection()
    
    # Setup authentication if enabled
    auth_enabled = getattr(config, 'web_auth_enabled', False)
    session_manager = None
    
    if auth_enabled:
        session_timeout = getattr(config, 'web_auth_session_timeout', 3600)
        session_manager = AuthSession(timeout_seconds=session_timeout)
        print(f"🔐 Web authentication enabled (session timeout: {session_timeout}s)")
    else:
        print("🌐 Web authentication disabled")
    
    # Create dependencies for dependency injection
    dependencies = {
        "db": db,
        "config": config,
        "nfo_manager": None,  # Not needed for read-only web interface
        "movie_processor": None,  # Not needed for read-only web interface  
        "tv_processor": None,  # Not needed for read-only web interface
        "auth_enabled": auth_enabled,
        "session_manager": session_manager
    }
    
    # Add authentication middleware if enabled (BEFORE routes)
    if auth_enabled:
        app.add_middleware(SimpleAuthMiddleware, config=config, session_manager=session_manager)
        print("🔐 Authentication middleware added to web interface")
    
    # Setup static files and routes
    setup_static_files(app)
    
    # Register web routes (now includes DELETE /api/episodes/ route)
    register_web_routes(app, dependencies)
    print("✅ Registered web routes with DELETE /api/episodes/ support")

    # Start daily library-sync auto-purge background task (runs every 24h)
    _start_library_sync_task(db)

    print(f"🚀 Starting web server on {web_host}:{web_port}")

    try:
        uvicorn.run(
            app,
            host=web_host,
            port=web_port,
            workers=1,
            log_level="info",
            access_log=False
        )
    except KeyboardInterrupt:
        print("\n🛑 Web interface shutdown by user")
    except Exception as e:
        print(f"❌ Web interface failed: {e}")
        sys.exit(1)


def _start_library_sync_task(db):
    """Start a daemon thread that runs the library-sync auto-purge every 24 hours."""
    import threading
    import time as _time
    import os

    movie_days = int(os.environ.get("PURGE_MISSING_MOVIES_DAYS", "0") or 0)
    tv_days = int(os.environ.get("PURGE_MISSING_TV_DAYS", "0") or 0)

    if movie_days == 0 and tv_days == 0:
        print("ℹ️  Library sync auto-purge disabled (PURGE_MISSING_MOVIES_DAYS and PURGE_MISSING_TV_DAYS both 0)")
        return

    print(f"🔄 Library sync auto-purge enabled — movies: {movie_days}d, tv: {tv_days}d")

    def _loop():
        # Wait 60s after startup before first run so DB is fully ready
        _time.sleep(60)
        while True:
            try:
                from utils import source_sync
                result = source_sync.run_auto_purge(db)
                if not result.get("skipped"):
                    print(f"🗑️  Library sync purge: deleted {result.get('deleted_movies', 0)} movies, "
                          f"{result.get('deleted_series', 0)} series")
            except Exception as e:
                print(f"⚠️  Library sync auto-purge error: {e}")
            _time.sleep(86400)  # 24 hours

    t = threading.Thread(target=_loop, daemon=True, name="library-sync-purge")
    t.start()


if __name__ == "__main__":
    main()