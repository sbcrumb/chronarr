#!/usr/bin/env python3
"""
Path mapping utilities for Chronarr
Handles conversion between external service paths and container paths
"""
import os
import re
from pathlib import Path

class PathMapper:
    """Handles path mapping between different environments"""
    
    def __init__(self, config):
        """Initialize path mapper with configuration"""
        # Use environment variables directly since config attribute names are unclear
        import os
        
        radarr_roots_str = os.getenv('RADARR_ROOT_FOLDERS', '')
        sonarr_roots_str = os.getenv('SONARR_ROOT_FOLDERS', '')
        movie_paths_str = os.getenv('MOVIE_PATHS', '')
        tv_paths_str = os.getenv('TV_PATHS', '')
        
        self.radarr_roots = [path.strip() for path in radarr_roots_str.split(',') if path.strip()]
        self.sonarr_roots = [path.strip() for path in sonarr_roots_str.split(',') if path.strip()]
        self.movie_paths = [path.strip() for path in movie_paths_str.split(',') if path.strip()]
        self.tv_paths = [path.strip() for path in tv_paths_str.split(',') if path.strip()]
        
        # Check if path debugging is enabled
        self.path_debug = os.getenv('PATH_DEBUG', 'false').lower() == 'true'
        
        if self.path_debug:
            print(f"PATH_DEBUG: PathMapper initialized with:")
            print(f"PATH_DEBUG: radarr_roots: {self.radarr_roots}")
            print(f"PATH_DEBUG: sonarr_roots: {self.sonarr_roots}")
            print(f"PATH_DEBUG: movie_paths: {self.movie_paths}")
            print(f"PATH_DEBUG: tv_paths: {self.tv_paths}")

    def sonarr_path_to_container_path(self, sonarr_path: str) -> str:
        """Convert Sonarr path to container path using environment mappings"""
        if self.path_debug:
            print(f"PATH_DEBUG: sonarr_path_to_container_path input: {sonarr_path}")
            print(f"PATH_DEBUG: sonarr_roots: {self.sonarr_roots}")
            print(f"PATH_DEBUG: tv_paths: {self.tv_paths}")
        
        # Sort roots by length (longest first) to avoid substring matching issues
        indexed_roots = [(i, root) for i, root in enumerate(self.sonarr_roots)]
        indexed_roots.sort(key=lambda x: len(x[1]), reverse=True)
        
        # Try to match against configured Sonarr root folders (longest first)
        for original_index, sonarr_root in indexed_roots:
            if self.path_debug:
                print(f"PATH_DEBUG: Checking sonarr_root[{original_index}]: {sonarr_root}")
            if sonarr_path.startswith(sonarr_root + '/') or sonarr_path == sonarr_root:
                if self.path_debug:
                    print(f"PATH_DEBUG: Match found! Index {original_index}")
                # Map to corresponding TV path
                if original_index < len(self.tv_paths):
                    container_root = self.tv_paths[original_index]
                    relative_path = sonarr_path[len(sonarr_root):].lstrip('/')
                    result = str(Path(container_root) / relative_path) if relative_path else container_root
                    if self.path_debug:
                        print(f"PATH_DEBUG: Mapped to: {result}")
                    return result
        
        if self.path_debug:
            print(f"PATH_DEBUG: No match found, returning original: {sonarr_path}")
        # No fallback - if path mapping fails, return original and let validation catch it
        return sonarr_path
    
    def radarr_path_to_container_path(self, radarr_path: str) -> str:
        """Convert Radarr path to container path using environment mappings"""
        if self.path_debug:
            print(f"PATH_DEBUG: radarr_path_to_container_path input: {radarr_path}")
            print(f"PATH_DEBUG: radarr_roots: {self.radarr_roots}")
            print(f"PATH_DEBUG: movie_paths: {self.movie_paths}")
        
        # Sort roots by length (longest first) to avoid substring matching issues
        indexed_roots = [(i, root) for i, root in enumerate(self.radarr_roots)]
        indexed_roots.sort(key=lambda x: len(x[1]), reverse=True)
        
        # Try to match against configured Radarr root folders (longest first)
        for original_index, radarr_root in indexed_roots:
            if self.path_debug:
                print(f"PATH_DEBUG: Checking radarr_root[{original_index}]: {radarr_root}")
            if radarr_path.startswith(radarr_root + '/') or radarr_path == radarr_root:
                if self.path_debug:
                    print(f"PATH_DEBUG: Match found! Index {original_index}")
                # Map to corresponding movie path
                if original_index < len(self.movie_paths):
                    container_root = self.movie_paths[original_index]
                    relative_path = radarr_path[len(radarr_root):].lstrip('/')
                    result = str(Path(container_root) / relative_path) if relative_path else container_root
                    if self.path_debug:
                        print(f"PATH_DEBUG: Mapped to: {result}")
                    return result
        
        if self.path_debug:
            print(f"PATH_DEBUG: No match found, returning original: {radarr_path}")
        # No fallback - if path mapping fails, return original and let validation catch it
        return radarr_path
    
    def container_path_to_host_path(self, container_path: str) -> str:
        """Convert container path back to host path if needed"""
        # This might be needed for file operations
        return container_path