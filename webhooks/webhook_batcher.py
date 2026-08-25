"""
Webhook Batching System for Chronarr
Handles batching and processing of webhook events to avoid processing storms
"""
import threading
import time
from pathlib import Path
from typing import Dict, Set
from concurrent.futures import ThreadPoolExecutor

from config.settings import config
from utils.logging import _log
from utils.imdb_utils import find_imdb_in_directory, parse_imdb_from_path  # Phase 3: Replaced NFOManager


class WebhookBatcher:
    """Batches webhook events to avoid processing storms"""

    def __init__(self, nfo_manager=None):
        # nfo_manager parameter kept for backward compatibility but no longer used (Phase 3)
        self.pending: Dict[str, Dict] = {}
        self.timers: Dict[str, threading.Timer] = {}
        self.processing: Set[str] = set()
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=config.max_concurrent)
        # Will be set by the application when processors are available
        self.tv_processor = None
        self.movie_processor = None
    
    def set_processors(self, tv_processor, movie_processor):
        """Set the processor instances"""
        self.tv_processor = tv_processor
        self.movie_processor = movie_processor
    
    def add_webhook(self, key: str, webhook_data: Dict, media_type: str):
        """Add webhook to batch queue"""
        with self.lock:
            if key in self.timers:
                self.timers[key].cancel()

            webhook_data['media_type'] = media_type

            # Accumulate episodes for same-series webhooks that arrive within the batch window.
            # Without this, each incoming webhook overwrites the previous one and only the last
            # episode in the batch window gets processed — silently dropping the rest.
            if key in self.pending and webhook_data.get('episodes'):
                existing_eps = self.pending[key].get('episodes', [])
                seen = {(e.get('seasonNumber'), e.get('episodeNumber')) for e in existing_eps}
                for ep in webhook_data['episodes']:
                    if (ep.get('seasonNumber'), ep.get('episodeNumber')) not in seen:
                        existing_eps.append(ep)
                        seen.add((ep.get('seasonNumber'), ep.get('episodeNumber')))
                webhook_data['episodes'] = existing_eps

            self.pending[key] = webhook_data
            _log("INFO", f"Batched {media_type} webhook for {key} ({len(webhook_data.get('episodes', []))} episode(s) pending)")
            _log("DEBUG", f"Batch added - key: {key}, media_type: {media_type}, timer scheduled for {config.batch_delay}s")

            timer = threading.Timer(config.batch_delay, self._process_item, args=[key])
            self.timers[key] = timer
            timer.start()
    
    def _process_item(self, key: str):
        """Process a batched item"""
        with self.lock:
            if key not in self.pending:
                return
            if key in self.processing:
                # Previous batch for this key is still running — re-schedule so accumulated
                # episode data isn't stranded with no timer and no processor to pick it up.
                _log("DEBUG", f"Batch item {key} still processing, re-scheduling in {config.batch_delay}s")
                timer = threading.Timer(config.batch_delay, self._process_item, args=[key])
                self.timers[key] = timer
                timer.start()
                return
            self.processing.add(key)
            webhook_data = self.pending.pop(key)
            self.timers.pop(key, None)
        
        try:
            self.executor.submit(self._process_sync, key, webhook_data)
        except Exception as e:
            _log("ERROR", f"Error submitting processing for {key}: {e}")
            with self.lock:
                self.processing.discard(key)
    
    def _process_sync(self, key: str, webhook_data: Dict):
        """Synchronous processing of webhook data with validation"""
        try:
            media_type = webhook_data.get('media_type')
            path_str = webhook_data.get('path')
            
            _log("DEBUG", f"Processing batch item: key={key}, media_type={media_type}, path={path_str}")
            
            if not path_str:
                _log("ERROR", f"No path found for {media_type} {key}")
                return
            
            path_obj = Path(path_str)
            if not path_obj.exists():
                _log("ERROR", f"BATCH PROCESSING FAILED: Path does not exist: {path_obj}")
                _log("ERROR", f"This indicates a path mapping issue - webhook rejected to prevent wrong processing")
                return
            
            # Validate IMDb ID for movies — only reject if a conflicting ID is found.
            # Standard Radarr folder naming (Movie Title (Year)) doesn't embed IMDb IDs,
            # so no detection is normal and not a reason to reject.
            if media_type == 'movie':
                expected_imdb = key.replace('movie:', '') if key.startswith('movie:') else key

                detected_imdb = find_imdb_in_directory(path_obj)
                if detected_imdb:
                    # An ID was found — check it matches
                    if detected_imdb == expected_imdb or detected_imdb.replace('tt', '') == expected_imdb.replace('tt', ''):
                        _log("DEBUG", f"Batch validation passed: IMDb {expected_imdb} confirmed in folder name")
                    else:
                        _log("ERROR", f"BATCH VALIDATION FAILED: folder contains {detected_imdb} but webhook expected {expected_imdb} in {path_str}")
                        _log("ERROR", f"This prevents processing the wrong movie due to a mismatched batch entry")
                        return
                else:
                    # No IMDb ID in folder/file names — standard naming, trust the webhook
                    _log("DEBUG", f"Batch validation: no IMDb in folder name for {path_str}, trusting webhook ID {expected_imdb}")

            # Validate IMDb ID for TV shows — same logic: conflict = reject, absent = proceed.
            if media_type == 'tv':
                expected_imdb = key.replace('tv:', '') if key.startswith('tv:') else key

                detected_imdb = parse_imdb_from_path(path_obj)
                if detected_imdb:
                    if detected_imdb == expected_imdb or detected_imdb.replace('tt', '') == expected_imdb.replace('tt', ''):
                        _log("DEBUG", f"TV batch validation passed: IMDb {expected_imdb} confirmed in folder name")
                    else:
                        _log("ERROR", f"BATCH VALIDATION FAILED: folder contains {detected_imdb} but webhook expected {expected_imdb} in TV {path_str}")
                        _log("ERROR", f"This prevents processing the wrong series due to a mismatched batch entry")
                        return
                else:
                    _log("DEBUG", f"TV batch validation: no IMDb in folder name for {path_str}, trusting webhook ID {expected_imdb}")
                
                if not self.tv_processor:
                    _log("ERROR", "TV processor not available")
                    return

                instance = webhook_data.get('instance', 'sonarr')
                processing_mode = webhook_data.get('processing_mode', config.tv_webhook_processing_mode)
                episodes_data = webhook_data.get('episodes', [])

                if processing_mode == 'targeted' and episodes_data:
                    _log("INFO", f"Using targeted episode processing for {len(episodes_data)} episodes")
                    if len(episodes_data) > 1 and config.sequential_delay > 0:
                        _log("INFO", f"Processing {len(episodes_data)} episodes sequentially with {config.sequential_delay}s delay")
                        self._process_episodes_sequentially(path_obj, episodes_data, instance=instance)
                    else:
                        self.tv_processor.process_webhook_episodes(path_obj, episodes_data, imdb_id=expected_imdb, instance=instance)
                else:
                    _log("INFO", f"Using series processing mode (fallback or configured)")
                    self.tv_processor.process_series(path_obj, imdb_id=expected_imdb, instance=instance)

            elif media_type == 'movie':
                if not self.movie_processor:
                    _log("ERROR", "Movie processor not available")
                    return

                instance = webhook_data.get('instance', 'radarr')
                self.movie_processor.process_movie(path_obj, webhook_mode=True, imdb_id=expected_imdb, instance=instance)
            else:
                _log("ERROR", f"Unknown media type: {media_type}")
        
        except Exception as e:
            _log("ERROR", f"Error processing {media_type} {key}: {e}")
        finally:
            with self.lock:
                self.processing.discard(key)
    
    def _process_episodes_sequentially(self, path_obj: Path, episodes_data: list, instance: str = 'sonarr'):
        """Process episodes one by one with delays to avoid Sonarr API spam."""
        total_episodes = len(episodes_data)
        for i, episode in enumerate(episodes_data, 1):
            try:
                season = episode.get('seasonNumber', '?')
                episode_num = episode.get('episodeNumber', '?')
                _log("INFO", f"Processing episode {i}/{total_episodes}: S{season:02d}E{episode_num:02d}")
                self.tv_processor.process_webhook_episodes(path_obj, [episode], instance=instance)
                if i < total_episodes and config.sequential_delay > 0:
                    _log("INFO", f"Waiting {config.sequential_delay}s before next episode...")
                    time.sleep(config.sequential_delay)
            except Exception as e:
                _log("ERROR", f"Error processing episode {i}/{total_episodes}: {e}")

        _log("INFO", f"Completed sequential processing of {total_episodes} episodes")
    
    def get_status(self) -> Dict:
        """Get batch queue status"""
        with self.lock:
            return {
                "pending_items": list(self.pending.keys()),
                "processing_items": list(self.processing),
                "pending_count": len(self.pending),
                "processing_count": len(self.processing)
            }
    
    def shutdown(self):
        """Shutdown the webhook batcher gracefully"""
        _log("INFO", "Shutting down webhook batcher...")
        
        with self.lock:
            # Cancel all pending timers
            for timer in self.timers.values():
                try:
                    timer.cancel()
                except Exception as e:
                    _log("WARNING", f"Error canceling timer: {e}")
            
            self.timers.clear()
            
            # Log any remaining items
            if self.pending:
                _log("WARNING", f"Shutting down with {len(self.pending)} pending items")
            if self.processing:
                _log("INFO", f"Waiting for {len(self.processing)} items to finish processing...")
        
        # Shutdown the thread pool executor
        try:
            # Use timeout parameter only if supported (Python 3.9+)
            import sys
            if sys.version_info >= (3, 9):
                self.executor.shutdown(wait=True, timeout=10)  # Wait up to 10 seconds
            else:
                self.executor.shutdown(wait=True)  # No timeout for older Python versions
            _log("INFO", "Thread pool executor shut down successfully")
        except Exception as e:
            _log("WARNING", f"Error shutting down thread pool: {e}")
        
        _log("INFO", "Webhook batcher shutdown complete")