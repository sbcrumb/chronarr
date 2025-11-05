#!/usr/bin/env python3
"""
Debug script to check specific TV series/episode data in Chronarr database
"""
import os
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import ChronarrDatabase
from config.settings import config

def debug_series(imdb_id: str):
    """Debug a specific TV series' data"""
    print(f"📺 DEBUG TV SERIES: {imdb_id}")
    print("=" * 60)
    
    # Initialize database
    db = ChronarrDatabase(config=config)
    
    # Get series episodes
    episodes = db.get_series_episodes(imdb_id)
    if not episodes:
        print(f"❌ TV series {imdb_id} not found in database")
        return
    
    print(f"📊 SERIES OVERVIEW:")
    print(f"   IMDb ID: {imdb_id}")
    print(f"   Total Episodes: {len(episodes)}")
    
    # Count episodes by status
    with_dates = sum(1 for ep in episodes if ep.get('dateadded'))
    without_dates = len(episodes) - with_dates
    with_video = sum(1 for ep in episodes if ep.get('has_video_file'))
    
    print(f"   Episodes with dates: {with_dates}")
    print(f"   Episodes without dates: {without_dates}")
    print(f"   Episodes with video files: {with_video}")
    
    # Group by season
    seasons = {}
    for ep in episodes:
        season = ep.get('season', 'Unknown')
        if season not in seasons:
            seasons[season] = []
        seasons[season].append(ep)
    
    print(f"   Seasons: {len(seasons)} ({', '.join(f'S{s}' if isinstance(s, int) else str(s) for s in sorted(seasons.keys()))})")
    
    # Show sources breakdown
    sources = {}
    for ep in episodes:
        source = ep.get('source', 'None')
        sources[source] = sources.get(source, 0) + 1
    
    print(f"\n📈 SOURCES BREAKDOWN:")
    for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
        print(f"   {source}: {count} episodes")
    
    # Show recent episodes (last 10 by date added)
    episodes_with_dates = [ep for ep in episodes if ep.get('dateadded')]
    recent_episodes = sorted(episodes_with_dates, key=lambda x: x.get('last_updated', ''), reverse=True)[:10]
    
    if recent_episodes:
        print(f"\n🕒 RECENT EPISODES (by last_updated):")
        for ep in recent_episodes:
            season = ep.get('season', '?')
            episode = ep.get('episode', '?')
            dateadded = ep.get('dateadded', 'None')
            source = ep.get('source', 'None')
            video = "✅" if ep.get('has_video_file') else "❌"
            print(f"   S{season:02d}E{episode:02d}: {dateadded} | {source} | Video: {video}")

def debug_episode(imdb_id: str, season: int, episode: int):
    """Debug a specific episode's data"""
    print(f"📺 DEBUG TV EPISODE: {imdb_id} S{season:02d}E{episode:02d}")
    print("=" * 60)
    
    # Initialize database
    db = ChronarrDatabase(config=config)
    
    # Get specific episode
    episode_data = db.get_episode_date(imdb_id, season, episode)
    if not episode_data:
        print(f"❌ Episode S{season:02d}E{episode:02d} for series {imdb_id} not found in database")
        return
    
    print("📊 RAW EPISODE DATA:")
    for key, value in episode_data.items():
        print(f"   {key}: {repr(value)}")
    
    print("\n📺 FORMATTED EPISODE DATA:")
    print(f"   Series IMDb: {episode_data.get('imdb_id', 'Unknown')}")
    print(f"   Season/Episode: S{episode_data.get('season', '?'):02d}E{episode_data.get('episode', '?'):02d}")
    print(f"   Title: {episode_data.get('title', 'Unknown')}")
    print(f"   Air Date: {episode_data.get('air_date', 'None')}")
    print(f"   Date Added: {episode_data.get('dateadded', 'None')}")
    print(f"   Source: {episode_data.get('source', 'None')}")
    print(f"   Has Video: {episode_data.get('has_video_file', False)}")
    print(f"   Video Path: {episode_data.get('video_path', 'None')}")
    print(f"   Last Updated: {episode_data.get('last_updated', 'None')}")
    
    # Check if air date is valid
    air_date = episode_data.get('air_date')
    if air_date and air_date.strip():
        try:
            from datetime import datetime
            test_date = f"{air_date}T00:00:00"
            parsed = datetime.fromisoformat(test_date.replace('Z', '+00:00'))
            print(f"\n✅ Air date is valid: {parsed}")
        except Exception as e:
            print(f"\n❌ Air date is INVALID: {e}")
    else:
        print(f"\n⚠️ Air date is empty or None")
    
    # Check if dateadded is valid
    dateadded = episode_data.get('dateadded')
    if dateadded and dateadded.strip():
        try:
            from datetime import datetime
            if isinstance(dateadded, str):
                test_date = f"{dateadded}T00:00:00" if 'T' not in dateadded else dateadded
                parsed = datetime.fromisoformat(test_date.replace('Z', '+00:00'))
            else:
                parsed = dateadded
            print(f"✅ Date added is valid: {parsed}")
        except Exception as e:
            print(f"❌ Date added is INVALID: {e}")
    else:
        print(f"⚠️ Date added is empty or None")

def debug_season(imdb_id: str, season: int):
    """Debug all episodes in a specific season"""
    print(f"📺 DEBUG TV SEASON: {imdb_id} Season {season}")
    print("=" * 60)
    
    # Initialize database
    db = ChronarrDatabase(config=config)
    
    # Get series episodes
    all_episodes = db.get_series_episodes(imdb_id)
    season_episodes = [ep for ep in all_episodes if ep.get('season') == season]
    
    if not season_episodes:
        print(f"❌ No episodes found for season {season} of series {imdb_id}")
        return
    
    print(f"📊 SEASON {season} OVERVIEW:")
    print(f"   Total Episodes: {len(season_episodes)}")
    
    # Sort by episode number
    season_episodes.sort(key=lambda x: x.get('episode', 0))
    
    with_dates = sum(1 for ep in season_episodes if ep.get('dateadded'))
    without_dates = len(season_episodes) - with_dates
    with_video = sum(1 for ep in season_episodes if ep.get('has_video_file'))
    
    print(f"   Episodes with dates: {with_dates}")
    print(f"   Episodes without dates: {without_dates}")
    print(f"   Episodes with video files: {with_video}")
    
    print(f"\n📋 EPISODE LIST:")
    for ep in season_episodes:
        episode_num = ep.get('episode', '?')
        title = ep.get('title', 'Unknown')[:30] + ('...' if len(ep.get('title', '')) > 30 else '')
        dateadded = ep.get('dateadded', 'None')
        source = ep.get('source', 'None')
        video = "✅" if ep.get('has_video_file') else "❌"
        air_date = ep.get('air_date', 'None')
        
        print(f"   E{episode_num:02d}: {title:<33} | Added: {dateadded} | Air: {air_date} | Video: {video}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python debug_tv.py <imdb_id>                    # Debug entire series")
        print("  python debug_tv.py <imdb_id> <season>           # Debug specific season") 
        print("  python debug_tv.py <imdb_id> <season> <episode> # Debug specific episode")
        print("\nExamples:")
        print("  python debug_tv.py tt0121955                    # Debug South Park")
        print("  python debug_tv.py tt0121955 27                 # Debug South Park Season 27")
        print("  python debug_tv.py tt0121955 27 6               # Debug South Park S27E06")
        sys.exit(1)
    
    imdb_id = sys.argv[1]
    if not imdb_id.startswith('tt'):
        imdb_id = f'tt{imdb_id}'
    
    if len(sys.argv) == 4:
        # Debug specific episode
        season = int(sys.argv[2])
        episode = int(sys.argv[3])
        debug_episode(imdb_id, season, episode)
    elif len(sys.argv) == 3:
        # Debug specific season
        season = int(sys.argv[2])
        debug_season(imdb_id, season)
    else:
        # Debug entire series
        debug_series(imdb_id)