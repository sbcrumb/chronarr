"""
NFO parsing patterns and utilities for Chronarr
Consolidates common NFO parsing logic and patterns
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from utils.logging import _log
from utils.exceptions import NFOCreationError, FileOperationError
from utils.validation import validate_imdb_id, validate_date_string


# Common IMDb ID patterns used across the application
IMDB_PATTERNS = [
    r'\[imdb-?(tt\d+)\]',      # [imdb-tt1234567] or [imdb-1234567]
    r'\[(tt\d+)\]',            # [tt1234567]
    r'\{imdb-?(tt\d+)\}',      # {imdb-tt1234567} or {imdb-1234567}
    r'\(imdb-?(tt\d+)\)',      # (imdb-tt1234567) or (imdb-1234567)
    r'[-_\s](tt\d+)$',         # tt1234567 at end of string
    r'imdb[_-]?(tt\d+)',       # imdb_tt1234567 or imdb-tt1234567
]

# Episode filename patterns
EPISODE_PATTERNS = [
    r'.*[sS](\d{1,2})[eE](\d{1,3}).*',    # S01E01
    r'.*(\d{1,2})x(\d{1,3}).*',           # 1x01
    r'.*[sS](\d{1,2})\.?[eE](\d{1,3}).*', # S01.E01
    r'.*Season[_\s]?(\d{1,2})[_\s]?Episode[_\s]?(\d{1,3}).*',  # Season 1 Episode 1
]

# Common NFO XML namespaces
NFO_NAMESPACES = {
    'kodi': 'http://kodi.tv/moviedb',
    'tmdb': 'https://www.themoviedb.org',
    'imdb': 'https://www.imdb.com'
}


def extract_imdb_id_from_text(text: str) -> Optional[str]:
    """
    Extract IMDb ID from text using consolidated patterns
    
    Args:
        text: Text to search for IMDb ID
        
    Returns:
        IMDb ID if found, None otherwise
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    for pattern in IMDB_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            imdb_id = match.group(1)
            # Ensure it starts with 'tt'
            if not imdb_id.startswith('tt'):
                imdb_id = f'tt{imdb_id}'
            
            if validate_imdb_id(imdb_id):
                return imdb_id
    
    return None


def extract_episode_info_from_filename(filename: str) -> Optional[Dict[str, int]]:
    """
    Extract season and episode information from filename
    
    Args:
        filename: Filename to parse
        
    Returns:
        Dictionary with 'season' and 'episode' keys if found, None otherwise
    """
    for pattern in EPISODE_PATTERNS:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            try:
                season = int(match.group(1))
                episode = int(match.group(2))
                
                # Validate reasonable ranges
                if 0 <= season <= 99 and 1 <= episode <= 999:
                    return {"season": season, "episode": episode}
            except (ValueError, IndexError):
                continue
    
    return None


def parse_nfo_with_tolerance(nfo_path: Path) -> Optional[ET.Element]:
    """
    Parse NFO file with error tolerance
    
    Args:
        nfo_path: Path to NFO file
        
    Returns:
        XML root element if successful, None otherwise
    """
    if not nfo_path.exists():
        return None
    
    try:
        # Try normal parsing first
        tree = ET.parse(nfo_path)
        return tree.getroot()
    except ET.ParseError as e:
        _log("WARNING", f"NFO parse error for {nfo_path}: {e}. Trying with tolerance...")
        
        try:
            # Try reading and cleaning the content
            content = nfo_path.read_text(encoding='utf-8', errors='ignore')
            
            # Basic cleanup for common issues
            content = content.replace('&', '&amp;')  # Fix unescaped ampersands
            content = re.sub(r'<(\w+)([^>]*?)(?<!/)>', r'<\1\2/>', content)  # Fix unclosed tags
            
            root = ET.fromstring(content)
            return root
        except Exception as e:
            _log("ERROR", f"Failed to parse NFO file {nfo_path} even with tolerance: {e}")
            return None


def extract_text_from_nfo_element(root: ET.Element, xpath: str, namespaces: Optional[Dict] = None) -> Optional[str]:
    """
    Extract text content from NFO element using XPath
    
    Args:
        root: XML root element
        xpath: XPath expression
        namespaces: Optional namespace dictionary
        
    Returns:
        Text content if found, None otherwise
    """
    try:
        if namespaces:
            elements = root.findall(xpath, namespaces)
        else:
            elements = root.findall(xpath)
        
        if elements and elements[0].text:
            return elements[0].text.strip()
    except Exception as e:
        _log("DEBUG", f"Failed to extract text from XPath {xpath}: {e}")
    
    return None


def extract_imdb_from_nfo_content(root: ET.Element) -> Optional[str]:
    """
    Extract IMDb ID from NFO XML content
    
    Args:
        root: XML root element
        
    Returns:
        IMDb ID if found, None otherwise
    """
    # Common XPath patterns for IMDb ID
    imdb_xpaths = [
        './/imdb',
        './/imdbid',
        './/id[@type="imdb"]',
        './/uniqueid[@type="imdb"]',
        './/uniqueid[@default="true"]',
        './/id',
        './/uniqueid'
    ]
    
    for xpath in imdb_xpaths:
        imdb_text = extract_text_from_nfo_element(root, xpath)
        if imdb_text:
            imdb_id = extract_imdb_id_from_text(imdb_text)
            if imdb_id:
                return imdb_id
    
    # Check in plot/overview text as fallback
    plot_xpaths = ['.//plot', './/overview', './/summary']
    for xpath in plot_xpaths:
        plot_text = extract_text_from_nfo_element(root, xpath)
        if plot_text:
            imdb_id = extract_imdb_id_from_text(plot_text)
            if imdb_id:
                return imdb_id
    
    return None


def extract_dates_from_nfo(root: ET.Element) -> Dict[str, Optional[str]]:
    """
    Extract various date fields from NFO content
    
    Args:
        root: XML root element
        
    Returns:
        Dictionary with date fields (premiered, aired, dateadded, etc.)
    """
    date_fields = {
        'premiered': ['.//premiered', './/releasedate', './/year'],
        'aired': ['.//aired', './/firstaired'],
        'dateadded': ['.//dateadded', './/added'],
        'lastplayed': ['.//lastplayed'],
        'filelastmodified': ['.//filelastmodified']
    }
    
    result = {}
    
    for field_name, xpaths in date_fields.items():
        for xpath in xpaths:
            date_text = extract_text_from_nfo_element(root, xpath)
            if date_text and validate_date_string(date_text):
                result[field_name] = date_text
                break
        else:
            result[field_name] = None
    
    return result


def create_basic_nfo_structure(
    media_type: str,
    title: str,
    imdb_id: Optional[str] = None,
    dates: Optional[Dict[str, str]] = None,
    additional_fields: Optional[Dict[str, str]] = None
) -> ET.Element:
    """
    Create basic NFO XML structure
    
    Args:
        media_type: Type of media ('movie', 'tvshow', 'episode')
        title: Media title
        imdb_id: Optional IMDb ID
        dates: Optional dictionary of date fields
        additional_fields: Optional additional fields to include
        
    Returns:
        XML root element
    """
    root = ET.Element(media_type)
    
    # Add title
    title_elem = ET.SubElement(root, 'title')
    title_elem.text = title
    
    # Add IMDb ID if provided
    if imdb_id and validate_imdb_id(imdb_id):
        imdb_elem = ET.SubElement(root, 'imdb')
        imdb_elem.text = imdb_id
        
        # Also add as uniqueid
        uniqueid_elem = ET.SubElement(root, 'uniqueid', type='imdb', default='true')
        uniqueid_elem.text = imdb_id
    
    # Add dates if provided
    if dates:
        for field_name, date_value in dates.items():
            if date_value and validate_date_string(date_value):
                date_elem = ET.SubElement(root, field_name)
                date_elem.text = date_value
    
    # Add additional fields
    if additional_fields:
        for field_name, field_value in additional_fields.items():
            if field_value:
                field_elem = ET.SubElement(root, field_name)
                field_elem.text = str(field_value)
    
    return root


def write_nfo_file(
    nfo_path: Path,
    root: ET.Element,
    lock_metadata: bool = True
) -> None:
    """
    Write NFO XML content to file
    
    Args:
        nfo_path: Path where to write the NFO file
        root: XML root element to write
        lock_metadata: Whether to add file locking attributes
        
    Raises:
        NFOCreationError: If writing fails
    """
    try:
        # Ensure parent directory exists
        nfo_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Add file locking if requested
        if lock_metadata:
            root.set('chronarr_managed', 'true')
            root.set('last_updated', datetime.now().isoformat())
        
        # Create tree and write
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)  # Pretty formatting
        
        # Write with proper XML declaration
        with open(nfo_path, 'wb') as f:
            tree.write(f, encoding='utf-8', xml_declaration=True)
        
        _log("DEBUG", f"Successfully wrote NFO file: {nfo_path}")
        
    except (OSError, ET.ParseError) as e:
        raise NFOCreationError(
            str(nfo_path),
            f"Failed to write NFO file: {e}",
            "unknown"
        )


def is_nfo_managed_by_chronarr(nfo_path: Path) -> bool:
    """
    Check if NFO file is managed by Chronarr
    
    Args:
        nfo_path: Path to NFO file
        
    Returns:
        True if managed by Chronarr, False otherwise
    """
    root = parse_nfo_with_tolerance(nfo_path)
    if root is None:
        return False
    
    return root.get('chronarr_managed') == 'true'


def extract_title_from_directory_name(directory_name: str) -> Optional[str]:
    """
    Extract clean title from directory name
    
    Args:
        directory_name: Directory name to parse
        
    Returns:
        Cleaned title or None if no title found
    """
    name = directory_name
    
    # Remove IMDb ID patterns
    for pattern in IMDB_PATTERNS:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    
    # Remove year in parentheses: (YYYY)
    name = re.sub(r'\s*\(\d{4}\)', '', name)
    
    # Remove common release info patterns
    release_patterns = [
        r'\s*\[.*?\]',  # [1080p], [BluRay], etc.
        r'\s*\{.*?\}',  # {edition info}
        r'\s*\(.*?\)',  # (additional info)
    ]
    
    for pattern in release_patterns:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    
    # Clean up extra spaces and special characters
    name = re.sub(r'[._-]+', ' ', name)  # Replace dots, underscores, dashes with spaces
    name = ' '.join(name.split())  # Normalize whitespace
    
    return name.strip() if name.strip() else None