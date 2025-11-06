"""
Pydantic models for Chronarr API
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class SonarrWebhook(BaseModel):
    """Sonarr webhook payload model"""
    eventType: str
    series: Optional[Dict[str, Any]] = None
    episodes: Optional[list] = []
    episodeFile: Optional[Dict[str, Any]] = None
    isUpgrade: Optional[bool] = False

    class Config:
        extra = "allow"


class RadarrWebhook(BaseModel):
    """Radarr webhook payload model"""
    eventType: str
    movie: Optional[Dict[str, Any]] = None
    movieFile: Optional[Dict[str, Any]] = None
    isUpgrade: Optional[bool] = False
    deletedFiles: Optional[list] = []
    remoteMovie: Optional[Dict[str, Any]] = None
    renamedMovieFiles: Optional[List[Dict[str, Any]]] = None

    class Config:
        extra = "allow"


class MaintainarrWebhook(BaseModel):
    """Maintainarr webhook payload model - uses template variables"""
    notification_type: Optional[str] = None  # e.g., "Media Removed"
    subject: Optional[str] = None
    message: Optional[str] = None
    image: Optional[str] = None
    extra: Optional[str] = None

    class Config:
        extra = "allow"


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    version: str
    uptime: str
    database_status: str
    radarr_database: Optional[Dict[str, Any]] = None


class TVSeasonRequest(BaseModel):
    """TV season processing request model"""
    series_path: str
    season_name: str


class TVEpisodeRequest(BaseModel):
    """TV episode processing request model"""
    series_path: str
    season: int
    episode: int


# Web interface models
class MovieUpdateRequest(BaseModel):
    """Request to update movie dateadded"""
    dateadded: Optional[str]
    source: str


class EpisodeUpdateRequest(BaseModel):
    """Request to update episode dateadded"""
    dateadded: Optional[str]
    source: str


class BulkUpdateRequest(BaseModel):
    """Request for bulk source updates"""
    media_type: str  # "movies" or "episodes"
    old_source: str
    new_source: str


class MovieResponse(BaseModel):
    """Movie data response"""
    imdb_id: str
    title: str
    path: str
    released: Optional[str]
    dateadded: Optional[str]
    source: Optional[str]
    has_video_file: bool
    last_updated: str


class SeriesResponse(BaseModel):
    """TV series data response"""
    imdb_id: str
    title: str
    path: str
    last_updated: str
    total_episodes: int
    episodes_with_dates: int
    episodes_with_video: int


class EpisodeResponse(BaseModel):
    """TV episode data response"""
    season: int
    episode: int
    aired: Optional[str]
    dateadded: Optional[str]
    source: Optional[str]
    has_video_file: bool
    last_updated: str
    series_path: str
    season_name: str
    episode_name: str


# Scheduled Scans Models

class CreateScheduledScanRequest(BaseModel):
    """Request model for creating a scheduled scan"""
    name: str
    description: Optional[str] = None
    cron_expression: str
    media_type: str  # 'tv', 'movies', 'both'
    scan_mode: str   # 'smart', 'full', 'incomplete', 'populate'
    specific_paths: Optional[str] = None
    enabled: bool = True


class UpdateScheduledScanRequest(BaseModel):
    """Request model for updating a scheduled scan"""
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    media_type: Optional[str] = None
    scan_mode: Optional[str] = None
    specific_paths: Optional[str] = None
    enabled: Optional[bool] = None


class ScheduledScanResponse(BaseModel):
    """Response model for scheduled scan data"""
    id: int
    name: str
    description: Optional[str]
    cron_expression: str
    media_type: str
    scan_mode: str
    specific_paths: Optional[str]
    enabled: bool
    created_at: str
    updated_at: str
    last_run_at: Optional[str]
    next_run_at: Optional[str]
    run_count: int
    created_by: Optional[str]
    updated_by: Optional[str]


class ScheduleExecutionResponse(BaseModel):
    """Response model for schedule execution data"""
    id: int
    schedule_id: int
    schedule_name: str
    started_at: str
    completed_at: Optional[str]
    status: str
    media_type: str
    scan_mode: str
    items_processed: int
    items_skipped: int
    items_failed: int
    execution_time_seconds: Optional[int]
    error_message: Optional[str]
    logs: Optional[str]
    triggered_by: Optional[str]


class OrphanedCleanupRequest(BaseModel):
    """Request model for orphaned record cleanup"""
    check_movies: bool = True
    check_series: bool = True
    check_filesystem: bool = True
    check_database: bool = True
    dry_run: bool = False


class CreateScheduledCleanupRequest(BaseModel):
    """Request model for creating a scheduled cleanup"""
    name: str
    description: Optional[str] = None
    cron_expression: str
    check_movies: bool = True
    check_series: bool = True
    check_filesystem: bool = True
    check_database: bool = True
    enabled: bool = True


class UpdateScheduledCleanupRequest(BaseModel):
    """Request model for updating a scheduled cleanup"""
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    check_movies: Optional[bool] = None
    check_series: Optional[bool] = None
    check_filesystem: Optional[bool] = None
    check_database: Optional[bool] = None
    enabled: Optional[bool] = None


class ScheduledCleanupResponse(BaseModel):
    """Response model for scheduled cleanup data"""
    id: int
    name: str
    description: Optional[str]
    cron_expression: str
    check_movies: bool
    check_series: bool
    check_filesystem: bool
    check_database: bool
    enabled: bool
    created_at: str
    updated_at: str
    last_run_at: Optional[str]
    next_run_at: Optional[str]
    run_count: int
    created_by: Optional[str]
    updated_by: Optional[str]


class CleanupExecutionResponse(BaseModel):
    """Response model for cleanup execution data"""
    id: int
    schedule_id: Optional[int]
    schedule_name: Optional[str]
    started_at: str
    completed_at: Optional[str]
    status: str
    movies_removed: int
    series_removed: int
    episodes_removed: int
    execution_time_seconds: Optional[int]
    error_message: Optional[str]
    report_json: Optional[str]
    triggered_by: Optional[str]