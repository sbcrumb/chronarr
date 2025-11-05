"""
File utility functions for Chronarr
Common file operations to eliminate code duplication
"""
import glob
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Union

from utils.logging import _log


# Video file extensions used throughout the application
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.ts'}

# Episode pattern for TV series files
EPISODE_PATTERN = re.compile(
    r'.*[sS](\d{1,2})[eE](\d{1,3}).*|.*(\d{1,2})x(\d{1,3}).*'
)


def find_media_path_by_imdb_and_title(
    title: str, 
    imdb_id: str, 
    search_paths: List[Path], 
    webhook_path: Optional[str] = None,
    path_mapper = None
) -> Optional[Path]:
    """
    Unified media path finder for both TV series and movies
    
    Args:
        title: Media title to search for
        imdb_id: IMDb ID to search for
        search_paths: List of paths to search in (tv_paths or movie_paths)
        webhook_path: Optional webhook path to try first
        path_mapper: Optional path mapper for webhook path conversion
    
    Returns:
        Path to media directory if found, None otherwise
    """
    # Try webhook path first if provided
    if webhook_path and path_mapper:
        try:
            if hasattr(path_mapper, 'sonarr_path_to_container_path'):
                container_path = path_mapper.sonarr_path_to_container_path(webhook_path)
            elif hasattr(path_mapper, 'radarr_path_to_container_path'):
                container_path = path_mapper.radarr_path_to_container_path(webhook_path)
            else:
                container_path = webhook_path
                
            path_obj = Path(container_path)
            if path_obj.exists():
                return path_obj
        except Exception as e:
            _log("WARNING", f"Failed to process webhook path {webhook_path}: {e}")
    
    # Search by IMDb ID or title in configured paths
    for media_path in search_paths:
        if not media_path.exists():
            continue
        
        # Search by IMDb ID first (more reliable)
        if imdb_id:
            # Use proper glob pattern - escape brackets to match literal [imdb-ID]
            pattern = str(media_path / f"*\\[imdb-{imdb_id}\\]*")
            matches = glob.glob(pattern)
            if matches:
                return Path(matches[0])
        
        # Search by title as fallback
        if title:
            title_clean = clean_title_for_search(title)
            for item in media_path.iterdir():
                if item.is_dir() and "[imdb-" in item.name.lower():
                    item_clean = clean_title_for_search(item.name)
                    if title_clean in item_clean:
                        return item
    
    return None


def clean_title_for_search(title: str) -> str:
    """
    Clean title for fuzzy matching
    
    Args:
        title: Raw title string
        
    Returns:
        Cleaned title for comparison
    """
    return title.lower().replace(" ", "").replace("-", "").replace(".", "")


def find_video_files(directory: Path, recursive: bool = True) -> List[Path]:
    """
    Find all video files in a directory
    
    Args:
        directory: Directory to search
        recursive: Whether to search recursively
        
    Returns:
        List of video file paths
    """
    if not directory.exists():
        return []
    
    video_files = []
    
    if recursive:
        for item in directory.rglob('*'):
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(item)
    else:
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(item)
    
    return video_files


def extract_episode_info(filename: str) -> Optional[Tuple[int, int]]:
    """
    Extract season and episode numbers from filename
    
    Args:
        filename: Video filename to parse
        
    Returns:
        Tuple of (season, episode) if found, None otherwise
    """
    match = EPISODE_PATTERN.match(filename)
    if not match:
        return None
    
    if match.group(1) and match.group(2):  # SxxExx format
        season = int(match.group(1))
        episode = int(match.group(2))
    elif match.group(3) and match.group(4):  # NxNN format
        season = int(match.group(3))
        episode = int(match.group(4))
    else:
        return None
    
    return (season, episode)


def find_episodes_on_disk(series_path: Path) -> Dict[Tuple[int, int], List[Path]]:
    """
    Find all episodes on disk and return mapping of (season, episode) -> [video_files]
    
    Args:
        series_path: Path to series directory
        
    Returns:
        Dictionary mapping (season, episode) tuples to lists of video files
    """
    episodes = {}
    
    if not series_path.exists():
        return episodes
    
    for video_file in find_video_files(series_path, recursive=True):
        episode_info = extract_episode_info(video_file.name)
        if episode_info:
            season, episode = episode_info
            key = (season, episode)
            if key not in episodes:
                episodes[key] = []
            episodes[key].append(video_file)
    
    return episodes


def extract_title_from_directory_name(directory_name: str) -> Optional[str]:
    """
    Extract clean title from directory name, removing year and IMDb ID
    
    Args:
        directory_name: Directory name to parse
        
    Returns:
        Cleaned title or None if no title found
    """
    name = directory_name
    
    # Remove IMDb ID part: [imdb-ttXXXXXX] or [ttXXXXXX]
    name = re.sub(r'\s*\[imdb-?tt\d+\]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\[tt\d+\]', '', name, flags=re.IGNORECASE)
    
    # Remove year in parentheses: (YYYY)
    name = re.sub(r'\s*\(\d{4}\)', '', name)
    
    # Clean up extra spaces
    name = ' '.join(name.split())
    
    return name.strip() if name.strip() else None


def extract_imdb_id_from_path(path: Union[str, Path]) -> Optional[str]:
    """
    Extract IMDb ID from directory or file path
    
    Args:
        path: Path to examine (string or Path object)
        
    Returns:
        IMDb ID if found, None otherwise
    """
    path_str = str(path)
    
    # Look for [imdb-ttXXXXXX] or [ttXXXXXX] patterns
    patterns = [
        r'\[imdb-(tt\d+)\]',  # [imdb-tt1234567]
        r'\[(tt\d+)\]',       # [tt1234567]
        r'imdb[_-]?(tt\d+)',  # imdb_tt1234567 or imdb-tt1234567
        r'(tt\d{7,})',        # standalone tt1234567 (7+ digits)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, path_str, re.IGNORECASE)
        if match:
            imdb_id = match.group(1)
            # Ensure it starts with 'tt'
            if not imdb_id.startswith('tt'):
                imdb_id = f'tt{imdb_id}'
            return imdb_id
    
    return None


def is_video_file(file_path: Path) -> bool:
    """
    Check if a file is a video file based on extension
    
    Args:
        file_path: Path to check
        
    Returns:
        True if it's a video file, False otherwise
    """
    return file_path.suffix.lower() in VIDEO_EXTENSIONS


def safe_directory_scan(directory: Path, pattern: str = "*") -> List[Path]:
    """
    Safely scan directory with error handling
    
    Args:
        directory: Directory to scan
        pattern: Glob pattern to match
        
    Returns:
        List of matching paths, empty list if scan fails
    """
    try:
        if not directory.exists():
            return []
        return list(directory.glob(pattern))
    except (PermissionError, OSError) as e:
        _log("WARNING", f"Failed to scan directory {directory}: {e}")
        return []


def normalize_path_separators(path: str) -> str:
    """
    Normalize path separators for cross-platform compatibility
    
    Args:
        path: Path string to normalize
        
    Returns:
        Normalized path string
    """
    return str(Path(path).as_posix())