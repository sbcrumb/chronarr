"""
FastAPI routes for Chronarr - extracted from main chronarr.py for modular architecture
"""
import os
import json
import requests
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from fastapi import HTTPException, BackgroundTasks, Request, Response
from typing import Optional

# Import models
from api.models import (
    SonarrWebhook, RadarrWebhook, MaintainarrWebhook, HealthResponse, TVSeasonRequest, TVEpisodeRequest,
    MovieUpdateRequest, EpisodeUpdateRequest, BulkUpdateRequest
)
# Import logging utility
from utils.logging import _log
# Web routes removed - handled by separate web container

# Global scan status tracking for detailed progress
scan_status = {
    "scanning": False,
    "scan_type": None,
    "scan_mode": None,
    "start_time": None,
    "current_operation": None,
    "tv_series_processed": 0,
    "tv_series_total": 0,
    "tv_series_skipped": 0,
    "movies_processed": 0,
    "movies_total": 0,
    "movies_skipped": 0,
    "current_item": None,
    "last_update": None
}


# ---------------------------
# Helper Functions
# ---------------------------

async def _read_payload(request: Request) -> dict:
    """Read webhook payload from request"""
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            return await request.json()
        form = await request.form()
        if "payload" in form:
            return json.loads(form["payload"])
        return dict(form)
    except Exception as e:
        _log("ERROR", f"Failed to read webhook payload: {e}")
        return {}


# ---------------------------
# Route Handlers
# ---------------------------

async def sonarr_webhook(request: Request, background_tasks: BackgroundTasks, dependencies: dict):
    """Handle Sonarr webhooks"""
    tv_processor = dependencies["tv_processor"]
    batcher = dependencies["batcher"]
    config = dependencies["config"]
    
    try:
        payload = await _read_payload(request)
        if not payload:
            raise HTTPException(status_code=422, detail="Empty Sonarr payload")
        
        webhook = SonarrWebhook(**payload)
        _log("INFO", f"Received Sonarr webhook: {webhook.eventType}")
        
        if webhook.eventType not in ["Download", "Upgrade", "Rename"]:
            return {"status": "ignored", "reason": f"Event type {webhook.eventType} not processed"}
        
        if not webhook.series:
            return {"status": "ignored", "reason": "No series data"}
        
        series_info = webhook.series
        series_title = series_info.get("title", "")
        imdb_id = series_info.get("imdbId", "").replace("tt", "").strip()
        if imdb_id:
            imdb_id = f"tt{imdb_id}"
        sonarr_path = series_info.get("path", "")
        
        if not imdb_id:
            _log("ERROR", f"No IMDb ID for series: {series_title}")
            return {"status": "error", "reason": "No IMDb ID"}
        
        # Find series path
        series_path = tv_processor.find_series_path(series_title, imdb_id, sonarr_path)
        if not series_path:
            print(f"ERROR: Could not find series directory: {series_title} ({imdb_id})")
            return {"status": "error", "reason": "Series directory not found"}
        
        # Extract episode data for targeted processing
        episodes_data = webhook.episodes or []
        _log("DEBUG", f"Initial episodes_data from webhook.episodes: {len(episodes_data)} episodes")
        
        # For all webhook events, if no episodes in webhook.episodes, try to extract from episodeFile
        # This ensures targeted processing for single episode operations (Download, Rename, Upgrade)
        print(f"DEBUG: webhook.episodeFile present: {webhook.episodeFile is not None}")
        if webhook.episodeFile:
            print(f"DEBUG: episodeFile content: {webhook.episodeFile}")
        
        if not episodes_data and webhook.episodeFile:
            episode_file = webhook.episodeFile
            # Extract season and episode from episodeFile path/filename
            season_num = episode_file.get("seasonNumber")
            episode_num = episode_file.get("episodeNumber")
            
            # If not directly available, parse from relativePath or path
            if not (season_num and episode_num):
                from utils.nfo_patterns import extract_episode_info_from_filename
                
                # Try relativePath first, then path
                file_path = episode_file.get("relativePath") or episode_file.get("path", "")
                print(f"DEBUG: Parsing episode info from path: {file_path}")
                
                episode_info = extract_episode_info_from_filename(file_path)
                if episode_info:
                    season_num = episode_info["season"]
                    episode_num = episode_info["episode"]
                    print(f"DEBUG: Extracted from filename - Season: {season_num}, Episode: {episode_num}")
                else:
                    print(f"DEBUG: Could not extract season/episode from filename: {file_path}")
            
            print(f"DEBUG: episodeFile seasonNumber: {season_num}, episodeNumber: {episode_num}")
            if season_num and episode_num:
                # Create episode data structure that matches what process_webhook_episodes expects
                episodes_data = [{
                    "seasonNumber": season_num,
                    "episodeNumber": episode_num,
                    "id": episode_file.get("id"),
                    "title": episode_file.get("title")
                    # Note: Not including dateAdded - we use database-first approach with Sonarr fallback
                }]
                _log("INFO", f"Extracted episode info from episodeFile for {webhook.eventType}: S{season_num:02d}E{episode_num:02d}")
            else:
                print(f"DEBUG: Missing season/episode numbers in episodeFile for {webhook.eventType}")
        
        # Special handling for Rename events - Sonarr doesn't include episodeFile for renames
        # Try to find recently renamed episodes using Sonarr history API
        if not episodes_data and webhook.eventType == "Rename":
            print(f"DEBUG: Attempting to find recently renamed episode for series {imdb_id}")
            try:
                # Get series info from Sonarr to find series ID
                series_lookup_url = f"{config.sonarr_url}/api/v3/series/lookup?term=imdbid:{imdb_id}"
                print(f"DEBUG: Sonarr lookup for rename: {series_lookup_url}")
                
                response = requests.get(series_lookup_url, headers={"X-Api-Key": os.environ.get("SONARR_API_KEY", "")}, timeout=10)
                if response.status_code == 200:
                    series_results = response.json()
                    if series_results:
                        series_id = series_results[0].get("id")
                        print(f"DEBUG: Found series ID {series_id} for rename lookup")
                        
                        # Get recent history for the series and filter for rename events
                        from datetime import datetime, timedelta
                        since_date = (datetime.utcnow() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                        history_url = f"{config.sonarr_url}/api/v3/history?seriesId={series_id}&sortKey=date&sortDir=desc&page=1&pageSize=50"
                        print(f"DEBUG: Checking recent rename history: {history_url}")
                        
                        history_response = requests.get(history_url, headers={"X-Api-Key": os.environ.get("SONARR_API_KEY", "")}, timeout=10)
                        if history_response.status_code == 200:
                            history_data = history_response.json()
                            all_records = history_data.get("records", [])
                            print(f"DEBUG: Got {len(all_records)} total history records")
                            
                            # Filter for recent rename events
                            since_timestamp = datetime.utcnow() - timedelta(hours=1)
                            recent_renames = []
                            
                            for record in all_records:
                                event_type = record.get("eventType", "")
                                date_str = record.get("date", "")
                                
                                if event_type == "episodeFileRenamed" and date_str:
                                    try:
                                        event_time = datetime.strptime(date_str.replace('Z', '+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z')
                                        event_time_utc = event_time.utctimetuple()
                                        if datetime(*event_time_utc[:6]) > since_timestamp:
                                            recent_renames.append(record)
                                    except:
                                        # If datetime parsing fails, include it anyway
                                        recent_renames.append(record)
                            
                            print(f"DEBUG: Found {len(recent_renames)} recent rename events")
                            
                            if recent_renames:
                                # Take the most recent rename event
                                latest_rename = recent_renames[0]
                                print(f"DEBUG: Processing latest rename event")
                                
                                # Extract episodeId directly from the rename event
                                episode_id = latest_rename.get("episodeId")
                                print(f"DEBUG: Found episodeId {episode_id} in rename event")
                                
                                if episode_id:
                                    # Fetch episode details using the episodeId
                                    episode_detail_url = f"{config.sonarr_url}/api/v3/episode/{episode_id}"
                                    episode_response = requests.get(episode_detail_url, headers={"X-Api-Key": os.environ.get("SONARR_API_KEY", "")}, timeout=10)
                                    
                                    if episode_response.status_code == 200:
                                        episode_detail = episode_response.json()
                                        season_num = episode_detail.get("seasonNumber")
                                        episode_num = episode_detail.get("episodeNumber")
                                        episode_title = episode_detail.get("title")
                                        
                                        print(f"DEBUG: Episode details - Season: {season_num}, Episode: {episode_num}, Title: {episode_title}")
                                        
                                        if season_num is not None and episode_num is not None:
                                            episodes_data = [{
                                                "seasonNumber": season_num,
                                                "episodeNumber": episode_num,
                                                "id": episode_id,
                                                "title": episode_title
                                            }]
                                            print(f"INFO: Successfully identified renamed episode: S{season_num:02d}E{episode_num:02d} - {episode_title}")
                                        else:
                                            print(f"DEBUG: Episode details missing season/episode numbers")
                                    else:
                                        print(f"DEBUG: Failed to fetch episode details: {episode_response.status_code}")
                                else:
                                    print(f"DEBUG: No episodeId found in rename event")
                            else:
                                print(f"DEBUG: No recent rename events found in last hour")
                        else:
                            print(f"DEBUG: Failed to get rename history: {history_response.status_code}")
                    else:
                        print(f"DEBUG: No series found for IMDb {imdb_id}")
                else:
                    print(f"DEBUG: Series lookup failed: {response.status_code}")
            except Exception as e:
                print(f"DEBUG: Error finding renamed episode: {e}")
                # Continue with series processing as fallback
        
        # Force targeted mode for single-episode webhooks to prevent full series processing
        processing_mode = config.tv_webhook_processing_mode
        if episodes_data and len(episodes_data) <= 3:  # Single episode or small batch
            processing_mode = "targeted"
            _log("INFO", f"Forcing targeted mode for {len(episodes_data)} episode(s)")
        
        # Add to batch queue with TV-prefixed key to avoid movie conflicts
        tv_batch_key = f"tv:{imdb_id}"
        webhook_dict = {
            'path': str(series_path),
            'series_info': series_info,
            'event_type': webhook.eventType,
            'episodes': episodes_data,  # Include enhanced episode data for targeted processing
            'processing_mode': processing_mode  # Use forced targeted mode when appropriate
        }
        batcher.add_webhook(tv_batch_key, webhook_dict, 'tv')
        
        return {"status": "accepted", "message": f"Sonarr webhook queued for {tv_batch_key}"}
        
    except Exception as e:
        _log("ERROR", f"Sonarr webhook error: {e}")
        raise HTTPException(status_code=422, detail=f"Invalid webhook: {e}")


async def radarr_webhook(request: Request, background_tasks: BackgroundTasks, dependencies: dict):
    """Handle Radarr webhooks"""
    path_mapper = dependencies["path_mapper"]
    batcher = dependencies["batcher"]
    
    try:
        payload = await _read_payload(request)
        _log("INFO", f"Received Radarr webhook: {payload.get('eventType', 'Unknown')}")
        _log("DEBUG", f"Full Radarr webhook payload: {payload}")
        
        # Filter supported event types (same as Sonarr: Download, Upgrade, Rename)
        event_type = payload.get('eventType', '')
        if event_type not in ["Download", "Upgrade", "Rename"]:
            return {"status": "ignored", "reason": f"Event type {event_type} not processed"}
        
        # Extract movie info
        movie_data = payload.get("movie", {})
        if not movie_data:
            _log("WARNING", "No movie data in Radarr webhook")
            return {"status": "error", "message": "No movie data"}
        
        # Get IMDb ID for batching key
        imdb_id = movie_data.get("imdbId", "").lower()
        if not imdb_id:
            _log("WARNING", "No IMDb ID in Radarr webhook movie data")
            return {"status": "error", "message": "No IMDb ID"}
        
        # Get movie path and map it
        movie_path = movie_data.get("folderPath") or movie_data.get("path", "")
        if not movie_path:
            _log("ERROR", "No movie path in Radarr webhook")
            return {"status": "error", "message": "No movie path provided"}
        
        # Map the path to container path
        container_path = path_mapper.radarr_path_to_container_path(movie_path)
        _log("DEBUG", f"Mapped Radarr path {movie_path} -> {container_path}")
        
        # CRITICAL: Verify the mapped path actually exists
        if not Path(container_path).exists():
            _log("ERROR", f"RADARR WEBHOOK REJECTED: Mapped path does not exist: {container_path}")
            _log("ERROR", "This prevents processing wrong movies due to path mapping issues")
            return {"status": "error", "message": f"Mapped movie path does not exist: {container_path}"}
        
        # Verify the path contains the expected IMDb ID
        if imdb_id not in container_path.lower():
            print(f"WARNING: IMDb ID {imdb_id} not found in container path {container_path}")
        
        # Create movie-specific webhook data with proper path validation
        movie_webhook_data = {
            'path': container_path,  # Use verified container path
            'movie_info': movie_data,
            'event_type': payload.get('eventType'),
            'original_payload': payload
        }
        
        # Add to batch queue with movie-prefixed key to avoid TV conflicts
        movie_batch_key = f"movie:{imdb_id}"
        _log("DEBUG", f"Adding Radarr webhook to batch: key={movie_batch_key}, movie_title={movie_data.get('title', 'Unknown')}")
        batcher.add_webhook(movie_batch_key, movie_webhook_data, "movie")
        
        return {"status": "success", "message": f"Radarr webhook queued for {movie_batch_key}"}
        
    except Exception as e:
        _log("ERROR", f"Radarr webhook error: {e}")
        return {"status": "error", "message": str(e)}


async def maintainarr_webhook(request: Request, background_tasks: BackgroundTasks, dependencies: dict):
    """Handle Maintainarr webhooks for media deletion"""
    db = dependencies["db"]
    config = dependencies["config"]
    
    try:
        payload = await _read_payload(request)
        if not payload:
            raise HTTPException(status_code=422, detail="Empty Maintainarr payload")
        
        webhook = MaintainarrWebhook(**payload)
        _log("INFO", f"Received Maintainarr webhook: {webhook.notification_type}")
        _log("DEBUG", f"Full Maintainarr webhook payload: {payload}")
        
        # Handle test notifications differently for debugging
        notification_type = webhook.notification_type or ""
        if notification_type == "TEST_NOTIFICATION":
            return {
                "status": "test_received", 
                "message": "Test notification received successfully",
                "available_fields": {
                    "notification_type": webhook.notification_type,
                    "subject": webhook.subject,
                    "message": webhook.message,
                    "extra": webhook.extra
                },
                "debug": "This is a test notification. Real media removal events will be processed when they occur."
            }
        
        # Only process media removal notifications
        if "removed" not in notification_type.lower() and "delete" not in notification_type.lower():
            return {"status": "ignored", "reason": f"Notification type '{notification_type}' not processed"}
        
        # Parse message to extract media information
        message = webhook.message or ""
        subject = webhook.subject or ""
        extra = webhook.extra or ""
        
        # Try to extract IMDb ID from message, subject, or extra data
        import re
        imdb_pattern = r'tt\d{7,8}|\b\d{7,8}\b'
        
        imdb_id = None
        title = "Unknown Media"
        media_type = "Unknown"
        
        # Look for IMDb ID in all fields
        for field in [message, subject, extra]:
            if field:
                imdb_matches = re.findall(imdb_pattern, field)
                if imdb_matches:
                    imdb_id = imdb_matches[0]
                    if not imdb_id.startswith("tt"):
                        imdb_id = f"tt{imdb_id}"
                    break
        
        if not imdb_id:
            _log("WARNING", f"No IMDb ID found in Maintainarr webhook - Message: '{message}', Subject: '{subject}'")
            return {"status": "ignored", "reason": "No IMDb ID found in webhook payload"}
        
        # Try to extract title from subject or message
        if subject and subject.strip():
            title = subject.strip()
        elif message and message.strip():
            # Extract title from message if possible
            title_match = re.search(r'(?:movie|series|show)\s*[:\-]?\s*(.+?)(?:\s*\(|$)', message, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
            else:
                title = message.strip()
        
        # Try to determine media type from message content
        if any(word in message.lower() for word in ["series", "show", "tv", "season", "episode"]):
            media_type = "Series"
        elif any(word in message.lower() for word in ["movie", "film"]):
            media_type = "Movie"
        else:
            # Try both types - first check if it's a series, then movie
            series = db.get_series_by_imdb(imdb_id)
            movie = db.get_movie_by_imdb(imdb_id)
            
            if series:
                media_type = "Series"
            elif movie:
                media_type = "Movie"
            else:
                _log("INFO", f"Media {title} ({imdb_id}) not found in database")
                return {"status": "ignored", "reason": f"Media {imdb_id} not found in database"}
        
        # Process deletion based on media type
        removed_count = 0
        removed_items = []
        
        if media_type == "Movie":
            _log("INFO", f"Processing movie deletion for {title} ({imdb_id})")
            
            # Check if movie exists in database
            movie = db.get_movie_by_imdb(imdb_id)
            if movie:
                if db.delete_movie(imdb_id):
                    removed_count += 1
                    removed_items.append(f"Movie: {title} ({imdb_id})")
                    _log("INFO", f"SUCCESS: Removed movie {title} ({imdb_id}) from database")
                else:
                    _log("WARNING", f"Failed to remove movie {title} ({imdb_id}) from database")
            else:
                _log("INFO", f"Movie {title} ({imdb_id}) not found in database")
        
        elif media_type == "Series":
            _log("INFO", f"Processing series deletion for {title} ({imdb_id})")
            
            # Check if series exists in database
            series = db.get_series_by_imdb(imdb_id)
            if series:
                # Delete all episodes for the series
                episodes_removed = db.delete_series_episodes(imdb_id)
                if episodes_removed > 0:
                    removed_count += episodes_removed
                    removed_items.append(f"Series episodes: {title} ({imdb_id}) - {episodes_removed} episodes")
                    print(f"SUCCESS: Removed {episodes_removed} episodes for series {title} ({imdb_id})")
                
                # Delete the series record
                if db.delete_series(imdb_id):
                    removed_count += 1
                    removed_items.append(f"Series: {title} ({imdb_id})")
                    _log("INFO", f"SUCCESS: Removed series {title} ({imdb_id}) from database")
                else:
                    _log("WARNING", f"Failed to remove series {title} ({imdb_id}) from database")
            else:
                _log("INFO", f"Series {title} ({imdb_id}) not found in database")
        
        # Log the cleanup operation
        if removed_count > 0:
            background_tasks.add_task(
                _log_maintainarr_cleanup,
                notification_type,
                media_type,
                title,
                imdb_id,
                removed_items,
                webhook.subject
            )
        
        return {
            "status": "success",
            "message": f"Processed {notification_type} for {title}",
            "media_type": media_type,
            "imdb_id": imdb_id,
            "removed_count": removed_count,
            "removed_items": removed_items
        }
        
    except Exception as e:
        _log("ERROR", f"Maintainarr webhook error: {e}")
        import traceback
        _log("ERROR", f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


async def _log_maintainarr_cleanup(event_type: str, media_type: str, title: str, imdb_id: str, removed_items: list, collection_name: str = None):
    """Background task to log Maintainarr cleanup operations"""
    try:
        log_message = f"Maintainarr cleanup: {event_type} - {media_type} '{title}' ({imdb_id})"
        if collection_name:
            log_message += f" from collection '{collection_name}'"
        log_message += f". Removed from database: {', '.join(removed_items)}"
        
        _log("INFO", log_message)
        
        # Could extend this to write to a cleanup log file or database table
        
    except Exception as e:
        print(f"ERROR: Failed to log Maintainarr cleanup: {e}")


async def health(dependencies: dict) -> HealthResponse:
    """Health check endpoint with Radarr database status"""
    db = dependencies["db"]
    movie_processor = dependencies["movie_processor"]
    start_time = dependencies["start_time"]
    version = dependencies["version"]
    
    uptime = datetime.now(timezone.utc) - start_time
    
    # Check Chronarr database
    try:
        with db.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {e}"
    
    # Check Radarr database if available
    radarr_db_health = None
    overall_status = "healthy" if db_status == "healthy" else "degraded"
    
    # Get Radarr client with database access from movie processor
    try:
        if hasattr(movie_processor, 'radarr') and movie_processor.radarr:
            radarr_client = movie_processor.radarr
            if hasattr(radarr_client, 'db_client') and radarr_client.db_client:
                try:
                    radarr_db_health = radarr_client.db_client.health_check()
                    if radarr_db_health["status"] != "healthy":
                        overall_status = "degraded"
                except Exception as e:
                    radarr_db_health = {
                        "status": "error",
                        "error": str(e),
                        "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                    }
                    overall_status = "degraded"
    except Exception as e:
        # If movie processor isn't available, skip database health check
        print(f"DEBUG: Skipping Radarr database health check: {e}")
    
    return HealthResponse(
        status=overall_status,
        version=version,
        uptime=str(uptime),
        database_status=db_status,
        radarr_database=radarr_db_health
    )


async def get_stats(dependencies: dict):
    """Get database statistics"""
    db = dependencies["db"]
    try:
        return db.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def batch_status(dependencies: dict):
    """Get batch queue status"""
    batcher = dependencies["batcher"]
    return batcher.get_status()


async def debug_movie_import_date(imdb_id: str, dependencies: dict):
    """Debug endpoint to analyze movie import date detection"""
    movie_processor = dependencies["movie_processor"]
    
    try:
        if not imdb_id.startswith("tt"):
            imdb_id = f"tt{imdb_id}"
            
        print(f"INFO: === DEBUG MOVIE IMPORT DATE: {imdb_id} ===")
        
        if not (os.environ.get("RADARR_URL") and os.environ.get("RADARR_API_KEY")):
            return {
                "error": "Radarr not configured", 
                "imdb_id": imdb_id,
                "radarr_configured": False
            }
        
        # Create Radarr client
        from clients.radarr_client import RadarrClient
        radarr_client = RadarrClient(
            os.environ.get("RADARR_URL"),
            os.environ.get("RADARR_API_KEY")
        )
        
        # Look up movie
        movie_obj = radarr_client.movie_by_imdb(imdb_id)
        if not movie_obj:
            return {
                "error": f"Movie not found in Radarr for IMDb ID {imdb_id}",
                "imdb_id": imdb_id,
                "radarr_configured": True,
                "movie_found": False
            }
            
        movie_id = movie_obj.get("id")
        movie_title = movie_obj.get("title")
        
        print(f"INFO: Found movie: {movie_title} (Radarr ID: {movie_id})")
        
        # Test the FULL movie processing pipeline (not just database lookup)
        print(f"INFO: === TESTING FULL MOVIE PROCESSING PIPELINE ===")
        
        # Create a dummy path for testing the decision logic
        dummy_path = Path("/tmp/test")
        
        try:
            # Use the global movie processor instance to test full decision logic
            if movie_processor:
                # First check external clients configuration
                print(f"INFO: === CHECKING EXTERNAL CLIENTS CONFIG ===")
                try:
                    tmdb_key = os.environ.get("TMDB_API_KEY", "")
                    print(f"INFO: TMDB API Key configured: {'✅ YES' if tmdb_key else '❌ NO'}")
                    if tmdb_key:
                        print(f"INFO: TMDB API Key length: {len(tmdb_key)} chars")
                    
                    # Check if external clients exist
                    external_clients_available = hasattr(movie_processor, 'external_clients') and movie_processor.external_clients
                    print(f"INFO: External clients initialized: {'✅ YES' if external_clients_available else '❌ NO'}")
                    
                except Exception as e:
                    print(f"ERROR: Error checking external clients config: {e}")
                
                # Test the full decision logic (including TMDB fallback)
                final_date, final_source, released = movie_processor._decide_movie_dates(
                    imdb_id, dummy_path, should_query=True, existing=None
                )
                
                print(f"INFO: === FULL PIPELINE RESULT ===")
                print(f"INFO: Final date: {final_date}")
                print(f"INFO: Final source: {final_source}")
                print(f"INFO: Released (theater): {released}")
                
                return {
                    "imdb_id": imdb_id,
                    "radarr_configured": True,
                    "movie_found": True,
                    "movie_title": movie_title,
                    "movie_id": movie_id,
                    "full_pipeline_test": {
                        "final_date": final_date,
                        "final_source": final_source,
                        "theater_release": released,
                        "decision_logic": "✅ TESTED FULL PIPELINE INCLUDING TMDB FALLBACK"
                    },
                    "database_only_test": {
                        "radarr_db_result": radarr_client.get_movie_import_date(movie_id, fallback_to_file_date=True),
                        "note": "This is just the database part - fallback happens in full pipeline"
                    },
                    "debug_info": {
                        "radarr_url": os.environ.get("RADARR_URL"),
                        "movie_digital_release": movie_obj.get("digitalRelease"),
                        "movie_in_cinemas": movie_obj.get("inCinemas"),
                        "movie_physical_release": movie_obj.get("physicalRelease"),
                        "movie_folder_path": movie_obj.get("folderPath")
                    }
                }
            else:
                print("ERROR: Movie processor not available - testing database only")
                # Fallback to database-only testing
                import_date, source = radarr_client.get_movie_import_date(movie_id, fallback_to_file_date=True)
                return {
                    "error": "Movie processor not available - only database test performed",
                    "imdb_id": imdb_id,
                    "radarr_configured": True,
                    "movie_found": True,
                    "movie_title": movie_title,
                    "movie_id": movie_id,
                    "detected_import_date": import_date,
                    "import_source": source,
                    "debug_info": {
                        "note": "FULL PIPELINE TEST FAILED - movie processor not initialized"
                    }
                }
                
        except Exception as pipeline_error:
            print(f"ERROR: Full pipeline test failed: {pipeline_error}")
            # Fallback to database-only testing
            import_date, source = radarr_client.get_movie_import_date(movie_id, fallback_to_file_date=True)
            return {
                "pipeline_error": str(pipeline_error),
                "imdb_id": imdb_id,
                "radarr_configured": True,
                "movie_found": True,
                "movie_title": movie_title,
                "movie_id": movie_id,
                "detected_import_date": import_date,
                "import_source": source,
                "debug_info": {
                    "note": "FULL PIPELINE TEST FAILED - showing database-only result"
                }
            }
        
    except Exception as e:
        print(f"ERROR: Debug endpoint error for {imdb_id}: {e}")
        return {
            "error": str(e),
            "imdb_id": imdb_id,
            "success": False
        }


async def debug_movie_history(imdb_id: str, dependencies: dict):
    """Detailed history analysis for a movie"""
    movie_processor = dependencies["movie_processor"]
    
    try:
        if not imdb_id.startswith("tt"):
            imdb_id = f"tt{imdb_id}"
            
        print(f"INFO: === DETAILED HISTORY ANALYSIS: {imdb_id} ===")
        
        # This would need the rest of the implementation from the original function
        # For now, returning a placeholder
        return {
            "imdb_id": imdb_id,
            "message": "History analysis endpoint - implementation needed"
        }
        
    except Exception as e:
        print(f"ERROR: Debug history endpoint error for {imdb_id}: {e}")
        return {
            "error": str(e),
            "imdb_id": imdb_id,
            "success": False
        }


async def manual_scan(background_tasks: BackgroundTasks, path: Optional[str] = None, scan_type: str = "both", scan_mode: str = "smart", dependencies: dict = None):
    """Manual scan endpoint with smart optimization modes"""
    config = dependencies["config"]
    nfo_manager = dependencies["nfo_manager"]
    tv_processor = dependencies["tv_processor"]
    movie_processor = dependencies["movie_processor"]
    
    if scan_type not in ["both", "tv", "movies"]:
        raise HTTPException(status_code=400, detail="scan_type must be 'both', 'tv', or 'movies'")
    
    if scan_mode not in ["smart", "full", "incomplete"]:
        raise HTTPException(status_code=400, detail="scan_mode must be 'smart', 'full', or 'incomplete'")
    
    async def run_scan():
        from datetime import datetime, timezone
        import time
        import os
        start_time = datetime.now()
        
        # Handle timezone display - check if TZ is set in container
        try:
            tz_name = os.environ.get('TZ')
            if tz_name:
                # TZ is set, so datetime.now() already returns local time
                local_start = start_time
                tz_display = f" ({tz_name})"
            else:
                # No TZ set, assume container is UTC and convert to Eastern
                import zoneinfo
                local_tz = zoneinfo.ZoneInfo("America/New_York")
                local_start = start_time.replace(tzinfo=timezone.utc).astimezone(local_tz)
                tz_display = " (EDT/EST)"
        except:
            # Ultimate fallback - just show time as-is with note
            local_start = start_time
            tz_display = " (container time)"
            
        print(f"🚀 MANUAL SCAN STARTED: {scan_type} scan (mode: {scan_mode}) initiated at {local_start.strftime('%Y-%m-%d %H:%M:%S')}{tz_display}")
        
        # Initialize scan tracking
        start_scan_tracking(scan_type, scan_mode)
        
        # Initialize counters for scan statistics
        tv_series_total = 0
        tv_series_skipped = 0
        tv_series_processed = 0
        movie_total = 0
        movie_skipped = 0
        movie_processed = 0
        
        def translate_host_path_to_container(path_str):
            """Translate host paths to container paths for Docker volume mounts"""
            path_str = str(path_str)
            # Handle the common Docker volume mount: /mnt/unionfs/Media/ -> /media/
            if path_str.startswith('/mnt/unionfs/Media/'):
                container_path = path_str.replace('/mnt/unionfs/Media/', '/media/')
                print(f"DEBUG: Translated host path '{path_str}' to container path '{container_path}'")
                return container_path
            # Handle case where user enters /Media/ instead of /media/ (case sensitivity)
            elif path_str.startswith('/Media/'):
                container_path = path_str.replace('/Media/', '/media/')
                print(f"DEBUG: Fixed case sensitivity '{path_str}' to container path '{container_path}'")
                return container_path
            return path_str
        
        paths_to_scan = []
        if path:
            # Translate the provided path from host format to container format
            translated_path = translate_host_path_to_container(path)
            paths_to_scan = [Path(translated_path)]
            print(f"DEBUG: Manual scan with specific path: {path} -> {translated_path}")
        else:
            if scan_type in ["both", "tv"]:
                paths_to_scan.extend(config.tv_paths)
            if scan_type in ["both", "movies"]:  
                paths_to_scan.extend(config.movie_paths)
        
        for scan_path in paths_to_scan:
            print(f"DEBUG: Checking scan_path: {scan_path}, exists: {scan_path.exists()}")
            if not scan_path.exists():
                print(f"DEBUG: Path does not exist, skipping: {scan_path}")
                continue
                
            print(f"DEBUG: scan_type={scan_type}, path={path}, scan_path in tv_paths: {scan_path in config.tv_paths}")
            if scan_type in ["both", "tv"] and (scan_path in config.tv_paths or path):
                # Handle specific season/episode path
                print(f"DEBUG: Entered TV processing branch")
                if path and scan_path.name.lower().startswith('season'):
                    print(f"DEBUG: Taking season processing path")
                    # Single season processing
                    series_path = scan_path.parent
                    tv_processor_obj = dependencies.get("tv_processor")
                    sonarr_client = tv_processor_obj.sonarr if tv_processor_obj and hasattr(tv_processor_obj, 'sonarr') else None
                    shutdown_event = dependencies.get("shutdown_event")
                    if nfo_manager.parse_imdb_from_path_with_nfo_fallback(series_path, sonarr_client, shutdown_event):
                        print(f"INFO: Processing single season: {scan_path}")
                        try:
                            tv_processor.process_season(series_path, scan_path)
                        except Exception as e:
                            print(f"ERROR: Failed processing season {scan_path}: {e}")
                elif path and scan_path.is_file() and scan_path.suffix.lower() in ('.mkv', '.mp4', '.avi'):
                    print(f"DEBUG: Taking single episode processing path")
                    # Single episode processing
                    season_path = scan_path.parent
                    series_path = season_path.parent
                    tv_processor_obj = dependencies.get("tv_processor")
                    sonarr_client = tv_processor_obj.sonarr if tv_processor_obj and hasattr(tv_processor_obj, 'sonarr') else None
                    shutdown_event = dependencies.get("shutdown_event")
                    if nfo_manager.parse_imdb_from_path_with_nfo_fallback(series_path, sonarr_client, shutdown_event):
                        print(f"INFO: Processing single episode: {scan_path}")
                        try:
                            tv_processor.process_episode_file(series_path, season_path, scan_path)
                        except Exception as e:
                            print(f"ERROR: Failed processing episode {scan_path}: {e}")
                else:
                    print(f"DEBUG: Taking series processing path")
                    # Check if this path itself is a series (has IMDb ID in directory name or NFO files)
                    tv_processor_obj = dependencies.get("tv_processor")
                    sonarr_client = tv_processor_obj.sonarr if tv_processor_obj and hasattr(tv_processor_obj, 'sonarr') else None
                    shutdown_event = dependencies.get("shutdown_event")
                    imdb_id = nfo_manager.parse_imdb_from_path_with_nfo_fallback(scan_path, sonarr_client, shutdown_event)
                    print(f"DEBUG: Manual scan IMDb detection for {scan_path}: {imdb_id}")
                    if imdb_id:
                        try:
                            # Determine force_scan based on scan mode
                            force_scan = (scan_mode == "full")
                            print(f"DEBUG: Processing series {scan_path} with force_scan={force_scan}, scan_mode={scan_mode}")
                            result = tv_processor.process_series(scan_path, force_scan=force_scan, scan_mode=scan_mode)
                            tv_series_total += 1
                            if result == "skipped":
                                tv_series_skipped += 1
                            elif result == "processed":
                                tv_series_processed += 1
                        except Exception as e:
                            print(f"ERROR: Failed processing TV series {scan_path}: {e}")
                            tv_series_total += 1
                    else:
                        # Full series processing - scan subdirectories
                        import re
                        
                        # Count total series first for progress tracking
                        tv_series_list = []
                        for item in scan_path.iterdir():
                            # Check for shutdown signal during series discovery
                            shutdown_event = dependencies.get("shutdown_event")
                            if shutdown_event and shutdown_event.is_set():
                                print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping series discovery")
                                return
                                
                            if (item.is_dir() and 
                                not item.name.lower().startswith('season') and
                                not re.match(r'^season\s+\d+$', item.name, re.IGNORECASE)):
                                
                                # Check for IMDb ID (enhanced with NFO fallback)
                                tv_processor_obj = dependencies.get("tv_processor")
                                sonarr_client = tv_processor_obj.sonarr if tv_processor_obj and hasattr(tv_processor_obj, 'sonarr') else None
                                imdb_id = nfo_manager.parse_imdb_from_path_with_nfo_fallback(item, sonarr_client, shutdown_event)
                                if imdb_id:
                                    tv_series_list.append(item)
                                else:
                                    # Log missing IMDb ID for TV series
                                    try:
                                        db = dependencies.get("db")
                                        db.add_missing_imdb(
                                            file_path=str(item),
                                            media_type="tv",
                                            folder_name=item.name,
                                            filename=None,
                                            notes=f"TV series directory without IMDb ID detected during scan"
                                        )
                                        print(f"⚠️ Missing IMDb ID: TV series {item.name} - logged for manual review")
                                    except Exception as e:
                                        print(f"❌ Failed to log missing IMDb for TV series {item.name}: {e}")
                        
                        tv_series_count = len(tv_series_list)
                        update_scan_status("tv", tv_series_total=tv_series_count)
                        print(f"INFO: Found {tv_series_count} TV series to process")
                        
                        tv_count = 0
                        for item in tv_series_list:
                            # Check for shutdown signal at start of each item
                            shutdown_event = dependencies.get("shutdown_event")
                            if shutdown_event and shutdown_event.is_set():
                                print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping scan gracefully")
                                return
                                
                            tv_count += 1
                            update_scan_status(current_item=item.name, tv_series_processed=tv_count)
                            
                            try:
                                # Determine force_scan based on scan mode
                                force_scan = (scan_mode == "full")
                                result = tv_processor.process_series(item, force_scan=force_scan, scan_mode=scan_mode)
                                tv_series_total += 1
                                if result == "skipped":
                                    tv_series_skipped += 1
                                elif result == "processed":
                                    tv_series_processed += 1
                            except Exception as e:
                                print(f"ERROR: Failed processing TV series {item}: {e}")
                                tv_series_total += 1
                            
                            # Yield control every TV series to allow other requests  
                            if tv_count % 1 == 0:
                                await asyncio.sleep(0.2)  # 200ms yield to process other requests
                                print(f"INFO: Processed {tv_count} TV series, yielding to other requests...")
                                
                                # Check for shutdown signal
                                shutdown_event = dependencies.get("shutdown_event")
                                if shutdown_event and shutdown_event.is_set():
                                    print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping scan gracefully")
                                    return
            
            if scan_type in ["both", "movies"] and scan_path in config.movie_paths:
                print(f"INFO: Scanning movies in: {scan_path}")
                update_scan_status("movies", current_item="Counting movies...")
                
                # Count total movies first for progress tracking
                movie_list = []
                for item in scan_path.iterdir():
                    # Check for shutdown signal during movie discovery
                    shutdown_event = dependencies.get("shutdown_event")
                    if shutdown_event and shutdown_event.is_set():
                        print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping movie discovery")
                        return
                        
                    if item.is_dir():
                        # Check for IMDb ID
                        imdb_id = nfo_manager.find_movie_imdb_id(item)
                        if imdb_id:
                            movie_list.append(item)
                        else:
                            # Log missing IMDb ID for movie
                            try:
                                db = dependencies.get("db")
                                db.add_missing_imdb(
                                    file_path=str(item),
                                    media_type="movie",
                                    folder_name=item.name,
                                    filename=None,
                                    notes=f"Movie directory without IMDb ID detected during scan"
                                )
                                print(f"⚠️ Missing IMDb ID: Movie {item.name} - logged for manual review")
                            except Exception as e:
                                print(f"❌ Failed to log missing IMDb for movie {item.name}: {e}")
                
                movie_total_count = len(movie_list)
                update_scan_status(movies_total=movie_total_count)
                print(f"INFO: Found {movie_total_count} movies to process")
                
                movie_count = 0
                for item in movie_list:
                    # Check for shutdown signal at start of each movie
                    shutdown_event = dependencies.get("shutdown_event")
                    if shutdown_event and shutdown_event.is_set():
                        print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping scan gracefully")
                        return
                        
                    movie_count += 1
                    update_scan_status(current_item=item.name, movies_processed=movie_count)
                    print(f"INFO: Processing movie: {item.name}")
                    try:
                        # Determine force_scan based on scan mode
                        force_scan = (scan_mode == "full")
                        shutdown_event = dependencies.get("shutdown_event")
                        result = movie_processor.process_movie(item, webhook_mode=False, force_scan=force_scan, scan_mode=scan_mode, shutdown_event=shutdown_event)
                        movie_total += 1
                        if result == "skipped":
                            movie_skipped += 1
                        elif result == "processed":
                            movie_processed += 1
                        elif result == "no_video_files":
                            print(f"INFO: Skipped empty directory: {item.name}")
                            movie_skipped += 1
                        elif result == "shutdown":
                            print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping movie scan gracefully")
                            return
                    except Exception as e:
                        print(f"ERROR: Failed processing movie {item}: {e}")
                        movie_total += 1
                    
                    # Yield control every 2 movies to allow other requests (webhooks, web interface)
                    if movie_count % 2 == 0:
                        await asyncio.sleep(0.2)  # 200ms yield to process other requests
                        print(f"INFO: Processed {movie_count} movies, yielding to other requests...")
                        
                        # Check for shutdown signal
                        shutdown_event = dependencies.get("shutdown_event")
                        if shutdown_event and shutdown_event.is_set():
                            print("INFO: ⚠️ SHUTDOWN SIGNAL RECEIVED - Stopping scan gracefully")
                            return
                        
                print(f"INFO: Completed movie scan: {movie_count} movies processed in {scan_path}")
        
        # Log scan completion with duration
        end_time = datetime.now()
        duration = end_time - start_time
        duration_str = str(duration).split('.')[0]  # Remove microseconds
        
        # Use same timezone logic as start
        try:
            tz_name = os.environ.get('TZ')
            if tz_name:
                # TZ is set, so datetime.now() already returns local time
                local_end = end_time
                tz_display = f" ({tz_name})"
            else:
                # No TZ set, assume container is UTC and convert to Eastern
                import zoneinfo
                local_tz = zoneinfo.ZoneInfo("America/New_York")
                local_end = end_time.replace(tzinfo=timezone.utc).astimezone(local_tz)
                tz_display = " (EDT/EST)"
        except:
            local_end = end_time
            tz_display = " (container time)"
            
        print(f"✅ MANUAL SCAN COMPLETED: {scan_type} scan (mode: {scan_mode}) finished at {local_end.strftime('%Y-%m-%d %H:%M:%S')}{tz_display}")
        print(f"⏱️ MANUAL SCAN DURATION: {duration_str} (total time: {duration.total_seconds():.1f} seconds)")
        
        # Stop scan tracking
        stop_scan_tracking()
        
        # Print optimization statistics for TV scans
        if scan_type in ["both", "tv"] and tv_series_total > 0:
            print(f"📊 TV SCAN OPTIMIZATION: Total: {tv_series_total}, Processed: {tv_series_processed}, Skipped: {tv_series_skipped}")
            if tv_series_skipped > 0:
                skip_percentage = (tv_series_skipped / tv_series_total) * 100
                print(f"⚡ TV PERFORMANCE BOOST: {tv_series_skipped}/{tv_series_total} series skipped ({skip_percentage:.1f}% time saved!)")
        
        # Print optimization statistics for movie scans
        if scan_type in ["both", "movies"] and movie_total > 0:
            print(f"📊 MOVIE SCAN OPTIMIZATION: Total: {movie_total}, Processed: {movie_processed}, Skipped: {movie_skipped}")
            if movie_skipped > 0:
                skip_percentage = (movie_skipped / movie_total) * 100
                print(f"⚡ MOVIE PERFORMANCE BOOST: {movie_skipped}/{movie_total} movies skipped ({skip_percentage:.1f}% time saved!)")
        
        # Print combined optimization statistics for "both" scans
        if scan_type == "both" and (tv_series_total > 0 or movie_total > 0):
            total_items = tv_series_total + movie_total
            total_skipped = tv_series_skipped + movie_skipped
            total_processed = tv_series_processed + movie_processed
            if total_skipped > 0:
                overall_skip_percentage = (total_skipped / total_items) * 100
                print(f"🎯 OVERALL OPTIMIZATION: {total_skipped}/{total_items} items skipped ({overall_skip_percentage:.1f}% total time saved!)")
    
    background_tasks.add_task(run_scan)
    return {"status": "started", "message": f"Manual {scan_type} scan started (mode: {scan_mode})"}


async def scan_tv_season(background_tasks: BackgroundTasks, request: TVSeasonRequest, dependencies: dict):
    """Scan a specific TV season - URL-safe endpoint"""
    nfo_manager = dependencies["nfo_manager"]
    tv_processor = dependencies["tv_processor"]
    
    try:
        series_dir = Path(request.series_path)
        season_dir = series_dir / request.season_name
        
        if not series_dir.exists():
            raise HTTPException(status_code=404, detail=f"Series path not found: {request.series_path}")
        if not season_dir.exists():
            raise HTTPException(status_code=404, detail=f"Season path not found: {season_dir}")
        
        imdb_id = nfo_manager.parse_imdb_from_path(series_dir)
        if not imdb_id:
            raise HTTPException(status_code=400, detail="No IMDb ID found in series path")
        
        async def process_season():
            print(f"INFO: Processing TV season: {season_dir}")
            try:
                tv_processor.process_season(series_dir, season_dir)
            except Exception as e:
                print(f"ERROR: Failed processing season {season_dir}: {e}")
        
        background_tasks.add_task(process_season)
        return {"status": "started", "message": f"Season scan started for {request.season_name}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def scan_tv_episode(background_tasks: BackgroundTasks, request: TVEpisodeRequest, dependencies: dict):
    """Scan a specific TV episode - URL-safe endpoint"""
    nfo_manager = dependencies["nfo_manager"]
    tv_processor = dependencies["tv_processor"]
    
    try:
        series_dir = Path(request.series_path)
        season_dir = series_dir / request.season_name
        episode_file = season_dir / request.episode_name
        
        if not series_dir.exists():
            raise HTTPException(status_code=404, detail=f"Series path not found: {request.series_path}")
        if not episode_file.exists():
            raise HTTPException(status_code=404, detail=f"Episode file not found: {episode_file}")
        
        imdb_id = nfo_manager.parse_imdb_from_path(series_dir)
        if not imdb_id:
            raise HTTPException(status_code=400, detail="No IMDb ID found in series path")
        
        async def process_episode():
            print(f"INFO: Processing TV episode: {episode_file}")
            try:
                tv_processor.process_episode_file(series_dir, season_dir, episode_file)
            except Exception as e:
                print(f"ERROR: Failed processing episode {episode_file}: {e}")
        
        background_tasks.add_task(process_episode)
        return {"status": "started", "message": f"Episode scan started for {request.episode_name}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def test_bulk_update(dependencies: dict):
    """Test bulk update functionality without modifying data"""
    try:
        from clients.radarr_db_client import RadarrDbClient
        
        # Test Radarr database
        radarr_db = RadarrDbClient.from_env()
        if not radarr_db:
            return {"status": "error", "message": "Radarr database connection failed"}
        
        # Test query execution
        query = 'SELECT COUNT(*) FROM "Movies" m JOIN "MovieMetadata" mm ON m."MovieMetadataId" = mm."Id" WHERE mm."ImdbId" IS NOT NULL'
        with radarr_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            movie_count = cursor.fetchone()[0]
        
        return {
            "status": "success", 
            "message": "Bulk update test passed",
            "movies_with_imdb": movie_count,
            "database_type": radarr_db.db_type
        }
    except Exception as e:
        return {"status": "error", "message": f"Bulk update test failed: {e}"}


async def test_movie_scan(dependencies: dict):
    """Test movie directory scanning logic"""
    config = dependencies["config"]
    nfo_manager = dependencies["nfo_manager"]
    
    try:
        results = []
        for path in config.movie_paths:
            path_result = {
                "path": str(path),
                "exists": path.exists(),
                "movies_found": 0
            }
            
            if path.exists():
                for item in path.iterdir():
                    if item.is_dir() and nfo_manager.find_movie_imdb_id(item):
                        path_result["movies_found"] += 1
            
            results.append(path_result)
        
        total_movies = sum(r["movies_found"] for r in results)
        return {
            "status": "success",
            "message": f"Movie scan test found {total_movies} movies",
            "path_results": results
        }
    except Exception as e:
        return {"status": "error", "message": f"Movie scan test failed: {e}"}


async def trigger_bulk_update(background_tasks: BackgroundTasks, dependencies: dict):
    """Trigger bulk update of all movies"""
    async def run_bulk_update():
        try:
            from bulk_update_movies import bulk_update_all_movies
            success = bulk_update_all_movies()
            print(f"INFO: Bulk update completed: {'success' if success else 'failed'}")
        except Exception as e:
            print(f"ERROR: Bulk update error: {e}")
    
    background_tasks.add_task(run_bulk_update)
    return {"status": "started", "message": "Bulk update started"}


async def debug_movie_priority_logic(imdb_id: str, dependencies: dict):
    """Debug endpoint showing how MOVIE_PRIORITY affects date selection"""
    config = dependencies["config"]
    movie_processor = dependencies["movie_processor"]
    
    try:
        if not imdb_id.startswith("tt"):
            imdb_id = f"tt{imdb_id}"
        
        result = {
            "imdb_id": imdb_id,
            "movie_priority": config.movie_priority,
            "release_date_priority": config.release_date_priority,
            "priority_explanation": "",
            "date_sources": {},
            "selected_date": None,
            "selected_source": None
        }
        
        # Get Radarr import date
        if movie_processor.radarr.api_key:
            radarr_movie = movie_processor.radarr.movie_by_imdb(imdb_id)
            if radarr_movie:
                movie_id = radarr_movie.get("id")
                if movie_id:
                    import_date, import_source = movie_processor.radarr.get_movie_import_date(movie_id)
                    if import_date:
                        result["date_sources"]["radarr_import"] = {
                            "date": import_date,
                            "source": import_source
                        }
        
        # Get digital release dates with detailed logging
        digital_date, digital_source = movie_processor._get_digital_release_date(imdb_id)
        if digital_date:
            result["date_sources"]["digital_release"] = {
                "date": digital_date,
                "source": digital_source
            }
        else:
            # Add debug info about why digital date wasn't found
            candidates = movie_processor.external_clients.get_digital_release_candidates(imdb_id)
            result["date_sources"]["digital_release_debug"] = {
                "candidates_found": len(candidates),
                "candidates": candidates[:3] if candidates else [],  # Show first 3
                "reason": digital_source if digital_source else "no_digital_dates_found"
            }
        
        # Show priority logic
        if config.movie_priority == "import_then_digital":
            priority_list = " → ".join(config.release_date_priority)
            result["priority_explanation"] = f"1st: Radarr import history, 2nd: Release dates ({priority_list}), 3rd: file mtime. Note: If import is only file date, prefer reasonable release dates."
            
            radarr_import = result["date_sources"].get("radarr_import")
            digital_release = result["date_sources"].get("digital_release")
            
            # Check for file date fallback logic
            if radarr_import and radarr_import["source"] == "radarr:db.file.dateAdded" and digital_release:
                # Test the smart logic
                would_prefer_digital = movie_processor._should_prefer_release_over_file_date(
                    digital_release["date"],
                    digital_release["source"], 
                    None,  # We don't have theatrical date in this debug context
                    imdb_id
                )
                result["file_date_detected"] = True
                result["would_prefer_digital"] = would_prefer_digital
                
                if would_prefer_digital:
                    result["selected_date"] = digital_release["date"]
                    result["selected_source"] = digital_release["source"] + " (preferred over file date)"
                else:
                    result["selected_date"] = radarr_import["date"]
                    result["selected_source"] = radarr_import["source"] + " (digital too old)"
            elif radarr_import and radarr_import["source"] != "radarr:db.file.dateAdded":
                result["selected_date"] = radarr_import["date"]
                result["selected_source"] = radarr_import["source"]
            elif digital_release:
                result["selected_date"] = digital_release["date"]
                result["selected_source"] = digital_release["source"]
        else:  # digital_then_import
            result["priority_explanation"] = "1st: TMDB/OMDb digital release, 2nd: Radarr import history, 3rd: file mtime"
            if result["date_sources"].get("digital_release"):
                result["selected_date"] = result["date_sources"]["digital_release"]["date"]
                result["selected_source"] = result["date_sources"]["digital_release"]["source"]
            elif result["date_sources"].get("radarr_import"):
                result["selected_date"] = result["date_sources"]["radarr_import"]["date"]
                result["selected_source"] = result["date_sources"]["radarr_import"]["source"]
        
        # Show external API status
        result["external_apis"] = {
            "tmdb_enabled": movie_processor.external_clients.tmdb.enabled,
            "omdb_enabled": movie_processor.external_clients.omdb.enabled,
            "jellyseerr_enabled": movie_processor.external_clients.jellyseerr.enabled
        }
        
        return result
        
    except Exception as e:
        return {"error": str(e), "imdb_id": imdb_id}


async def debug_tmdb_lookup(imdb_id: str, dependencies: dict):
    """Debug TMDB API lookup for a specific movie"""
    movie_processor = dependencies["movie_processor"]
    
    try:
        if not imdb_id.startswith("tt"):
            imdb_id = f"tt{imdb_id}"
        
        result = {
            "imdb_id": imdb_id,
            "tmdb_api_enabled": movie_processor.external_clients.tmdb.enabled,
            "tmdb_api_key_configured": bool(movie_processor.external_clients.tmdb.api_key),
            "steps": {}
        }
        
        if not movie_processor.external_clients.tmdb.enabled:
            result["error"] = "TMDB API not enabled - check TMDB_API_KEY environment variable"
            return result
        
        # Step 1: Find movie by IMDb ID
        print(f"INFO: TMDB Debug: Looking up {imdb_id}")
        tmdb_movie = movie_processor.external_clients.tmdb.find_by_imdb(imdb_id)
        result["steps"]["1_find_by_imdb"] = {
            "found": bool(tmdb_movie),
            "tmdb_movie": tmdb_movie if tmdb_movie else None
        }
        
        if not tmdb_movie:
            result["error"] = f"Movie {imdb_id} not found in TMDB"
            return result
        
        tmdb_id = tmdb_movie.get("id")
        result["tmdb_id"] = tmdb_id
        
        # Step 2: Get release dates
        if tmdb_id:
            print(f"INFO: TMDB Debug: Getting release dates for TMDB ID {tmdb_id}")
            release_dates_result = movie_processor.external_clients.tmdb._get(f"/movie/{tmdb_id}/release_dates")
            result["steps"]["2_release_dates"] = {
                "raw_response": release_dates_result,
                "has_results": bool(release_dates_result and release_dates_result.get("results"))
            }
            
            # Step 3: Look for US digital releases
            if release_dates_result and release_dates_result.get("results"):
                us_releases = []
                for country_data in release_dates_result["results"]:
                    if country_data.get("iso_3166_1") == "US":
                        us_releases = country_data.get("release_dates", [])
                        break
                
                result["steps"]["3_us_releases"] = {
                    "found_us_data": bool(us_releases),
                    "us_releases": us_releases
                }
                
                # Step 4: Look for digital releases (type 4)
                digital_releases = [r for r in us_releases if r.get("type") == 4]
                result["steps"]["4_digital_releases"] = {
                    "digital_count": len(digital_releases),
                    "digital_releases": digital_releases
                }
        
        # Step 5: Test the full digital release function
        digital_date = movie_processor.external_clients.tmdb.get_digital_release_date(imdb_id)
        result["steps"]["5_final_result"] = {
            "digital_date": digital_date,
            "success": bool(digital_date)
        }
        
        return result
        
    except Exception as e:
        return {"error": str(e), "imdb_id": imdb_id, "traceback": str(e)}


# ---------------------------
# Database Cleanup Endpoints
# ---------------------------

async def delete_episode(imdb_id: str, season: int, episode: int, dependencies: dict):
    """Delete a specific episode from the database"""
    db = dependencies["db"]
    
    try:
        deleted = db.delete_episode(imdb_id, season, episode)
        
        if deleted:
            return {
                "success": True,
                "message": f"Deleted episode S{season:02d}E{episode:02d} from series {imdb_id}",
                "imdb_id": imdb_id,
                "season": season,
                "episode": episode
            }
        else:
            return {
                "success": False,
                "message": f"Episode S{season:02d}E{episode:02d} not found in series {imdb_id}",
                "imdb_id": imdb_id,
                "season": season,
                "episode": episode
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "imdb_id": imdb_id,
            "season": season,
            "episode": episode
        }


async def delete_series_episodes(imdb_id: str, dependencies: dict):
    """Delete all episodes for a series from the database"""
    db = dependencies["db"]
    
    try:
        deleted_count = db.delete_series_episodes(imdb_id)
        
        return {
            "success": True,
            "message": f"Deleted {deleted_count} episodes from series {imdb_id}",
            "imdb_id": imdb_id,
            "deleted_count": deleted_count
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "imdb_id": imdb_id
        }


async def delete_movie(imdb_id: str, dependencies: dict):
    """Delete a specific movie from the database"""
    db = dependencies["db"]
    
    try:
        deleted = db.delete_movie(imdb_id)
        
        if deleted:
            return {
                "success": True,
                "message": f"Deleted movie {imdb_id} from database",
                "imdb_id": imdb_id
            }
        else:
            return {
                "success": False,
                "message": f"Movie {imdb_id} not found in database",
                "imdb_id": imdb_id
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "imdb_id": imdb_id
        }


async def cleanup_orphaned_episodes(dependencies: dict):
    """Find and delete episodes that don't have corresponding video files"""
    db = dependencies["db"]
    
    try:
        deleted_episodes = db.delete_orphaned_episodes()
        
        return {
            "success": True,
            "message": f"Cleaned up {len(deleted_episodes)} orphaned episodes",
            "deleted_count": len(deleted_episodes),
            "deleted_episodes": deleted_episodes
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to cleanup orphaned episodes"
        }


async def cleanup_orphaned_movies(dependencies: dict):
    """Find and delete movies that don't have corresponding video files"""
    db = dependencies["db"]
    
    try:
        deleted_movies = db.delete_orphaned_movies()
        
        return {
            "success": True,
            "message": f"Cleaned up {len(deleted_movies)} orphaned movies",
            "deleted_count": len(deleted_movies),
            "deleted_movies": deleted_movies
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to cleanup orphaned movies"
        }


async def cleanup_orphaned_series(dependencies: dict):
    """Find and delete TV series that don't have corresponding directories"""
    db = dependencies["db"]
    
    try:
        deleted_series = db.delete_orphaned_series()
        
        return {
            "success": True,
            "message": f"Cleaned up {len(deleted_series)} orphaned TV series",
            "deleted_count": len(deleted_series),
            "deleted_series": deleted_series
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to cleanup orphaned TV series"
        }


async def verify_nfo_sync(dependencies: dict, media_type: str = "both"):
    """Verify that database dates match NFO file contents"""
    db = dependencies["db"]
    nfo_manager = dependencies["nfo_manager"]
    config = dependencies["config"]
    
    try:
        verification_results = {
            "movies": {"total": 0, "verified": 0, "missing_nfo": 0, "date_mismatch": 0, "empty_nfo": 0, "issues": []},
            "episodes": {"total": 0, "verified": 0, "missing_nfo": 0, "date_mismatch": 0, "empty_nfo": 0, "issues": []}
        }
        
        print(f"🔍 NFO VERIFICATION STARTED: Checking {media_type}")
        
        # Verify Movies
        if media_type in ["both", "movies"]:
            print("📽️ Verifying movie NFO files...")
            
            # Get all movies from database
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT imdb_id, path, dateadded, released, source FROM movies WHERE has_video_file = true")
                movies = cursor.fetchall()
            
            verification_results["movies"]["total"] = len(movies)
            
            for movie in movies:
                imdb_id = movie['imdb_id']
                db_path = movie['path']
                db_dateadded = movie['dateadded']
                db_released = movie['released']
                db_source = movie['source']
                
                try:
                    from pathlib import Path
                    movie_path = Path(db_path)
                    nfo_path = movie_path / "movie.nfo"
                    
                    # Check if NFO exists
                    if not nfo_path.exists():
                        verification_results["movies"]["missing_nfo"] += 1
                        verification_results["movies"]["issues"].append({
                            "imdb_id": imdb_id,
                            "path": str(movie_path),
                            "issue": "missing_nfo",
                            "message": "NFO file does not exist"
                        })
                        continue
                    
                    # Check if NFO is empty
                    nfo_content = nfo_path.read_text(encoding='utf-8').strip()
                    if not nfo_content:
                        verification_results["movies"]["empty_nfo"] += 1
                        verification_results["movies"]["issues"].append({
                            "imdb_id": imdb_id,
                            "path": str(movie_path),
                            "issue": "empty_nfo",
                            "message": "NFO file exists but is empty"
                        })
                        continue
                    
                    # Extract Chronarr data from NFO
                    nfo_data = nfo_manager.extract_chronarr_dates_from_nfo(nfo_path)
                    
                    if not nfo_data:
                        verification_results["movies"]["date_mismatch"] += 1
                        verification_results["movies"]["issues"].append({
                            "imdb_id": imdb_id,
                            "path": str(movie_path),
                            "issue": "no_chronarr_data",
                            "message": "NFO exists but contains no Chronarr date information",
                            "db_dateadded": str(db_dateadded),
                            "db_source": db_source
                        })
                        continue
                    
                    # Compare dates
                    nfo_dateadded = nfo_data.get("dateadded")
                    nfo_source = nfo_data.get("source")
                    
                    # Convert database datetime to string for comparison
                    if hasattr(db_dateadded, 'isoformat'):
                        db_dateadded_str = db_dateadded.isoformat()
                    else:
                        db_dateadded_str = str(db_dateadded)
                    
                    # Check for date mismatch
                    if nfo_dateadded != db_dateadded_str or nfo_source != db_source:
                        verification_results["movies"]["date_mismatch"] += 1
                        verification_results["movies"]["issues"].append({
                            "imdb_id": imdb_id,
                            "path": str(movie_path),
                            "issue": "date_mismatch",
                            "message": "Database and NFO dates/sources don't match",
                            "db_dateadded": db_dateadded_str,
                            "db_source": db_source,
                            "nfo_dateadded": nfo_dateadded,
                            "nfo_source": nfo_source
                        })
                        continue
                    
                    # Everything matches
                    verification_results["movies"]["verified"] += 1
                    
                except Exception as e:
                    verification_results["movies"]["issues"].append({
                        "imdb_id": imdb_id,
                        "path": db_path,
                        "issue": "verification_error",
                        "message": f"Error during verification: {str(e)}"
                    })
        
        # Verify TV Episodes
        if media_type in ["both", "episodes"]:
            print("📺 Verifying TV episode NFO files...")
            
            # Get all episodes from database
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT imdb_id, season, episode, air_date, dateadded, source, video_path 
                    FROM episodes 
                    WHERE has_video_file = true 
                    ORDER BY imdb_id, season, episode
                """)
                episodes = cursor.fetchall()
            
            verification_results["episodes"]["total"] = len(episodes)
            
            for episode in episodes:
                imdb_id = episode['imdb_id']
                season = episode['season']
                episode_num = episode['episode']
                db_air_date = episode['air_date']
                db_dateadded = episode['dateadded']
                db_source = episode['source']
                video_path = episode['video_path']
                
                try:
                    from pathlib import Path
                    if video_path:
                        video_file = Path(video_path)
                        nfo_path = video_file.with_suffix('.nfo')
                    else:
                        # Construct expected path
                        for tv_path in config.tv_paths:
                            series_dirs = [d for d in tv_path.iterdir() if d.is_dir() and imdb_id in str(d)]
                            if series_dirs:
                                season_dir = series_dirs[0] / f"Season {season:02d}"
                                if season_dir.exists():
                                    episode_files = list(season_dir.glob(f"*S{season:02d}E{episode_num:02d}*.nfo"))
                                    if episode_files:
                                        nfo_path = episode_files[0]
                                        break
                        else:
                            continue
                    
                    # Check if NFO exists
                    if not nfo_path.exists():
                        verification_results["episodes"]["missing_nfo"] += 1
                        verification_results["episodes"]["issues"].append({
                            "imdb_id": imdb_id,
                            "episode": f"S{season:02d}E{episode_num:02d}",
                            "issue": "missing_nfo",
                            "message": "NFO file does not exist",
                            "expected_path": str(nfo_path)
                        })
                        continue
                    
                    # Check if NFO is empty
                    nfo_content = nfo_path.read_text(encoding='utf-8').strip()
                    if not nfo_content:
                        verification_results["episodes"]["empty_nfo"] += 1
                        verification_results["episodes"]["issues"].append({
                            "imdb_id": imdb_id,
                            "episode": f"S{season:02d}E{episode_num:02d}",
                            "issue": "empty_nfo",
                            "message": "NFO file exists but is empty",
                            "nfo_path": str(nfo_path)
                        })
                        continue
                    
                    # Extract Chronarr data from episode NFO
                    nfo_data = nfo_manager.extract_chronarr_dates_from_episode_nfo(nfo_path)
                    
                    if not nfo_data:
                        verification_results["episodes"]["date_mismatch"] += 1
                        verification_results["episodes"]["issues"].append({
                            "imdb_id": imdb_id,
                            "episode": f"S{season:02d}E{episode_num:02d}",
                            "issue": "no_chronarr_data",
                            "message": "NFO exists but contains no Chronarr date information",
                            "db_dateadded": str(db_dateadded),
                            "db_source": db_source,
                            "nfo_path": str(nfo_path)
                        })
                        continue
                    
                    # Everything matches
                    verification_results["episodes"]["verified"] += 1
                    
                except Exception as e:
                    verification_results["episodes"]["issues"].append({
                        "imdb_id": imdb_id,
                        "episode": f"S{season:02d}E{episode_num:02d}",
                        "issue": "verification_error",
                        "message": f"Error during verification: {str(e)}"
                    })
        
        # Print summary
        if media_type in ["both", "movies"]:
            movies = verification_results["movies"]
            print(f"📽️ MOVIE VERIFICATION COMPLETE:")
            print(f"   Total Movies: {movies['total']}")
            print(f"   ✅ Verified: {movies['verified']}")
            print(f"   ❌ Missing NFO: {movies['missing_nfo']}")
            print(f"   📄 Empty NFO: {movies['empty_nfo']}")
            print(f"   🔄 Date Mismatch: {movies['date_mismatch']}")
        
        if media_type in ["both", "episodes"]:
            episodes = verification_results["episodes"]
            print(f"📺 EPISODE VERIFICATION COMPLETE:")
            print(f"   Total Episodes: {episodes['total']}")
            print(f"   ✅ Verified: {episodes['verified']}")
            print(f"   ❌ Missing NFO: {episodes['missing_nfo']}")
            print(f"   📄 Empty NFO: {episodes['empty_nfo']}")
            print(f"   🔄 Date Mismatch: {episodes['date_mismatch']}")
        
        return {
            "success": True,
            "message": f"NFO verification completed for {media_type}",
            "results": verification_results
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to verify NFO files"
        }


async def fix_nfo_sync_issues(dependencies: dict, media_type: str = "both"):
    """Fix NFO sync issues by regenerating NFO files from database data"""
    db = dependencies["db"]
    nfo_manager = dependencies["nfo_manager"]
    config = dependencies["config"]
    
    try:
        # First run verification to identify issues
        verification_result = await verify_nfo_sync(dependencies, media_type)
        if not verification_result["success"]:
            return verification_result
        
        results = verification_result["results"]
        fix_results = {
            "movies": {"fixed": 0, "failed": 0, "errors": []},
            "episodes": {"fixed": 0, "failed": 0, "errors": []}
        }
        
        print(f"🔧 NFO FIX STARTED: Regenerating NFO files for {media_type}")
        
        # Fix Movies
        if media_type in ["both", "movies"]:
            print("📽️ Fixing movie NFO files...")
            
            for issue in results["movies"]["issues"]:
                if issue["issue"] in ["empty_nfo", "no_chronarr_data", "date_mismatch"]:
                    imdb_id = issue["imdb_id"]
                    movie_path = issue["path"]
                    
                    try:
                        # Get movie data from database
                        movie_data = db.get_movie_dates(imdb_id)
                        if not movie_data:
                            fix_results["movies"]["errors"].append(f"No database data for {imdb_id}")
                            fix_results["movies"]["failed"] += 1
                            continue
                        
                        dateadded = movie_data.get("dateadded")
                        released = movie_data.get("released")
                        source = movie_data.get("source")
                        
                        # Convert datetime to string if needed
                        if hasattr(dateadded, 'isoformat'):
                            dateadded = dateadded.isoformat()
                        if released and hasattr(released, 'isoformat'):
                            released = released.isoformat()
                        
                        # Regenerate NFO file
                        from pathlib import Path
                        movie_path_obj = Path(movie_path)
                        
                        if config.manage_nfo:
                            nfo_manager.create_movie_nfo(
                                movie_path_obj, imdb_id, dateadded, released, source, config.lock_metadata
                            )
                            print(f"✅ Fixed NFO for {imdb_id}: {movie_path}")
                            fix_results["movies"]["fixed"] += 1
                        else:
                            fix_results["movies"]["errors"].append(f"MANAGE_NFO disabled - cannot fix {imdb_id}")
                            fix_results["movies"]["failed"] += 1
                        
                    except Exception as e:
                        fix_results["movies"]["errors"].append(f"Error fixing {imdb_id}: {str(e)}")
                        fix_results["movies"]["failed"] += 1
        
        # Fix Episodes
        if media_type in ["both", "episodes"]:
            print("📺 Fixing TV episode NFO files...")
            
            for issue in results["episodes"]["issues"]:
                if issue["issue"] in ["empty_nfo", "no_chronarr_data", "date_mismatch"]:
                    imdb_id = issue["imdb_id"]
                    episode_str = issue["episode"]
                    
                    try:
                        # Parse season/episode from string like "S01E05"
                        import re
                        match = re.match(r'S(\d+)E(\d+)', episode_str)
                        if not match:
                            continue
                        
                        season = int(match.group(1))
                        episode_num = int(match.group(2))
                        
                        # Get episode data from database
                        episode_data = db.get_episode_date(imdb_id, season, episode_num)
                        if not episode_data:
                            fix_results["episodes"]["errors"].append(f"No database data for {episode_str}")
                            fix_results["episodes"]["failed"] += 1
                            continue
                        
                        air_date = episode_data.get("air_date")
                        dateadded = episode_data.get("dateadded")
                        source = episode_data.get("source")
                        video_path = episode_data.get("video_path")
                        
                        # Convert datetime to string if needed
                        if hasattr(air_date, 'isoformat'):
                            air_date = air_date.isoformat()
                        if hasattr(dateadded, 'isoformat'):
                            dateadded = dateadded.isoformat()
                        
                        # Find the episode file
                        from pathlib import Path
                        if video_path:
                            episode_file = Path(video_path)
                        else:
                            # Try to find it by scanning
                            episode_file = None
                            for tv_path in config.tv_paths:
                                series_dirs = [d for d in tv_path.iterdir() if d.is_dir() and imdb_id in str(d)]
                                if series_dirs:
                                    season_dir = series_dirs[0] / f"Season {season:02d}"
                                    if season_dir.exists():
                                        video_files = list(season_dir.glob(f"*S{season:02d}E{episode_num:02d}*.mkv")) + \
                                                    list(season_dir.glob(f"*S{season:02d}E{episode_num:02d}*.mp4")) + \
                                                    list(season_dir.glob(f"*S{season:02d}E{episode_num:02d}*.avi"))
                                        if video_files:
                                            episode_file = video_files[0]
                                            break
                        
                        if not episode_file or not episode_file.exists():
                            fix_results["episodes"]["errors"].append(f"Cannot find video file for {episode_str}")
                            fix_results["episodes"]["failed"] += 1
                            continue
                        
                        # Regenerate NFO file
                        if config.manage_nfo:
                            nfo_manager.create_episode_nfo(
                                episode_file, imdb_id, season, episode_num, air_date, dateadded, source, config.lock_metadata
                            )
                            print(f"✅ Fixed NFO for {episode_str}: {episode_file}")
                            fix_results["episodes"]["fixed"] += 1
                        else:
                            fix_results["episodes"]["errors"].append(f"MANAGE_NFO disabled - cannot fix {episode_str}")
                            fix_results["episodes"]["failed"] += 1
                        
                    except Exception as e:
                        fix_results["episodes"]["errors"].append(f"Error fixing {episode_str}: {str(e)}")
                        fix_results["episodes"]["failed"] += 1
        
        # Print summary
        movies = fix_results["movies"]
        episodes = fix_results["episodes"]
        
        print(f"🔧 NFO FIX COMPLETED:")
        if media_type in ["both", "movies"]:
            print(f"   📽️ Movies: {movies['fixed']} fixed, {movies['failed']} failed")
        if media_type in ["both", "episodes"]:
            print(f"   📺 Episodes: {episodes['fixed']} fixed, {episodes['failed']} failed")
        
        return {
            "success": True,
            "message": f"NFO fix completed for {media_type}",
            "fix_results": fix_results,
            "original_verification": results
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to fix NFO sync issues"
        }


async def backfill_movie_release_dates(dependencies: dict):
    """Backfill missing release dates for existing movies"""
    db = dependencies["db"]
    movie_processor = dependencies["movie_processor"]
    
    try:
        # Get all movies with missing release dates
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Find movies where released is NULL but source suggests we found a release date
            query = """
                SELECT imdb_id, path, dateadded, source 
                FROM movies 
                WHERE released IS NULL 
                AND (source LIKE '%tmdb%' OR source LIKE '%omdb%' OR source LIKE '%premiered%')
                ORDER BY last_updated DESC
            """
            cursor.execute(query)
            movies_to_backfill = cursor.fetchall()
        
        if not movies_to_backfill:
            return {
                "success": True,
                "message": "No movies found that need release date backfill",
                "movies_processed": 0,
                "movies_updated": 0
            }
        
        processed_count = 0
        updated_count = 0
        
        print(f"🔄 BACKFILL STARTED: Found {len(movies_to_backfill)} movies needing release date backfill")
        
        for movie in movies_to_backfill:
            imdb_id = movie['imdb_id']
            source = movie['source']
            
            try:
                print(f"🔍 Processing {imdb_id} (source: {source})")
                
                # Try to get release date based on the source
                release_date = None
                
                if 'tmdb' in source or 'omdb' in source:
                    # Re-fetch digital release date
                    digital_date, _ = movie_processor._get_digital_release_date(imdb_id)
                    if digital_date:
                        release_date = digital_date
                        print(f"✅ Found release date for {imdb_id}: {release_date}")
                    else:
                        print(f"⚠️ Could not re-fetch release date for {imdb_id}")
                
                elif 'premiered' in source:
                    # Use the dateadded as the release date for premiered sources
                    release_date = movie['dateadded']
                    if hasattr(release_date, 'isoformat'):
                        release_date = release_date.isoformat()
                    print(f"✅ Using premiered date for {imdb_id}: {release_date}")
                
                # Update the database if we found a release date
                if release_date:
                    db.upsert_movie_dates(imdb_id, release_date, movie['dateadded'], source, True)
                    updated_count += 1
                    print(f"📝 Updated release date for {imdb_id}")
                
                processed_count += 1
                
                # Small delay to avoid overwhelming APIs
                import time
                time.sleep(0.1)
                
            except Exception as e:
                print(f"❌ Error processing {imdb_id}: {e}")
                processed_count += 1
                continue
        
        print(f"✅ BACKFILL COMPLETED: Processed {processed_count} movies, updated {updated_count} with release dates")
        
        return {
            "success": True,
            "message": f"Backfill completed: processed {processed_count} movies, updated {updated_count} with release dates",
            "movies_processed": processed_count,
            "movies_updated": updated_count,
            "movies_found": len(movies_to_backfill)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to backfill movie release dates"
        }


# ---------------------------
# Scan Status Functions
# ---------------------------

async def get_scan_status():
    """Get detailed scan status with progress information"""
    global scan_status
    
    if not scan_status["scanning"]:
        return {"scanning": False, "message": "No active scan"}
    
    # Calculate elapsed time
    from datetime import datetime
    if scan_status["start_time"]:
        elapsed_seconds = int((datetime.now() - scan_status["start_time"]).total_seconds())
        if elapsed_seconds >= 60:
            minutes = elapsed_seconds // 60
            seconds = elapsed_seconds % 60
            elapsed_str = f"{minutes}m {seconds}s"
        else:
            elapsed_str = f"{elapsed_seconds}s"
    else:
        elapsed_str = "unknown"
    
    # Build detailed status message
    if scan_status["current_operation"] == "tv":
        if scan_status["tv_series_total"] > 0:
            message = f"Processing TV series ({scan_status['tv_series_processed']}/{scan_status['tv_series_total']}) - {elapsed_str} elapsed"
        else:
            message = f"Processed {scan_status['tv_series_processed']} TV series - {elapsed_str} elapsed"
    elif scan_status["current_operation"] == "movies":
        if scan_status["movies_total"] > 0:
            message = f"Processing movies ({scan_status['movies_processed']}/{scan_status['movies_total']}) - {elapsed_str} elapsed"
        else:
            message = f"Processed {scan_status['movies_processed']} movies - {elapsed_str} elapsed"
    else:
        message = f"Scan in progress - {elapsed_str} elapsed"
    
    # Add current item if available
    if scan_status["current_item"]:
        message += f" | Current: {scan_status['current_item']}"
    
    return {
        "scanning": True,
        "message": message,
        "scan_type": scan_status["scan_type"],
        "scan_mode": scan_status["scan_mode"],
        "elapsed_seconds": elapsed_seconds if scan_status["start_time"] else 0,
        "current_operation": scan_status["current_operation"],
        "tv_series_processed": scan_status["tv_series_processed"],
        "tv_series_total": scan_status["tv_series_total"],
        "tv_series_skipped": scan_status["tv_series_skipped"],
        "movies_processed": scan_status["movies_processed"],
        "movies_total": scan_status["movies_total"],
        "movies_skipped": scan_status["movies_skipped"],
        "current_item": scan_status["current_item"]
    }

def update_scan_status(operation=None, current_item=None, **kwargs):
    """Update scan status with new progress information"""
    global scan_status
    
    if operation:
        scan_status["current_operation"] = operation
    if current_item:
        scan_status["current_item"] = current_item
    
    # Update counters
    for key, value in kwargs.items():
        if key in scan_status:
            scan_status[key] = value
    
    scan_status["last_update"] = datetime.now()

def start_scan_tracking(scan_type, scan_mode):
    """Initialize scan tracking"""
    global scan_status
    
    scan_status.update({
        "scanning": True,
        "scan_type": scan_type,
        "scan_mode": scan_mode,
        "start_time": datetime.now(),
        "current_operation": None,
        "tv_series_processed": 0,
        "tv_series_total": 0,
        "tv_series_skipped": 0,
        "movies_processed": 0,
        "movies_total": 0,
        "movies_skipped": 0,
        "current_item": None,
        "last_update": datetime.now()
    })

def stop_scan_tracking():
    """Stop scan tracking"""
    global scan_status
    
    scan_status.update({
        "scanning": False,
        "scan_type": None,
        "scan_mode": None,
        "start_time": None,
        "current_operation": None,
        "current_item": None
    })

# ---------------------------
# Route Registration
# ---------------------------

async def update_episode_nfo(imdb_id: str, season: int, episode: int, request: Request, dependencies: dict):
    """Update NFO file for a specific episode with new dateadded"""
    try:
        # Get request data
        payload = await request.json()
        dateadded = payload.get('dateadded')
        source = payload.get('source', 'manual')
        aired = payload.get('aired')
        
        # Get dependencies
        config = dependencies["config"]
        nfo_manager = dependencies["nfo_manager"]
        
        if not config.manage_nfo:
            return {"success": False, "message": "NFO management is disabled"}
        
        # Find the series directory based on IMDb ID
        series_path = None
        for tv_path in config.tv_paths:
            for series_dir in Path(tv_path).iterdir():
                if series_dir.is_dir() and imdb_id.lower() in series_dir.name.lower():
                    series_path = series_dir
                    break
            if series_path:
                break
        
        if not series_path:
            return {"success": False, "message": f"Series directory not found for {imdb_id}"}
        
        # Get season directory
        season_dir = series_path / config.get_season_dir_name(season)
        if not season_dir.exists():
            return {"success": False, "message": f"Season directory not found: {season_dir}"}
        
        # Update NFO file
        nfo_manager.create_episode_nfo(
            season_dir=season_dir,
            season_num=season,
            episode_num=episode,
            aired=aired,
            dateadded=dateadded,
            source=source,
            lock_metadata=config.lock_metadata
        )
        
        print(f"✅ Updated NFO file for {imdb_id} S{season:02d}E{episode:02d}")
        return {"success": True, "message": f"NFO file updated for {imdb_id} S{season:02d}E{episode:02d}"}
        
    except Exception as e:
        print(f"❌ Error updating NFO file for {imdb_id} S{season:02d}E{episode:02d}: {e}")
        return {"success": False, "message": f"Failed to update NFO file: {str(e)}"}


# ---------------------------
# Emby Plugin Lookup Functions
# ---------------------------

async def lookup_episode(imdb_id: str, season: int, episode: int, dependencies: dict):
    """
    Lookup episode dateadded from Chronarr database for Emby plugin integration
    
    Returns dateadded information if found, or null if not available.
    Used by Emby plugin to populate missing dateadded elements in NFO files.
    """
    try:
        print(f"DEBUG: Episode lookup called for {imdb_id} S{season:02d}E{episode:02d}")
        
        db = dependencies.get("db")
        if not db:
            print(f"ERROR: Database not available in dependencies")
            raise HTTPException(status_code=500, detail="Database not available")
        
        # Normalize IMDb ID (ensure tt prefix)
        if not imdb_id.startswith('tt'):
            imdb_id = f"tt{imdb_id}"
        
        print(f"DEBUG: Querying database for episode {imdb_id} S{season:02d}E{episode:02d}")
        
        # Query database for episode
        result = db.get_episode_date(imdb_id, season, episode)
        
        print(f"DEBUG: Database query result: {result}")
        
        if result and result.get('dateadded'):
            # Format response for Emby plugin
            dateadded = result['dateadded']
            
            # Convert datetime to ISO string if needed
            if hasattr(dateadded, 'isoformat'):
                dateadded_str = dateadded.isoformat()
            else:
                dateadded_str = str(dateadded)
            
            # NOTE: Auto-fix functionality removed - just return database data
            
            return {
                "found": True,
                "imdb_id": imdb_id,
                "season": season,
                "episode": episode,
                "dateadded": dateadded_str,
                "source": result.get('source', 'database'),
                "air_date": result.get('air_date') if result.get('air_date') else None,
                "auto_fixed": False  # Auto-fix functionality disabled
            }
        else:
            # Not found in database
            return {
                "found": False,
                "imdb_id": imdb_id,
                "season": season,
                "episode": episode,
                "dateadded": None,
                "source": None,
                "air_date": None
            }
            
    except Exception as e:
        _log("ERROR", f"Episode lookup failed for {imdb_id} S{season:02d}E{episode:02d}: {e}")
        raise HTTPException(status_code=500, detail=f"Episode lookup failed: {str(e)}")


def extract_title_and_year_from_path(nfo_path: str) -> tuple:
    """
    Extract movie title and year from NFO file path
    Examples:
    - "/path/Scream (1996)/movie.nfo" -> ("Scream", "1996")
    - "/path/Witchboard (2025)/movie.nfo" -> ("Witchboard", "2025") 
    - "/path/The Conjuring 2 (2016) [tt3065204]/movie.nfo" -> ("The Conjuring 2", "2016")
    """
    import re
    from pathlib import Path
    
    # Get the directory name (movie folder)
    dir_name = Path(nfo_path).parent.name
    
    # Pattern to extract title and year: "Title (YYYY)" 
    pattern = r'^(.+?)\s*\((\d{4})\)'
    match = re.search(pattern, dir_name)
    
    if match:
        title = match.group(1).strip()
        year = match.group(2)
        return title, year
    
    # Fallback: try to find year anywhere in the path
    year_pattern = r'\((\d{4})\)'
    year_match = re.search(year_pattern, dir_name)
    year = year_match.group(1) if year_match else None
    
    # Remove any [imdb-*] or [tt*] patterns and year patterns
    clean_title = re.sub(r'\s*\[\s*(?:imdb-)?tt\d+\s*\]', '', dir_name)
    clean_title = re.sub(r'\s*\(\d{4}\)', '', clean_title)
    clean_title = clean_title.strip()
    
    return clean_title, year


async def lookup_movie_comprehensive(nfo_path: str, dependencies: dict):
    """
    Comprehensive movie lookup that tries multiple methods:
    1. Extract IMDb ID from path/NFO -> lookup by IMDb
    2. Extract title/year from path -> lookup by title  
    3. Extract title only -> fuzzy lookup
    """
    try:
        _log("DEBUG", f"Comprehensive movie lookup for: {nfo_path}")
        
        # First try to extract IMDb ID from path
        from utils.nfo_patterns import extract_imdb_id_from_text
        imdb_id = extract_imdb_id_from_text(nfo_path)
        
        if imdb_id:
            _log("DEBUG", f"Found IMDb ID in path: {imdb_id}")
            result = await lookup_movie(imdb_id, dependencies)
            if result.get("found"):
                result["lookup_method"] = "imdb_from_path"
                return result
        
        # If IMDb lookup failed, try title-based lookup
        title, year = extract_title_and_year_from_path(nfo_path)
        _log("DEBUG", f"Extracted title: '{title}', year: '{year}' from path")
        
        if title:
            result = await lookup_movie_by_title(title, year, dependencies)
            if result.get("found"):
                return result
        
        # All methods failed
        return {
            "found": False,
            "nfo_path": nfo_path,
            "extracted_title": title,
            "extracted_year": year,
            "extracted_imdb": imdb_id,
            "lookup_method": "comprehensive_failed"
        }
        
    except Exception as e:
        _log("ERROR", f"Comprehensive movie lookup failed for {nfo_path}: {e}")
        return {
            "found": False,
            "error": str(e),
            "lookup_method": "comprehensive_error"
        }


async def lookup_movie_by_title(title: str, year: str, dependencies: dict):
    """
    Lookup movie by title and year when IMDb ID is not available
    
    This is a fallback for when Radarr overwrites NFO files and IMDb IDs are lost.
    """
    try:
        db = dependencies.get("db")
        if not db:
            raise HTTPException(status_code=500, detail="Database not available")
        
        _log("DEBUG", f"Movie lookup by title: '{title}' year: '{year}'")
        
        # Clean up the title (remove common brackets, extra spaces)
        clean_title = title.strip()
        
        # Search database by title pattern matching
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Try exact title match first
            if year:
                cursor.execute("""
                    SELECT * FROM movies 
                    WHERE LOWER(title) = LOWER(%s) AND released::text LIKE %s
                    ORDER BY dateadded DESC
                    LIMIT 1
                """, (clean_title, f"{year}%"))
            else:
                cursor.execute("""
                    SELECT * FROM movies 
                    WHERE LOWER(title) = LOWER(%s)
                    ORDER BY dateadded DESC
                    LIMIT 1
                """, (clean_title,))
            
            row = cursor.fetchone()
            
            # If exact match fails, try fuzzy matching
            if not row:
                _log("DEBUG", f"Exact match failed, trying fuzzy match for '{clean_title}'")
                
                if year:
                    cursor.execute("""
                        SELECT * FROM movies 
                        WHERE LOWER(title) LIKE LOWER(%s) AND released::text LIKE %s
                        ORDER BY dateadded DESC
                        LIMIT 1
                    """, (f"%{clean_title}%", f"{year}%"))
                else:
                    cursor.execute("""
                        SELECT * FROM movies 
                        WHERE LOWER(title) LIKE LOWER(%s)
                        ORDER BY dateadded DESC
                        LIMIT 1
                    """, (f"%{clean_title}%",))
                
                row = cursor.fetchone()
            
            if row:
                result = dict(row)
                _log("DEBUG", f"Found movie by title search: {result}")
                
                if result.get('dateadded'):
                    dateadded = result['dateadded']
                    if hasattr(dateadded, 'isoformat'):
                        dateadded_str = dateadded.isoformat()
                    else:
                        dateadded_str = str(dateadded)
                    
                    return {
                        "found": True,
                        "imdb_id": result.get('imdb_id'),
                        "title": result.get('title'),
                        "dateadded": dateadded_str,
                        "source": result.get('source', 'database'),
                        "released": result.get('released') if result.get('released') else None,
                        "lookup_method": "title_search"
                    }
            
            _log("DEBUG", f"No movie found for title '{clean_title}' year '{year}'")
            return {
                "found": False,
                "title": clean_title,
                "year": year,
                "lookup_method": "title_search"
            }
            
    except Exception as e:
        _log("ERROR", f"Movie title lookup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Movie title lookup failed: {str(e)}")


async def lookup_movie(imdb_id: str, dependencies: dict):
    """
    Lookup movie dateadded from Chronarr database for Emby plugin integration
    
    Returns dateadded information if found, or null if not available.  
    Used by Emby plugin to populate missing dateadded elements in NFO files.
    """
    try:
        db = dependencies.get("db")
        if not db:
            raise HTTPException(status_code=500, detail="Database not available")
        
        _log("DEBUG", f"Movie lookup called for IMDb ID: {imdb_id}")
        
        # Normalize IMDb ID (ensure tt prefix)
        if not imdb_id.startswith('tt'):
            imdb_id = f"tt{imdb_id}"
        
        _log("DEBUG", f"Normalized IMDb ID: {imdb_id}")
        
        # Query database for movie
        result = db.get_movie_dates(imdb_id)
        _log("DEBUG", f"Movie lookup for {imdb_id}: database result = {result}")
        
        # If not found, let's see what movies we DO have in the database
        if not result:
            _log("DEBUG", f"Movie {imdb_id} not found, checking what movies exist in database...")
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT imdb_id, title FROM movies ORDER BY dateadded DESC LIMIT 10")
                recent_movies = cursor.fetchall()
                _log("DEBUG", f"Recent movies in database: {[dict(row) for row in recent_movies]}")
        
        if result and result.get('dateadded'):
            # Format response for Emby plugin
            dateadded = result['dateadded']
            
            # Convert datetime to ISO string if needed
            if hasattr(dateadded, 'isoformat'):
                dateadded_str = dateadded.isoformat()
            else:
                dateadded_str = str(dateadded)
            
            # NOTE: Auto-fix functionality removed - just return database data
            
            return {
                "found": True,
                "imdb_id": imdb_id,
                "dateadded": dateadded_str,
                "source": result.get('source', 'database'),
                "released": result.get('released') if result.get('released') else None,
                "auto_fixed": False  # Auto-fix functionality disabled
            }
        else:
            # Not found in database
            return {
                "found": False,
                "imdb_id": imdb_id,
                "dateadded": None,
                "source": None,
                "released": None
            }
            
    except Exception as e:
        _log("ERROR", f"Movie lookup failed for {imdb_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Movie lookup failed: {str(e)}")


async def populate_database(background_tasks: BackgroundTasks, media_type: str = "both", dependencies: dict = None):
    """
    Populate Chronarr database from Radarr/Sonarr sources

    Args:
        background_tasks: FastAPI background tasks
        media_type: Type of media to populate ("movies", "tv", or "both")
        dependencies: Dictionary with db, radarr_client, sonarr_client

    Returns:
        Status message indicating population has started
    """
    from core.database_populator import DatabasePopulator

    db = dependencies["db"]
    config = dependencies["config"]

    # Get Radarr and Sonarr clients
    from clients.radarr_client import RadarrClient
    from clients.sonarr_client import SonarrClient

    radarr_client = RadarrClient(config)
    sonarr_client = SonarrClient(config)

    if media_type not in ["both", "movies", "tv"]:
        raise HTTPException(status_code=400, detail="media_type must be 'both', 'movies', or 'tv'")

    # Create global status tracking
    populate_status = {
        "running": True,
        "media_type": media_type,
        "start_time": datetime.now().isoformat(),
        "movies": {"status": "pending", "stats": None},
        "tv": {"status": "pending", "stats": None},
        "completed": False,
        "error": None
    }

    # Store status globally so it can be queried
    global _populate_status
    _populate_status = populate_status

    async def run_population():
        """Background task to populate the database"""
        try:
            populator = DatabasePopulator(db, radarr_client, sonarr_client)

            _log("INFO", f"Starting database population: {media_type}")

            if media_type == "movies":
                populate_status["movies"]["status"] = "running"
                movie_stats = populator.populate_movies()
                populate_status["movies"]["status"] = "completed"
                populate_status["movies"]["stats"] = movie_stats
                _log("INFO", f"Movie population completed: {movie_stats}")

            elif media_type == "tv":
                populate_status["tv"]["status"] = "running"
                tv_stats = populator.populate_tv_episodes()
                populate_status["tv"]["status"] = "completed"
                populate_status["tv"]["stats"] = tv_stats
                _log("INFO", f"TV population completed: {tv_stats}")

            elif media_type == "both":
                populate_status["movies"]["status"] = "running"
                movie_stats = populator.populate_movies()
                populate_status["movies"]["status"] = "completed"
                populate_status["movies"]["stats"] = movie_stats
                _log("INFO", f"Movie population completed: {movie_stats}")

                populate_status["tv"]["status"] = "running"
                tv_stats = populator.populate_tv_episodes()
                populate_status["tv"]["status"] = "completed"
                populate_status["tv"]["stats"] = tv_stats
                _log("INFO", f"TV population completed: {tv_stats}")

            populate_status["completed"] = True
            populate_status["running"] = False
            _log("INFO", "Database population completed successfully")

        except Exception as e:
            _log("ERROR", f"Database population failed: {e}")
            populate_status["error"] = str(e)
            populate_status["running"] = False
            populate_status["completed"] = True

    # Add task to background
    background_tasks.add_task(run_population)

    _log("INFO", f"Database population started for: {media_type}")
    return {
        "status": "started",
        "media_type": media_type,
        "message": f"Database population started for {media_type}"
    }


async def get_populate_status():
    """Get the current status of database population"""
    global _populate_status
    if '_populate_status' not in globals():
        return {"running": False, "completed": False}
    return _populate_status


# Initialize global populate status
_populate_status = {"running": False, "completed": False}


def register_routes(app, dependencies: dict):
    """
    Register all routes with the FastAPI app
    
    Args:
        app: FastAPI application instance
        dependencies: Dictionary containing:
            - db: ChronarrDatabase instance
            - nfo_manager: NFOManager instance
            - path_mapper: PathMapper instance
            - tv_processor: TVProcessor instance
            - movie_processor: MovieProcessor instance
            - batcher: WebhookBatcher instance
            - start_time: Application start time
            - config: ChronarrConfig instance
            - version: Application version string
    """
    
    @app.post("/webhook/sonarr")
    async def _sonarr_webhook(request: Request, background_tasks: BackgroundTasks):
        return await sonarr_webhook(request, background_tasks, dependencies)

    @app.post("/webhook/radarr") 
    async def _radarr_webhook(request: Request, background_tasks: BackgroundTasks):
        return await radarr_webhook(request, background_tasks, dependencies)

    @app.post("/webhook/maintainarr")
    async def _maintainarr_webhook(request: Request, background_tasks: BackgroundTasks):
        return await maintainarr_webhook(request, background_tasks, dependencies)

    @app.get("/health")
    async def _health() -> HealthResponse:
        return await health(dependencies)
    
    @app.get("/health/simple")
    async def _health_simple():
        """Simple health check for Docker without external dependencies"""
        return {"status": "healthy", "service": "chronarr-core"}

    @app.get("/stats")
    async def _get_stats():
        return await get_stats(dependencies)

    @app.get("/batch/status") 
    async def _batch_status():
        return await batch_status(dependencies)

    @app.get("/debug/movie/{imdb_id}")
    async def _debug_movie_import_date(imdb_id: str):
        return await debug_movie_import_date(imdb_id, dependencies)

    @app.get("/debug/movie/{imdb_id}/history")
    async def _debug_movie_history(imdb_id: str):
        return await debug_movie_history(imdb_id, dependencies)

    @app.delete("/database/episode/{imdb_id}/{season}/{episode}")
    async def _delete_episode(imdb_id: str, season: int, episode: int):
        return await delete_episode(imdb_id, season, episode, dependencies)
    
    @app.post("/api/episodes/{imdb_id}/{season}/{episode}/update-nfo")
    async def _update_episode_nfo(imdb_id: str, season: int, episode: int, request: Request):
        return await update_episode_nfo(imdb_id, season, episode, request, dependencies)

    @app.delete("/database/series/{imdb_id}/episodes")
    async def _delete_series_episodes(imdb_id: str):
        return await delete_series_episodes(imdb_id, dependencies)

    @app.delete("/database/movie/{imdb_id}")
    async def _delete_movie(imdb_id: str):
        return await delete_movie(imdb_id, dependencies)

    @app.post("/database/cleanup/orphaned-episodes")
    async def _cleanup_orphaned_episodes():
        return await cleanup_orphaned_episodes(dependencies)

    @app.post("/database/cleanup/orphaned-movies")
    async def _cleanup_orphaned_movies():
        return await cleanup_orphaned_movies(dependencies)

    @app.post("/database/cleanup/orphaned-series")
    async def _cleanup_orphaned_series():
        return await cleanup_orphaned_series(dependencies)

    @app.post("/database/backfill/movie-release-dates")
    async def _backfill_movie_release_dates():
        return await backfill_movie_release_dates(dependencies)

    @app.post("/database/verify/nfo-sync")
    async def _verify_nfo_sync(media_type: str = "both"):
        return await verify_nfo_sync(dependencies, media_type)

    @app.post("/database/fix/nfo-sync")
    async def _fix_nfo_sync_issues(media_type: str = "both"):
        return await fix_nfo_sync_issues(dependencies, media_type)

    @app.post("/manual/scan")
    async def _manual_scan(background_tasks: BackgroundTasks, path: Optional[str] = None, scan_type: str = "both", scan_mode: str = "smart"):
        return await manual_scan(background_tasks, path, scan_type, scan_mode, dependencies)

    @app.get("/api/scan/status")
    async def _scan_status():
        return await get_scan_status()

    @app.post("/admin/populate-database")
    async def _populate_database(background_tasks: BackgroundTasks, media_type: str = "both"):
        return await populate_database(background_tasks, media_type, dependencies)

    @app.get("/api/populate/status")
    async def _populate_status():
        return await get_populate_status()

    @app.post("/tv/scan-season")
    async def _scan_tv_season(background_tasks: BackgroundTasks, request: TVSeasonRequest):
        return await scan_tv_season(background_tasks, request, dependencies)

    @app.post("/tv/scan-episode")
    async def _scan_tv_episode(background_tasks: BackgroundTasks, request: TVEpisodeRequest):
        return await scan_tv_episode(background_tasks, request, dependencies)

    @app.post("/test/bulk-update")
    async def _test_bulk_update():
        return await test_bulk_update(dependencies)

    @app.post("/test/movie-scan")
    async def _test_movie_scan():
        return await test_movie_scan(dependencies)

    @app.post("/bulk/update")
    async def _trigger_bulk_update(background_tasks: BackgroundTasks):
        return await trigger_bulk_update(background_tasks, dependencies)

    @app.get("/debug/movie/{imdb_id}/priority")
    async def _debug_movie_priority_logic(imdb_id: str):
        return await debug_movie_priority_logic(imdb_id, dependencies)

    @app.get("/debug/tmdb/{imdb_id}")
    async def _debug_tmdb_lookup(imdb_id: str):
        return await debug_tmdb_lookup(imdb_id, dependencies)

    # ---------------------------
    # Emby Plugin Lookup Endpoints
    # ---------------------------
    
    @app.get("/api/lookup/episode/{imdb_id}/{season}/{episode}")
    async def _lookup_episode(imdb_id: str, season: int, episode: int):
        return await lookup_episode(imdb_id, season, episode, dependencies)
    
    @app.get("/api/lookup/movie/{imdb_id}")
    async def _lookup_movie(imdb_id: str):
        return await lookup_movie(imdb_id, dependencies)
    
    @app.get("/api/lookup/movie/title/{title}")
    async def _lookup_movie_by_title(title: str, year: str = None):
        return await lookup_movie_by_title(title, year, dependencies)
    
    @app.post("/api/lookup/movie/path")
    async def _lookup_movie_by_path(request: Request):
        data = await request.json()
        nfo_path = data.get("nfo_path")
        if not nfo_path:
            raise HTTPException(status_code=400, detail="nfo_path required")
        return await lookup_movie_comprehensive(nfo_path, dependencies)
    
    @app.get("/api/debug/movie/{title}")
    async def _debug_movie_lookup(title: str):
        """Debug endpoint to check what movies exist for a given title"""
        db = dependencies.get("db")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT imdb_id, title, dateadded, source FROM movies WHERE LOWER(title) LIKE LOWER(%s)", (f"%{title}%",))
            movies = cursor.fetchall()
            return {"title_search": title, "matches": [dict(row) for row in movies]}

    # Include monitoring routes
    from api.monitoring_routes import router as monitoring_router
    app.include_router(monitoring_router)
    
    # ---------------------------
    # Web Interface Moved to Separate Container  
    # ---------------------------
    # Web interface routes have been moved to the chronarr-web container
    # for performance isolation. The core container only handles:
    # - Webhooks (/webhook/*)
    # - Manual scans (/manual/*)  
    # - Database operations (/database/*)
    # - Health checks (/health)
    # 
    # Web interface available on separate container port 8081
    
    async def nfo_repair_scan():
        """Scan filesystem for episodes/movies missing dateadded elements in NFO files"""
        import os
        import xml.etree.ElementTree as ET
        
        config = dependencies.get("config")
        db = dependencies.get("db")
        
        if not config or not db:
            raise HTTPException(status_code=500, detail=f"Dependencies not available - config:{config is not None}, db:{db is not None}")
        
        print("🔧 Starting NFO repair scan from core container")
        
        import time
        scan_start_time = time.time()
        
        missing_items = {
            "episodes": [],
            "movies": []
        }
        
        # Track total files processed for statistics
        total_tv_files_checked = 0
        total_movie_files_checked = 0
        
        try:
            # Use filesystem-first approach: find all NFO files missing dateadded
            print("📺 Scanning NFO files directly for missing dateadded elements")
            
            # Get TV and Movie library paths from config  
            tv_path = getattr(config, 'tv_library_path', '/media/TV')
            movie_path = getattr(config, 'movie_library_path', '/media/Movies') 
            
            print(f"📁 Scanning TV path: {tv_path}")
            print(f"📁 Scanning Movie path: {movie_path}")
            
            import subprocess
            import re
            
            # Separate tracking for TV and movie missing files
            missing_tv_nfo_files = []
            missing_movie_nfo_files = []
            
            # Find all NFO files in TV directory
            if os.path.exists(tv_path):
                print("🔍 Finding all TV NFO files...")
                try:
                    # Use find to get all NFO files
                    find_result = subprocess.run(
                        ['find', tv_path, '-name', '*.nfo', '-type', 'f'],
                        capture_output=True, text=True, timeout=60
                    )
                    
                    if find_result.returncode == 0:
                        tv_nfo_files = find_result.stdout.strip().split('\n')
                        tv_nfo_files = [f for f in tv_nfo_files if f]  # Remove empty strings
                        print(f"📊 Found {len(tv_nfo_files)} TV NFO files")
                        
                        # Check each NFO file for missing dateadded
                        for i, nfo_file in enumerate(tv_nfo_files):
                            total_tv_files_checked = i + 1  # Track progress
                            
                            if i % 1000 == 0 and i > 0:
                                elapsed = time.time() - scan_start_time
                                print(f"📊 Progress: {i}/{len(tv_nfo_files)} TV NFO files checked in {elapsed:.1f}s, {len(missing_tv_nfo_files)} missing found")
                            
                            # Timeout check
                            if time.time() - scan_start_time > 180:  # 3 minutes
                                print(f"⏰ TV NFO scan timeout after 3 minutes - checked {i}/{len(tv_nfo_files)} files")
                                break
                            
                            try:
                                # Use grep to quickly check if dateadded exists
                                grep_result = subprocess.run(
                                    ['grep', '-l', '<dateadded>', nfo_file],
                                    capture_output=True, text=True, timeout=5
                                )
                                
                                # If grep returns non-zero, dateadded is missing
                                if grep_result.returncode != 0:
                                    missing_tv_nfo_files.append(nfo_file)
                                    
                                    # Log specific files we're looking for
                                    if 'Hudson' in nfo_file and 'S08E05' in nfo_file:
                                        print(f"🔍 FOUND MISSING: Hudson & Rex S08E05 at {nfo_file}")
                                    if 'Star Trek' in nfo_file and 'S03E07' in nfo_file:
                                        print(f"🔍 FOUND MISSING: Star Trek SNW S03E07 at {nfo_file}")
                                        
                            except subprocess.TimeoutExpired:
                                print(f"⏰ Timeout checking {nfo_file}")
                                continue
                            except Exception as e:
                                print(f"⚠️ Error checking {nfo_file}: {e}")
                                continue
                                
                    else:
                        print(f"❌ Error finding TV NFO files: {find_result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    print("⏰ Find command timeout for TV files")
                except Exception as e:
                    print(f"❌ Error scanning TV directory: {e}")
            else:
                print(f"❌ TV path does not exist: {tv_path}")
            
            print(f"📊 Found {len(missing_tv_nfo_files)} TV NFO files missing dateadded elements")
            
            # Convert TV file paths to episode information with direct NFO parsing
            def extract_imdb_from_nfo_content(nfo_file, is_episode=True, verbose_logging=True):
                """Extract IMDb ID directly from NFO file content - we already know the file exists"""
                imdb_id = "unknown"
                
                try:
                    # Try to parse the NFO file we already know exists (since grep found it missing dateadded)
                    tree = ET.parse(nfo_file)
                    root = tree.getroot()
                    
                    # Method 1: Check <imdb> tag
                    imdb_elem = root.find("imdb")
                    if imdb_elem is not None and imdb_elem.text:
                        imdb_text = imdb_elem.text.strip()
                        if imdb_text.startswith('tt'):
                            if verbose_logging:
                                print(f"✅ Found IMDb {imdb_text} in <imdb> tag: {os.path.basename(nfo_file)}")
                            return imdb_text
                    
                    # Method 2: Check <uniqueid type="imdb"> tags
                    for uniqueid in root.findall("uniqueid"):
                        if uniqueid.get("type") == "imdb" and uniqueid.text:
                            imdb_text = uniqueid.text.strip()
                            if imdb_text.startswith('tt'):
                                if verbose_logging:
                                    print(f"✅ Found IMDb {imdb_text} in <uniqueid type='imdb'>: {os.path.basename(nfo_file)}")
                                return imdb_text
                    
                    # Method 3: Check for IMDb pattern anywhere in NFO content
                    nfo_content = ET.tostring(root, encoding='unicode')
                    content_match = re.search(r'(tt\d{7,})', nfo_content)
                    if content_match:
                        imdb_text = content_match.group(1)
                        if verbose_logging:
                            print(f"✅ Found IMDb {imdb_text} in NFO content: {os.path.basename(nfo_file)}")
                        return imdb_text
                
                except ET.ParseError as e:
                    # Handle malformed XML by trying text-based search
                    if verbose_logging:
                        print(f"⚠️ NFO XML parse error in {os.path.basename(nfo_file)}: {e}")
                    try:
                        # Fallback: Read as text and search for IMDb patterns
                        with open(nfo_file, 'r', encoding='utf-8', errors='ignore') as f:
                            nfo_text = f.read()
                            
                        # Search for IMDb patterns in raw text
                        text_match = re.search(r'(tt\d{7,})', nfo_text)
                        if text_match:
                            imdb_text = text_match.group(1)
                            if verbose_logging:
                                print(f"✅ Found IMDb {imdb_text} in NFO text content: {os.path.basename(nfo_file)}")
                            return imdb_text
                    except Exception as text_error:
                        if verbose_logging:
                            print(f"⚠️ Error reading NFO as text {nfo_file}: {text_error}")
                        
                except Exception as e:
                    if verbose_logging:
                        print(f"⚠️ Unexpected error parsing NFO {nfo_file}: {e}")
                
                # Method 4: Fallback - check folder structure 
                if is_episode:
                    series_folder = os.path.dirname(os.path.dirname(nfo_file))
                    folder_name = os.path.basename(series_folder)
                    folder_match = re.search(r'\[imdb-(tt\d+)\]', folder_name, re.IGNORECASE)
                    if folder_match:
                        if verbose_logging:
                            print(f"✅ Found IMDb {folder_match.group(1)} in folder: {folder_name}")
                        return folder_match.group(1)
                else:
                    # For movies, check movie folder
                    movie_folder = os.path.dirname(nfo_file)
                    folder_name = os.path.basename(movie_folder)
                    folder_match = re.search(r'\[imdb-(tt\d+)\]', folder_name, re.IGNORECASE)
                    if folder_match:
                        if verbose_logging:
                            print(f"✅ Found IMDb {folder_match.group(1)} in folder: {folder_name}")
                        return folder_match.group(1)
                
                if verbose_logging:
                    print(f"❌ No IMDb ID found in {os.path.basename(nfo_file)}")
                return "unknown"
            
            for nfo_file in missing_tv_nfo_files:
                try:
                    # Parse episode info from file path
                    # Example: /media/TV/tv/Hudson & Rex (2019) [imdb-tt9111220]/Season 08/Hudson & Rex (2019)-S08E05-Episode.nfo
                    path_parts = nfo_file.split('/')
                    
                    # Look for season/episode pattern
                    season_match = re.search(r'Season\s+(\d+)', nfo_file, re.IGNORECASE)
                    episode_match = re.search(r'S(\d+)E(\d+)', os.path.basename(nfo_file), re.IGNORECASE)
                    
                    if season_match and episode_match:
                        season = int(episode_match.group(1))
                        episode = int(episode_match.group(2))
                        
                        # Extract series name and path
                        series_path = os.path.dirname(os.path.dirname(nfo_file))
                        series_name = os.path.basename(series_path)
                        
                        # Extract IMDb ID from NFO content
                        imdb_id = extract_imdb_from_nfo_content(nfo_file, is_episode=True)
                        
                        # Clean series name (remove year and imdb parts)
                        clean_series_name = re.sub(r'\s*\(\d{4}\)\s*\[imdb-[^]]+\]', '', series_name).strip()
                        
                        missing_items["episodes"].append({
                            "imdb_id": imdb_id,
                            "season": season,
                            "episode": episode,
                            "series_name": clean_series_name,
                            "series_path": series_path,
                            "dateadded": None,
                            "nfo_path": nfo_file,
                            "reason": "NFO missing dateadded element (filesystem scan)"
                        })
                        
                except Exception as e:
                    print(f"⚠️ Error parsing NFO file path {nfo_file}: {e}")
                    continue
        
            # Scan movies using filesystem grep approach
            print("🎬 Scanning movie NFO files for missing dateadded elements")
            
            # Find all NFO files in Movie directory
            if os.path.exists(movie_path):
                print(f"🔍 Finding all Movie NFO files in {movie_path}...")
                try:
                    # Use find to get all NFO files
                    find_result = subprocess.run(
                        ['find', movie_path, '-name', '*.nfo', '-type', 'f'],
                        capture_output=True, text=True, timeout=60
                    )
                    
                    if find_result.returncode == 0:
                        movie_nfo_files = find_result.stdout.strip().split('\n')
                        movie_nfo_files = [f for f in movie_nfo_files if f]  # Remove empty strings
                        print(f"📊 Found {len(movie_nfo_files)} Movie NFO files")
                        
                        # Check each NFO file for missing dateadded
                        for i, nfo_file in enumerate(movie_nfo_files):
                            total_movie_files_checked = i + 1  # Track progress
                            
                            if i % 500 == 0 and i > 0:
                                elapsed = time.time() - scan_start_time
                                print(f"📊 Progress: {i}/{len(movie_nfo_files)} Movie NFO files checked in {elapsed:.1f}s, {len(missing_movie_nfo_files)} missing found")
                            
                            # Timeout check
                            if time.time() - scan_start_time > 300:  # 5 minutes total
                                print(f"⏰ Movie NFO scan timeout after 5 minutes - checked {i}/{len(movie_nfo_files)} files")
                                break
                            
                            try:
                                # Use grep to quickly check if dateadded exists
                                grep_result = subprocess.run(
                                    ['grep', '-l', '<dateadded>', nfo_file],
                                    capture_output=True, text=True, timeout=5
                                )
                                
                                # If grep returns non-zero, dateadded is missing
                                if grep_result.returncode != 0:
                                    missing_movie_nfo_files.append(nfo_file)
                                        
                            except subprocess.TimeoutExpired:
                                print(f"⏰ Timeout checking {nfo_file}")
                                continue
                            except Exception as e:
                                print(f"⚠️ Error checking {nfo_file}: {e}")
                                continue
                                
                    else:
                        print(f"❌ Error finding Movie NFO files: {find_result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    print("⏰ Find command timeout for Movie files")
                except Exception as e:
                    print(f"❌ Error scanning Movie directory: {e}")
            else:
                print(f"❌ Movie path does not exist: {movie_path}")
            
            # Process missing movie NFO files
            print(f"📊 Found {len(missing_movie_nfo_files)} Movie NFO files missing dateadded elements")
            
            print(f"🎬 Processing {len(missing_movie_nfo_files)} movie NFO files for detailed information...")
            for i, nfo_file in enumerate(missing_movie_nfo_files):
                print(f"  📁 Movie {i+1}/{len(missing_movie_nfo_files)}: {nfo_file}")
                try:
                    # Extract movie info from file path
                    # Example: /media/Movies/movies/Knives Out (2019) [imdb-tt8946378]/movie.nfo
                    movie_dir = os.path.dirname(nfo_file)
                    movie_folder_name = os.path.basename(movie_dir)
                    
                    # Extract IMDb ID from NFO content
                    imdb_id = extract_imdb_from_nfo_content(nfo_file, is_episode=False, verbose_logging=False)
                    
                    # Clean movie title (remove year and imdb parts)
                    clean_movie_title = re.sub(r'\s*\(\d{4}\)\s*\[imdb-[^]]+\]', '', movie_folder_name).strip()
                    
                    # Log detailed movie information
                    if imdb_id != "unknown":
                        print(f"✅ Found IMDb {imdb_id} for movie: {clean_movie_title} ({movie_folder_name})")
                    else:
                        print(f"❌ No IMDb ID found for movie: {clean_movie_title} ({movie_folder_name})")
                        print(f"   📁 Path: {movie_dir}")
                        print(f"   📄 NFO: {os.path.basename(nfo_file)}")
                    
                    missing_items["movies"].append({
                        "imdb_id": imdb_id,
                        "title": clean_movie_title,
                        "path": movie_dir,
                        "dateadded": None,
                        "nfo_path": nfo_file,
                        "reason": "NFO missing dateadded element (filesystem scan)"
                    })
                except Exception as e:
                    print(f"⚠️ Error parsing movie NFO file path {nfo_file}: {e}")
                    continue
            
            # Database lookup to get actual dateadded values for missing items
            print("🔍 Looking up dateadded values from database for missing items...")
            
            # Enhance episodes with database data
            episodes_with_dates = 0
            episodes_missing_db = 0
            
            for episode in missing_items["episodes"]:
                if episode["imdb_id"] != "unknown":
                    try:
                        with db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                SELECT dateadded, source
                                FROM episodes 
                                WHERE imdb_id = %s AND season = %s AND episode = %s
                                LIMIT 1
                            """, (episode["imdb_id"], episode["season"], episode["episode"]))
                            
                            result = cursor.fetchone()
                            if result:
                                episode["dateadded"] = result["dateadded"]
                                episode["source"] = result.get("source", "database")
                                episodes_with_dates += 1
                                print(f"✅ Found database date for {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d}: {result['dateadded']}")
                            else:
                                episodes_missing_db += 1
                                # Try to find other episodes from same series to estimate date
                                cursor.execute("""
                                    SELECT dateadded, season, episode
                                    FROM episodes 
                                    WHERE imdb_id = %s AND dateadded IS NOT NULL
                                    ORDER BY season DESC, episode DESC
                                    LIMIT 3
                                """, (episode["imdb_id"],))
                                
                                similar_episodes = cursor.fetchall()
                                if similar_episodes:
                                    latest_date = similar_episodes[0]["dateadded"]
                                    episode["dateadded"] = latest_date
                                    episode["source"] = f"estimated_from_series_latest"
                                    print(f"🔮 Estimated date for {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d} from latest episode: {latest_date}")
                                else:
                                    # Use NFO file modification time as fallback
                                    try:
                                        import os
                                        from datetime import datetime
                                        if os.path.exists(episode["nfo_path"]):
                                            file_mtime = os.path.getmtime(episode["nfo_path"])
                                            file_date = datetime.fromtimestamp(file_mtime)
                                            episode["dateadded"] = file_date
                                            episode["source"] = "nfo_file_mtime"
                                            print(f"📅 Using NFO file date for {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d}: {file_date}")
                                        else:
                                            print(f"❌ No fallback date available for {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d}")
                                    except Exception as fallback_error:
                                        print(f"⚠️ Fallback date lookup failed for {episode['imdb_id']}: {fallback_error}")
                    except Exception as e:
                        print(f"⚠️ Database lookup failed for episode {episode['imdb_id']}: {e}")
            
            # Enhance movies with database data  
            movies_with_dates = 0
            movies_missing_db = 0
            
            for movie in missing_items["movies"]:
                if movie["imdb_id"] != "unknown":
                    try:
                        with db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                SELECT dateadded, source
                                FROM movies 
                                WHERE imdb_id = %s
                                LIMIT 1
                            """, (movie["imdb_id"],))
                            
                            result = cursor.fetchone()
                            if result:
                                movie["dateadded"] = result["dateadded"]
                                movie["source"] = result.get("source", "database")
                                movies_with_dates += 1
                                print(f"✅ Found database date for movie {movie['imdb_id']}: {result['dateadded']}")
                            else:
                                movies_missing_db += 1
                                # Use NFO file modification time as fallback for movies
                                try:
                                    import os
                                    from datetime import datetime
                                    if os.path.exists(movie["nfo_path"]):
                                        file_mtime = os.path.getmtime(movie["nfo_path"])
                                        file_date = datetime.fromtimestamp(file_mtime)
                                        movie["dateadded"] = file_date
                                        movie["source"] = "nfo_file_mtime"
                                        print(f"📅 Using NFO file date for movie {movie['imdb_id']}: {file_date}")
                                    else:
                                        print(f"❌ No fallback date available for movie {movie['imdb_id']}")
                                except Exception as fallback_error:
                                    print(f"⚠️ Fallback date lookup failed for movie {movie['imdb_id']}: {fallback_error}")
                    except Exception as e:
                        print(f"⚠️ Database lookup failed for movie {movie['imdb_id']}: {e}")
            
            # Print summary statistics
            total_episodes = len(missing_items["episodes"])
            total_movies = len(missing_items["movies"])
            print(f"📊 Database lookup summary:")
            print(f"   Episodes: {episodes_with_dates}/{total_episodes} found in DB, {episodes_missing_db} missing from DB")
            print(f"   Movies: {movies_with_dates}/{total_movies} found in DB, {movies_missing_db} missing from DB")
            
            # Calculate comprehensive statistics
            total_nfo_files_missing = len(missing_tv_nfo_files) + len(missing_movie_nfo_files)
            total_with_imdb_and_db = len(missing_items["episodes"]) + len(missing_items["movies"])
            
            print(f"✅ NFO repair scan complete:")
            print(f"   📄 {total_nfo_files_missing} NFO files missing dateadded elements")
            print(f"   🎬 {len(missing_tv_nfo_files)} TV episodes, {len(missing_movie_nfo_files)} movies")
            print(f"   🔍 {total_with_imdb_and_db} items with IMDb IDs found in database (can be fixed)")
            
            return {
                "status": "success",
                "total_missing": total_with_imdb_and_db,  # Items that can be fixed
                "total_nfo_files_missing": total_nfo_files_missing,  # All NFO files missing dateadded
                "episodes_missing": len(missing_items["episodes"]),
                "movies_missing": len(missing_items["movies"]),
                "tv_nfo_files_missing": len(missing_tv_nfo_files),
                "movie_nfo_files_missing": len(missing_movie_nfo_files),
                "total_tv_files_checked": total_tv_files_checked,
                "total_movie_files_checked": total_movie_files_checked,
                "missing_items": missing_items,
                "statistics": {
                    "nfo_files_scanned": {
                        "tv": total_tv_files_checked,
                        "movies": total_movie_files_checked,
                        "total": total_tv_files_checked + total_movie_files_checked
                    },
                    "nfo_files_missing_dateadded": {
                        "tv": len(missing_tv_nfo_files),
                        "movies": len(missing_movie_nfo_files),
                        "total": total_nfo_files_missing
                    },
                    "items_with_imdb_and_database": {
                        "tv": len(missing_items["episodes"]),
                        "movies": len(missing_items["movies"]),
                        "total": total_with_imdb_and_db
                    }
                }
            }
            
        except Exception as e:
            print(f"❌ Error during NFO repair scan: {str(e)}")
            raise HTTPException(status_code=500, detail=f"NFO repair scan failed: {str(e)}")

    @app.get("/admin/nfo-repair-scan")
    async def _nfo_repair_scan():
        return await nfo_repair_scan()

    async def nfo_repair_fix():
        """Fix missing dateadded elements in NFO files using database values"""
        import os
        import xml.etree.ElementTree as ET
        from datetime import datetime
        
        config = dependencies.get("config")
        db = dependencies.get("db")
        nfo_manager = dependencies.get("nfo_manager")
        
        if not config or not db:
            raise HTTPException(status_code=500, detail=f"Dependencies not available")
        
        print("🔧 Starting NFO repair fix process from core container")
        
        # First, run the scan to identify missing items
        scan_result = await nfo_repair_scan()
        if scan_result["status"] != "success":
            return {"status": "error", "message": "Scan failed"}
        
        missing_items = scan_result["missing_items"]
        total_episodes = len(missing_items["episodes"])
        total_movies = len(missing_items["movies"])
        
        print(f"🔍 Found {total_episodes} episodes and {total_movies} movies to fix")
        
        fixed_count = 0
        failed_count = 0
        results = []
        
        # Fix episodes
        for episode in missing_items["episodes"]:
            if episode.get("dateadded") and episode.get("imdb_id") != "unknown":
                try:
                    nfo_path = episode["nfo_path"]
                    dateadded_value = episode["dateadded"]
                    
                    # Format dateadded for NFO file
                    if isinstance(dateadded_value, str):
                        # Parse string datetime  
                        dt = datetime.fromisoformat(dateadded_value.replace('Z', '+00:00'))
                    else:
                        dt = dateadded_value
                    
                    # Format as NFO expects: 2024-10-15 12:34:56
                    nfo_dateadded = dt.strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Read and modify NFO file
                    if os.path.exists(nfo_path):
                        tree = ET.parse(nfo_path)
                        root = tree.getroot()
                        
                        # Remove existing dateadded element if present
                        existing = root.find("dateadded")
                        if existing is not None:
                            root.remove(existing)
                        
                        # Add new dateadded element
                        dateadded_elem = ET.SubElement(root, "dateadded")
                        dateadded_elem.text = nfo_dateadded
                        
                        # Add source attribution (similar to what Chronarr normally adds)
                        # Check if source element exists, if not create it
                        source_elem = root.find("source")
                        if source_elem is None:
                            source_elem = ET.SubElement(root, "source")
                        source_elem.text = f"Chronarr repair - {episode.get('source', 'database')}"
                        
                        # Add addedby attribution if not present
                        addedby_elem = root.find("addedby")
                        if addedby_elem is None:
                            addedby_elem = ET.SubElement(root, "addedby")
                        addedby_elem.text = "Chronarr"
                        
                        # Write back to file
                        tree.write(nfo_path, encoding='utf-8', xml_declaration=True)
                        
                        # VERIFY the write was successful by re-reading the file
                        try:
                            verify_tree = ET.parse(nfo_path)
                            verify_root = verify_tree.getroot()
                            verify_dateadded = verify_root.find("dateadded")
                            
                            if verify_dateadded is not None and verify_dateadded.text and verify_dateadded.text.strip():
                                # Verification successful
                                fixed_count += 1
                                results.append({
                                    "type": "episode",
                                    "imdb_id": episode["imdb_id"], 
                                    "season": episode["season"],
                                    "episode": episode["episode"],
                                    "nfo_path": nfo_path,
                                    "dateadded": nfo_dateadded,
                                    "verified_dateadded": verify_dateadded.text.strip(),
                                    "status": "fixed_and_verified"
                                })
                                print(f"✅ Fixed and verified episode {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d}")
                            else:
                                # Verification failed - dateadded missing after write
                                failed_count += 1
                                results.append({
                                    "type": "episode",
                                    "imdb_id": episode["imdb_id"], 
                                    "season": episode["season"],
                                    "episode": episode["episode"],
                                    "nfo_path": nfo_path,
                                    "dateadded": nfo_dateadded,
                                    "status": "write_failed_verification"
                                })
                                print(f"❌ Write verification FAILED for episode {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d} - dateadded not found after write")
                        except Exception as verify_error:
                            # Verification failed due to parse error
                            failed_count += 1
                            results.append({
                                "type": "episode",
                                "imdb_id": episode["imdb_id"], 
                                "season": episode["season"],
                                "episode": episode["episode"],
                                "nfo_path": nfo_path,
                                "status": "verification_parse_error",
                                "error": str(verify_error)
                            })
                            print(f"❌ Verification parse error for episode {episode['imdb_id']} S{episode['season']:02d}E{episode['episode']:02d}: {verify_error}")
                    else:
                        failed_count += 1
                        print(f"❌ NFO file not found: {nfo_path}")
                        
                except Exception as e:
                    failed_count += 1
                    print(f"❌ Failed to fix episode {episode.get('imdb_id', 'unknown')}: {e}")
        
        # Fix movies
        for movie in missing_items["movies"]:
            if movie.get("dateadded") and movie.get("imdb_id") != "unknown":
                try:
                    nfo_path = movie["nfo_path"]
                    dateadded_value = movie["dateadded"]
                    
                    # Format dateadded for NFO file
                    if isinstance(dateadded_value, str):
                        dt = datetime.fromisoformat(dateadded_value.replace('Z', '+00:00'))
                    else:
                        dt = dateadded_value
                    
                    nfo_dateadded = dt.strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Read and modify NFO file
                    if os.path.exists(nfo_path):
                        tree = ET.parse(nfo_path)
                        root = tree.getroot()
                        
                        # Remove existing dateadded element if present
                        existing = root.find("dateadded")
                        if existing is not None:
                            root.remove(existing)
                        
                        # Add new dateadded element
                        dateadded_elem = ET.SubElement(root, "dateadded")
                        dateadded_elem.text = nfo_dateadded
                        
                        # Add source attribution (similar to what Chronarr normally adds)
                        source_elem = root.find("source")
                        if source_elem is None:
                            source_elem = ET.SubElement(root, "source")
                        source_elem.text = f"Chronarr repair - {movie.get('source', 'database')}"
                        
                        # Add addedby attribution if not present
                        addedby_elem = root.find("addedby")
                        if addedby_elem is None:
                            addedby_elem = ET.SubElement(root, "addedby")
                        addedby_elem.text = "Chronarr"
                        
                        # Write back to file
                        tree.write(nfo_path, encoding='utf-8', xml_declaration=True)
                        
                        # VERIFY the write was successful by re-reading the file
                        try:
                            verify_tree = ET.parse(nfo_path)
                            verify_root = verify_tree.getroot()
                            verify_dateadded = verify_root.find("dateadded")
                            
                            if verify_dateadded is not None and verify_dateadded.text and verify_dateadded.text.strip():
                                # Verification successful
                                fixed_count += 1
                                results.append({
                                    "type": "movie",
                                    "imdb_id": movie["imdb_id"],
                                    "title": movie["title"],
                                    "nfo_path": nfo_path,
                                    "dateadded": nfo_dateadded,
                                    "verified_dateadded": verify_dateadded.text.strip(),
                                    "status": "fixed_and_verified"
                                })
                                print(f"✅ Fixed and verified movie {movie['imdb_id']} ({movie['title']})")
                            else:
                                # Verification failed - dateadded missing after write
                                failed_count += 1
                                results.append({
                                    "type": "movie",
                                    "imdb_id": movie["imdb_id"],
                                    "title": movie["title"],
                                    "nfo_path": nfo_path,
                                    "dateadded": nfo_dateadded,
                                    "status": "write_failed_verification"
                                })
                                print(f"❌ Write verification FAILED for movie {movie['imdb_id']} ({movie['title']}) - dateadded not found after write")
                        except Exception as verify_error:
                            # Verification failed due to parse error
                            failed_count += 1
                            results.append({
                                "type": "movie",
                                "imdb_id": movie["imdb_id"],
                                "title": movie["title"],
                                "nfo_path": nfo_path,
                                "status": "verification_parse_error",
                                "error": str(verify_error)
                            })
                            print(f"❌ Verification parse error for movie {movie['imdb_id']} ({movie['title']}): {verify_error}")
                    else:
                        failed_count += 1
                        print(f"❌ NFO file not found: {nfo_path}")
                        
                except Exception as e:
                    failed_count += 1
                    print(f"❌ Failed to fix movie {movie.get('imdb_id', 'unknown')}: {e}")
        
        print(f"✅ NFO repair fix complete: {fixed_count} fixed, {failed_count} failed")
        
        # Final summary with detailed statistics
        verification_summary = {
            "fixed_and_verified": sum(1 for r in results if r.get("status") == "fixed_and_verified"),
            "write_failed_verification": sum(1 for r in results if r.get("status") == "write_failed_verification"),
            "verification_parse_error": sum(1 for r in results if r.get("status") == "verification_parse_error")
        }
        
        print(f"📊 Final summary: {fixed_count} fixed, {failed_count} failed")
        print(f"   ✅ Verified successful: {verification_summary['fixed_and_verified']}")
        print(f"   ❌ Write verification failed: {verification_summary['write_failed_verification']}")
        print(f"   ⚠️ Verification parse errors: {verification_summary['verification_parse_error']}")
        
        return {
            "status": "success",
            "total_processed": total_episodes + total_movies,
            "fixed_count": fixed_count,
            "failed_count": failed_count,
            "verification_summary": verification_summary,
            "results": results[:20]  # Show first 20 for UI
        }

    @app.post("/admin/nfo-repair-fix")
    async def _nfo_repair_fix():
        return await nfo_repair_fix()

    @app.get("/admin/missing-imdb")
    async def get_missing_imdb():
        """Get items missing IMDb IDs for manual review"""
        config = dependencies.get("config")
        db = dependencies.get("db")
        
        if not config or not db:
            raise HTTPException(status_code=500, detail="Dependencies not available")
        
        print("📋 Retrieving missing IMDb items from core container")
        
        try:
            # Get missing items by type
            missing_tv = db.get_missing_imdb_items(media_type="tv", resolved=False)
            missing_movies = db.get_missing_imdb_items(media_type="movie", resolved=False)
            
            # Format for web interface
            missing_items = []
            
            for item in missing_tv:
                missing_items.append({
                    "id": item["id"],
                    "type": "TV Series",
                    "folder_name": item["folder_name"],
                    "file_path": item["file_path"],
                    "discovered_at": item["discovered_at"].isoformat() if item["discovered_at"] else None,
                    "last_checked": item["last_checked"].isoformat() if item["last_checked"] else None,
                    "check_count": item["check_count"],
                    "notes": item["notes"]
                })
            
            for item in missing_movies:
                missing_items.append({
                    "id": item["id"],
                    "type": "Movie",
                    "folder_name": item["folder_name"],
                    "file_path": item["file_path"],
                    "discovered_at": item["discovered_at"].isoformat() if item["discovered_at"] else None,
                    "last_checked": item["last_checked"].isoformat() if item["last_checked"] else None,
                    "check_count": item["check_count"],
                    "notes": item["notes"]
                })
            
            print(f"✅ Found {len(missing_tv)} TV series and {len(missing_movies)} movies missing IMDb IDs")
            
            return {
                "status": "success",
                "missing_items": missing_items,
                "summary": {
                    "total_missing": len(missing_items),
                    "tv_series": len(missing_tv),
                    "movies": len(missing_movies)
                }
            }
            
        except Exception as e:
            print(f"❌ Error retrieving missing IMDb items: {e}")
            return {
                "status": "error",
                "message": f"Failed to retrieve missing IMDb items: {str(e)}"
            }

    # ---------------------------
    # Core API - No Web Interface
    # ---------------------------
    
    @app.get("/")
    async def _core_info():
        """Core container API information - Web interface on separate container"""
        import os
        # Get configured web port from environment or config
        web_port = os.environ.get("WEB_EXTERNAL_PORT",
                  getattr(dependencies.get("config", None), "web_api_port", "8081"))
        # Get version from dependencies
        version = dependencies.get("version", "unknown")

        return {
            "service": "Chronarr Core Processing Engine",
            "version": version,
            "message": f"Web interface available on separate container (port {web_port})",
            "api_endpoints": {
                "health": "/health",
                "webhooks": "/webhook/*",
                "manual_scans": "/manual/*",
                "database": "/database/*",
                "api_docs": "/docs"
            }
        }