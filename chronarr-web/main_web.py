"""
Chronarr Web Interface - Separated Web Application
Lightweight FastAPI application for web interface only
"""
import asyncio
import signal
import sys
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Add current directory and parent directory to path for imports
sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

# Import web-specific configuration
from config.web_settings import web_config

# Import database (lightweight, read-only access)
from core.web_database import WebDatabase

# Import web routes and authentication
from api.web_routes import register_web_routes
from api.auth import SimpleAuthMiddleware, create_auth_dependencies


def create_web_app() -> FastAPI:
    """Create FastAPI web application"""
    app = FastAPI(
        title="Chronarr Web Interface",
        description="Web interface for Chronarr media database management",
        version="2.9.0-fixes-only-files",
        docs_url="/docs" if web_config.web_debug else None,
        redoc_url="/redoc" if web_config.web_debug else None
    )
    
    return app


def initialize_web_database() -> WebDatabase:
    """Initialize web database connection (read-only optimized)"""
    return WebDatabase(
        db_type=web_config.db_type,
        host=web_config.db_host,
        port=web_config.db_port,
        database=web_config.db_name,
        user=web_config.db_user,
        password=web_config.db_password
    )


def setup_static_files(app: FastAPI) -> None:
    """Mount static file directories"""
    # Mount main static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    # Mount logo separately for easy access
    app.mount("/logo", StaticFiles(directory="logo"), name="logo")
    
    # Serve index.html at root
    @app.get("/")
    async def serve_index():
        return FileResponse("static/index.html")


def setup_signal_handlers():
    """Setup graceful shutdown signal handlers"""
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, shutting down web interface...")
        # Web interface can shutdown immediately (no background processing)
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def main():
    """Main entry point for Chronarr Web Interface"""
    print("🌐 Starting Chronarr Web Interface...")
    print(f"📊 Configuration: Port {web_config.web_port}, Auth: {'Enabled' if web_config.web_auth_enabled else 'Disabled'}")
    
    # Setup signal handlers
    setup_signal_handlers()
    
    # Create FastAPI app
    app = create_web_app()
    
    # Initialize database
    try:
        db = initialize_web_database()
        print(f"✅ Connected to database: {web_config.db_host}:{web_config.db_port}/{web_config.db_name}")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)
    
    # Create dependencies for dependency injection
    dependencies = {
        "db": db,
        "config": web_config
    }
    
    # Add authentication dependencies if enabled
    if web_config.web_auth_enabled:
        auth_deps = create_auth_dependencies(web_config)
        dependencies.update(auth_deps)
        
        # Add authentication middleware
        app.add_middleware(SimpleAuthMiddleware, config=web_config)
        print(f"🔐 Web authentication enabled for user: {web_config.web_auth_username}")
    else:
        print("🔓 Web authentication disabled - interface is public")
    
    # Setup static files and routes
    setup_static_files(app)
    
    # Register web routes
    register_web_routes(app, dependencies)
    
    print(f"🚀 Starting web server on {web_config.web_host}:{web_config.web_port}")
    
    try:
        uvicorn.run(
            app,
            host=web_config.web_host,
            port=web_config.web_port,
            workers=web_config.web_workers,
            log_level="debug" if web_config.web_debug else "info",
            access_log=web_config.web_debug
        )
    except KeyboardInterrupt:
        print("\n🛑 Web interface shutdown by user")
    except Exception as e:
        print(f"❌ Web interface failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()