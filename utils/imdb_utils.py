#!/usr/bin/env python3
"""
IMDb ID Extraction Utilities
Parses IMDb IDs from directory/file names (no file I/O)
Phase 3: Replaces NFOManager for IMDb ID extraction only
"""
import re
from pathlib import Path
from typing import Optional


def parse_imdb_from_path(path: Path) -> Optional[str]:
    """
    Extract IMDb ID from directory path or filename using regex patterns.
    Does NOT read any files - only parses the path string.

    Supported patterns:
    - [imdb-tt1234567]
    - [tt1234567]
    - {imdb-tt1234567}
    - (imdb-tt1234567)
    - -tt1234567 (at end)
    - _tt1234567 (at end)

    Args:
        path: Path object to parse

    Returns:
        IMDb ID (e.g., "tt1234567") or None if not found
    """
    path_str = str(path).lower()

    # Try [imdb-ttXXXXXXX] format first (most explicit)
    match = re.search(r'\[imdb-?(tt\d+)\]', path_str)
    if match:
        return match.group(1)

    # Try standalone [ttXXXXXXX] format in brackets
    match = re.search(r'\[(tt\d+)\]', path_str)
    if match:
        return match.group(1)

    # Try {imdb-ttXXXXXXX} format with curly braces
    match = re.search(r'\{imdb-?(tt\d+)\}', path_str)
    if match:
        return match.group(1)

    # Try (imdb-ttXXXXXXX) format with parentheses
    match = re.search(r'\(imdb-?(tt\d+)\)', path_str)
    if match:
        return match.group(1)

    # Try ttXXXXXXX at end of filename/dirname (common pattern)
    match = re.search(r'[-_\s](tt\d+)$', path_str)
    if match:
        return match.group(1)

    return None


def find_imdb_in_directory(directory: Path) -> Optional[str]:
    """
    Find IMDb ID from directory name or filenames within the directory.
    Does NOT read file contents - only checks filenames.

    Args:
        directory: Directory path to search

    Returns:
        IMDb ID or None if not found
    """
    # First try directory name itself
    imdb_id = parse_imdb_from_path(directory)
    if imdb_id:
        return imdb_id

    # Try all filenames in the directory
    if directory.is_dir():
        for file_path in directory.iterdir():
            if file_path.is_file():
                imdb_id = parse_imdb_from_path(file_path)
                if imdb_id:
                    return imdb_id

    return None
