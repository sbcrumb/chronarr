"""
Simple authentication middleware for Chronarr web interface
Provides basic HTTP auth and session management for web interface protection
"""
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.base import BaseHTTPMiddleware


class AuthSession:
    """Simple session management for web interface"""
    
    def __init__(self, timeout_seconds: int = 3600):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.timeout_seconds = timeout_seconds
    
    def create_session(self, username: str) -> str:
        """Create a new session and return session token"""
        session_token = secrets.token_urlsafe(32)
        self.sessions[session_token] = {
            "username": username,
            "created_at": datetime.utcnow(),
            "last_activity": datetime.utcnow()
        }
        return session_token
    
    def validate_session(self, session_token: str) -> bool:
        """Validate session token and update last activity"""
        if not session_token or session_token not in self.sessions:
            return False
        
        session = self.sessions[session_token]
        now = datetime.utcnow()
        
        # Check if session expired
        if (now - session["last_activity"]).seconds > self.timeout_seconds:
            del self.sessions[session_token]
            return False
        
        # Update last activity
        session["last_activity"] = now
        return True
    
    def get_session_user(self, session_token: str) -> Optional[str]:
        """Get username from valid session"""
        if self.validate_session(session_token):
            return self.sessions[session_token]["username"]
        return None
    
    def delete_session(self, session_token: str) -> None:
        """Delete a session (logout)"""
        if session_token in self.sessions:
            del self.sessions[session_token]
    
    def cleanup_expired_sessions(self) -> None:
        """Remove expired sessions"""
        now = datetime.utcnow()
        expired_tokens = []
        
        for token, session in self.sessions.items():
            if (now - session["last_activity"]).seconds > self.timeout_seconds:
                expired_tokens.append(token)
        
        for token in expired_tokens:
            del self.sessions[token]


class SimpleAuthMiddleware(BaseHTTPMiddleware):
    """Simple authentication middleware for web interface routes"""
    
    def __init__(self, app, config, session_manager=None):
        super().__init__(app)
        self.config = config
        self.session_manager = session_manager or AuthSession(config.web_auth_session_timeout)
        self.security = HTTPBasic()
        
        # Routes that require authentication (web interface)
        self.protected_routes = [
            "/",  # Main web interface
            "/static/",  # Static files (CSS, JS)
            "/api/movies",  # Web API endpoints
            "/api/series",
            "/api/episodes",
            "/api/dashboard"
        ]
        
        # Routes that are always public (webhooks, health checks, API endpoints)
        self.public_routes = [
            "/webhook/",
            "/health",
            "/logo/",  # Logo files should always be accessible
            "/favicon.ico",  # Favicon should always be accessible
            "/ping",
            "/api/v1/health",
            "/api/v1/metrics",
            "/database/",  # Database management endpoints (API access)
            "/manual/",    # Manual scan endpoints (API access)
            "/debug/",     # Debug endpoints (API access)
            "/test/",      # Test endpoints (API access)
            "/bulk/"       # Bulk operation endpoints (API access)
        ]
    
    async def dispatch(self, request: Request, call_next):
        """Process request through authentication middleware"""
        
        # Skip authentication if disabled
        if not self.config.web_auth_enabled:
            return await call_next(request)
        
        # Check if route requires authentication
        path = request.url.path
        needs_auth = any(path.startswith(route) for route in self.protected_routes)
        is_public = any(path.startswith(route) for route in self.public_routes)
        
        if is_public or not needs_auth:
            return await call_next(request)
        
        # Check for existing session
        session_token = request.cookies.get("chronarr_session")
        if session_token and self.session_manager.validate_session(session_token):
            # Valid session, proceed
            return await call_next(request)
        
        # Check for HTTP Basic Auth
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Basic "):
            credentials = self._parse_basic_auth(auth_header)
            if credentials and self._validate_credentials(credentials.username, credentials.password):
                # Create session for successful login
                session_token = self.session_manager.create_session(credentials.username)
                response = await call_next(request)
                response.set_cookie(
                    key="chronarr_session", 
                    value=session_token,
                    max_age=self.config.web_auth_session_timeout,
                    httponly=True,
                    secure=False  # Set to True if using HTTPS
                )
                return response
        
        # Authentication required
        return self._auth_required_response()
    
    def _parse_basic_auth(self, auth_header: str) -> Optional[HTTPBasicCredentials]:
        """Parse HTTP Basic Auth header"""
        try:
            import base64
            encoded_credentials = auth_header.split(" ")[1]
            decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
            username, password = decoded_credentials.split(":", 1)
            return HTTPBasicCredentials(username=username, password=password)
        except Exception:
            return None
    
    def _validate_credentials(self, username: str, password: str) -> bool:
        """Validate username and password"""
        return (username == self.config.web_auth_username and 
                password == self.config.web_auth_password)
    
    def _auth_required_response(self) -> Response:
        """Return 401 response with WWW-Authenticate header"""
        return Response(
            content="Authentication required",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm=\"Chronarr Web Interface\""}
        )


def create_auth_dependencies(config) -> Dict[str, Any]:
    """Create authentication-related dependencies for dependency injection"""
    session_manager = AuthSession(config.web_auth_session_timeout)
    
    return {
        "session_manager": session_manager,
        "auth_enabled": config.web_auth_enabled,
        "auth_config": {
            "username": config.web_auth_username,
            "timeout": config.web_auth_session_timeout
        }
    }