#!/usr/bin/env python3
"""
Debug script to check specific movie data in Chronarr database
"""
import os
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import ChronarrDatabase
from config.settings import config

def debug_movie(imdb_id: str):
    """Debug a specific movie's data"""
    print(f"🔍 DEBUG MOVIE: {imdb_id}")
    print("=" * 50)
    
    # Initialize database
    db = ChronarrDatabase(config=config)
    
    # Get movie data
    movie = db.get_movie_dates(imdb_id)
    if not movie:
        print(f"❌ Movie {imdb_id} not found in database")
        return
    
    print("📊 RAW MOVIE DATA:")
    for key, value in movie.items():
        print(f"   {key}: {repr(value)}")
    
    print("\n🎬 FORMATTED MOVIE DATA:")
    print(f"   Title/Path: {movie.get('path', 'Unknown')}")
    print(f"   Released: {movie.get('released', 'None')}")
    print(f"   Date Added: {movie.get('dateadded', 'None')}")
    print(f"   Source: {movie.get('source', 'None')}")
    print(f"   Has Video: {movie.get('has_video_file', False)}")
    print(f"   Last Updated: {movie.get('last_updated', 'None')}")
    
    # Check if released date is valid
    released = movie.get('released')
    if released and released.strip():
        try:
            from datetime import datetime
            test_date = f"{released}T00:00:00"
            parsed = datetime.fromisoformat(test_date.replace('Z', '+00:00'))
            print(f"\n✅ Released date is valid: {parsed}")
        except Exception as e:
            print(f"\n❌ Released date is INVALID: {e}")
    else:
        print(f"\n⚠️ Released date is empty or None")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_movie.py <imdb_id>")
        sys.exit(1)
    
    imdb_id = sys.argv[1]
    if not imdb_id.startswith('tt'):
        imdb_id = f'tt{imdb_id}'
    
    debug_movie(imdb_id)