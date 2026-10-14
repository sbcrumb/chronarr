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
    radarr_database: Optional[Dict[str, Any]] = None  # legacy — default Radarr instance only, kept for back-compat
    instances: Optional[Dict[str, Dict[str, Any]]] = None  # {"radarr": {name: {connected, method}}, "sonarr": {...}} — every configured instance


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


class WizardConnectionTestRequest(BaseModel):
    """Setup wizard: test a Radarr/Sonarr URL+API key or a direct DB connection.

    Send either url+api_key, or a db_type block, or both — whatever the
    form has filled in so far. Doesn't touch any files.
    """
    media_type: str  # "radarr" or "sonarr"
    name: Optional[str] = None  # not validated here — just used to label log lines during the test
    url: Optional[str] = None
    api_key: Optional[str] = None
    db_type: Optional[str] = None  # "sqlite" or "postgresql"
    db_host: Optional[str] = None
    db_port: Optional[int] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_path: Optional[str] = None


class WizardSaveInstanceRequest(BaseModel):
    """Setup wizard: write a Radarr/Sonarr instance to .env / .env.secrets.

    `name` is the user-typed instance name (e.g. "4k" or "strm") — leave it
    empty to configure the default instance. `force` skips the connection
    test failing being a hard stop, for someone who knows the service is
    just down right now and wants to save the config anyway. `edit_existing`
    flips the name check: normally a name must NOT already exist (adding a
    new instance); with edit_existing=True it must ALREADY exist instead —
    editing something that was never configured isn't a valid request either.
    """
    media_type: str  # "radarr" or "sonarr"
    name: str = ""
    url: str
    api_key: str
    root_folders: Optional[List[str]] = None
    movie_paths: Optional[List[str]] = None  # radarr instances only
    tv_paths: Optional[List[str]] = None     # sonarr instances only
    db_type: Optional[str] = None
    db_host: Optional[str] = None
    db_port: Optional[int] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_path: Optional[str] = None
    force: bool = False
    edit_existing: bool = False


class WizardDeleteInstanceRequest(BaseModel):
    """Setup wizard: remove a Radarr/Sonarr instance from .env / .env.secrets.

    Removes every env var this instance's name segment owns. Same automatic
    pre-write snapshot every other wizard write already takes.
    """
    media_type: str  # "radarr" or "sonarr"
    name: str = ""   # "" targets the default (unprefixed) instance


class WizardEnvRestoreRequest(BaseModel):
    """Setup wizard: restore .env / .env.secrets from a backup file's contents.

    `env` and `env_secrets` are the raw file text, exactly as
    GET /api/wizard/env-backup produced them — this overwrites both files
    verbatim, not a merge. `chronarr_version`/`exported_at` are informational
    only, from the backup's own header; nothing currently rejects a restore
    over a version mismatch, but they're captured in case that's worth
    warning about later.
    """
    env: str
    env_secrets: str
    chronarr_version: Optional[str] = None
    exported_at: Optional[str] = None