"""
Async file utilities for Chronarr
High-performance async file operations with concurrent processing
"""
import asyncio
import aiofiles
import aiofiles.os
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Set
import xml.etree.ElementTree as ET
from datetime import datetime

from utils.logging import _log
from utils.exceptions import FileOperationError, NFOCreationError
from utils.file_utils import VIDEO_EXTENSIONS, extract_episode_info, extract_imdb_id_from_path
from utils.nfo_patterns import parse_nfo_with_tolerance, write_nfo_file


async def async_read_text_file(file_path: Path, encoding: str = 'utf-8') -> Optional[str]:
    """
    Async read text file with error handling
    
    Args:
        file_path: Path to file to read
        encoding: Text encoding (default: utf-8)
        
    Returns:
        File content as string or None if error
    """
    try:
        async with aiofiles.open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            return await f.read()
    except Exception as e:
        _log("WARNING", f"Failed to read file {file_path}: {e}")
        return None


async def async_write_text_file(file_path: Path, content: str, encoding: str = 'utf-8') -> bool:
    """
    Async write text file with error handling
    
    Args:
        file_path: Path to file to write
        content: Content to write
        encoding: Text encoding (default: utf-8)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure parent directory exists
        await aiofiles.os.makedirs(file_path.parent, exist_ok=True)
        
        async with aiofiles.open(file_path, 'w', encoding=encoding) as f:
            await f.write(content)
        return True
    except Exception as e:
        _log("ERROR", f"Failed to write file {file_path}: {e}")
        return False


async def async_file_exists(file_path: Path) -> bool:
    """
    Async check if file exists
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file exists, False otherwise
    """
    try:
        return await aiofiles.os.path.exists(file_path)
    except Exception:
        return False


async def async_get_file_mtime(file_path: Path) -> Optional[float]:
    """
    Async get file modification time
    
    Args:
        file_path: Path to file
        
    Returns:
        Modification time as timestamp or None if error
    """
    try:
        stat_result = await aiofiles.os.stat(file_path)
        return stat_result.st_mtime
    except Exception:
        return None


async def async_set_file_mtime(file_path: Path, mtime: float) -> bool:
    """
    Async set file modification time
    
    Args:
        file_path: Path to file
        mtime: New modification time as timestamp
        
    Returns:
        True if successful, False otherwise
    """
    try:
        await aiofiles.os.utime(file_path, (mtime, mtime))
        return True
    except Exception as e:
        _log("WARNING", f"Failed to set mtime for {file_path}: {e}")
        return False


async def async_find_video_files(directory: Path, recursive: bool = True) -> List[Path]:
    """
    Async find all video files in a directory
    
    Args:
        directory: Directory to search
        recursive: Whether to search recursively
        
    Returns:
        List of video file paths
    """
    if not await async_file_exists(directory):
        return []
    
    video_files = []
    
    try:
        if recursive:
            # Use os.walk equivalent for async
            async def _walk_directory(path: Path):
                try:
                    entries = await aiofiles.os.listdir(path)
                    for entry in entries:
                        entry_path = path / entry
                        if await aiofiles.os.path.isfile(entry_path):
                            if entry_path.suffix.lower() in VIDEO_EXTENSIONS:
                                video_files.append(entry_path)
                        elif await aiofiles.os.path.isdir(entry_path):
                            await _walk_directory(entry_path)
                except Exception as e:
                    _log("WARNING", f"Failed to scan directory {path}: {e}")
            
            await _walk_directory(directory)
        else:
            # Non-recursive scan
            try:
                entries = await aiofiles.os.listdir(directory)
                for entry in entries:
                    entry_path = directory / entry
                    if await aiofiles.os.path.isfile(entry_path):
                        if entry_path.suffix.lower() in VIDEO_EXTENSIONS:
                            video_files.append(entry_path)
            except Exception as e:
                _log("WARNING", f"Failed to scan directory {directory}: {e}")
        
    except Exception as e:
        _log("ERROR", f"Failed to find video files in {directory}: {e}")
    
    return video_files


async def async_find_episodes_on_disk(series_path: Path) -> Dict[Tuple[int, int], List[Path]]:
    """
    Async find all episodes on disk with concurrent processing
    
    Args:
        series_path: Path to series directory
        
    Returns:
        Dictionary mapping (season, episode) tuples to lists of video files
    """
    episodes = {}
    
    if not await async_file_exists(series_path):
        return episodes
    
    # Get all video files concurrently
    video_files = await async_find_video_files(series_path, recursive=True)
    
    # Process files to extract episode information
    for video_file in video_files:
        episode_info = extract_episode_info(video_file.name)
        if episode_info:
            season, episode = episode_info["season"], episode_info["episode"]
            key = (season, episode)
            if key not in episodes:
                episodes[key] = []
            episodes[key].append(video_file)
    
    return episodes


async def async_read_nfo_file(nfo_path: Path) -> Optional[ET.Element]:
    """
    Async read and parse NFO file
    
    Args:
        nfo_path: Path to NFO file
        
    Returns:
        XML root element if successful, None otherwise
    """
    if not await async_file_exists(nfo_path):
        return None
    
    try:
        content = await async_read_text_file(nfo_path)
        if not content:
            return None
        
        # Parse XML content
        try:
            root = ET.fromstring(content)
            return root
        except ET.ParseError:
            # Try with tolerance (sync operation for now)
            return parse_nfo_with_tolerance(nfo_path)
            
    except Exception as e:
        _log("ERROR", f"Failed to read NFO file {nfo_path}: {e}")
        return None


async def async_write_nfo_file(
    nfo_path: Path,
    root: ET.Element,
    lock_metadata: bool = True
) -> bool:
    """
    Async write NFO XML content to file
    
    Args:
        nfo_path: Path where to write the NFO file
        root: XML root element to write
        lock_metadata: Whether to add file locking attributes
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure parent directory exists
        await aiofiles.os.makedirs(nfo_path.parent, exist_ok=True)
        
        # Add file locking if requested
        if lock_metadata:
            root.set('chronarr_managed', 'true')
            root.set('last_updated', datetime.now().isoformat())
        
        # Create tree and format
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)  # Pretty formatting
        
        # Convert to string
        xml_str = ET.tostring(root, encoding='unicode', xml_declaration=False)
        xml_content = f'<?xml version="1.0" encoding="utf-8"?>\n{xml_str}'
        
        # Write asynchronously
        success = await async_write_text_file(nfo_path, xml_content)
        
        if success:
            _log("DEBUG", f"Successfully wrote NFO file: {nfo_path}")
        
        return success
        
    except Exception as e:
        _log("ERROR", f"Failed to write NFO file {nfo_path}: {e}")
        return False


async def async_batch_process_files(
    file_paths: List[Path],
    process_func,
    max_concurrent: int = 10,
    progress_callback: Optional[callable] = None
) -> List[Any]:
    """
    Process multiple files concurrently with controlled concurrency
    
    Args:
        file_paths: List of file paths to process
        process_func: Async function to process each file
        max_concurrent: Maximum number of concurrent operations
        progress_callback: Optional callback for progress updates
        
    Returns:
        List of results from processing each file
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []
    
    async def _process_with_semaphore(file_path: Path, index: int) -> Any:
        async with semaphore:
            try:
                result = await process_func(file_path)
                if progress_callback:
                    progress_callback(index + 1, len(file_paths), file_path)
                return result
            except Exception as e:
                _log("ERROR", f"Failed to process {file_path}: {e}")
                return None
    
    # Create tasks for all files
    tasks = [
        _process_with_semaphore(file_path, i) 
        for i, file_path in enumerate(file_paths)
    ]
    
    # Execute all tasks concurrently with controlled concurrency
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return results


async def async_batch_nfo_operations(
    nfo_operations: List[Dict[str, Any]],
    max_concurrent: int = 5
) -> List[bool]:
    """
    Batch NFO operations (read/write) with controlled concurrency
    
    Args:
        nfo_operations: List of operation dictionaries with 'type', 'path', and other params
        max_concurrent: Maximum number of concurrent operations
        
    Returns:
        List of success/failure results
    """
    async def _execute_nfo_operation(operation: Dict[str, Any]) -> bool:
        try:
            op_type = operation.get('type')
            path = operation.get('path')
            
            if op_type == 'read':
                result = await async_read_nfo_file(path)
                return result is not None
                
            elif op_type == 'write':
                root = operation.get('root')
                lock_metadata = operation.get('lock_metadata', True)
                return await async_write_nfo_file(path, root, lock_metadata)
                
            else:
                _log("ERROR", f"Unknown NFO operation type: {op_type}")
                return False
                
        except Exception as e:
            _log("ERROR", f"Failed to execute NFO operation: {e}")
            return False
    
    return await async_batch_process_files(
        [op.get('path') for op in nfo_operations],
        lambda path: _execute_nfo_operation(next(op for op in nfo_operations if op.get('path') == path)),
        max_concurrent
    )


async def async_concurrent_episode_processing(
    episodes_data: List[Dict[str, Any]],
    process_episode_func,
    max_concurrent: int = 3
) -> List[Any]:
    """
    Process multiple episodes concurrently
    
    Args:
        episodes_data: List of episode data dictionaries
        process_episode_func: Async function to process each episode
        max_concurrent: Maximum number of concurrent episode processes
        
    Returns:
        List of processing results
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def _process_episode_with_semaphore(episode_data: Dict[str, Any]) -> Any:
        async with semaphore:
            try:
                return await process_episode_func(episode_data)
            except Exception as e:
                _log("ERROR", f"Failed to process episode {episode_data}: {e}")
                return None
    
    # Create tasks for all episodes
    tasks = [
        _process_episode_with_semaphore(episode_data)
        for episode_data in episodes_data
    ]
    
    # Execute all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return results


async def async_directory_scan_with_stats(
    directories: List[Path],
    file_extensions: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    Async scan multiple directories and gather statistics
    
    Args:
        directories: List of directories to scan
        file_extensions: Optional set of file extensions to filter by
        
    Returns:
        Dictionary with scan statistics and file lists
    """
    if file_extensions is None:
        file_extensions = VIDEO_EXTENSIONS
    
    stats = {
        'total_files': 0,
        'total_directories': len(directories),
        'files_by_directory': {},
        'scan_errors': [],
        'total_size_bytes': 0
    }
    
    async def _scan_single_directory(directory: Path) -> Dict[str, Any]:
        dir_stats = {
            'path': str(directory),
            'files': [],
            'file_count': 0,
            'size_bytes': 0,
            'error': None
        }
        
        try:
            if not await async_file_exists(directory):
                dir_stats['error'] = 'Directory does not exist'
                return dir_stats
            
            files = await async_find_video_files(directory, recursive=True)
            dir_stats['files'] = [str(f) for f in files]
            dir_stats['file_count'] = len(files)
            
            # Calculate total size
            for file_path in files:
                try:
                    stat_result = await aiofiles.os.stat(file_path)
                    dir_stats['size_bytes'] += stat_result.st_size
                except Exception:
                    pass  # Skip files we can't stat
            
        except Exception as e:
            dir_stats['error'] = str(e)
            stats['scan_errors'].append(f"{directory}: {e}")
        
        return dir_stats
    
    # Scan all directories concurrently
    directory_results = await asyncio.gather(
        *[_scan_single_directory(directory) for directory in directories],
        return_exceptions=True
    )
    
    # Aggregate results
    for result in directory_results:
        if isinstance(result, dict) and not result.get('error'):
            stats['files_by_directory'][result['path']] = result
            stats['total_files'] += result['file_count']
            stats['total_size_bytes'] += result['size_bytes']
    
    return stats