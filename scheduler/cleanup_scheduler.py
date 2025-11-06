"""
Chronarr Cleanup Scheduler
Manages scheduled cleanup jobs using APScheduler with cron-like functionality
"""
import logging
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

logger = logging.getLogger(__name__)


class CleanupScheduler:
    """
    Background scheduler for Chronarr that manages scheduled cleanup jobs
    """

    def __init__(self, dependencies: Dict[str, Any]):
        """Initialize the cleanup scheduler with dependencies"""
        self.dependencies = dependencies
        self.scheduler = None
        self.running = False

        # Configure APScheduler
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': AsyncIOExecutor()
        }
        job_defaults = {
            'coalesce': False,
            'max_instances': 1,
            'misfire_grace_time': 300  # 5 minutes
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )

    async def start(self):
        """Start the scheduler and load existing schedules"""
        if self.running:
            logger.warning("Cleanup scheduler is already running")
            return

        try:
            self.scheduler.start()
            self.running = True
            logger.info("✅ Cleanup Scheduler started successfully")

            # Load existing scheduled cleanups from database
            await self.load_schedules()

        except Exception as e:
            logger.error(f"Failed to start cleanup scheduler: {e}")
            raise

    async def stop(self):
        """Stop the scheduler gracefully"""
        if not self.running:
            return

        try:
            self.scheduler.shutdown()
            self.running = False
            logger.info("✅ Cleanup Scheduler stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping cleanup scheduler: {e}")

    async def load_schedules(self):
        """Load all enabled scheduled cleanups from database and add them to scheduler"""
        try:
            db = self.dependencies.get("db")
            if not db:
                logger.error("Database not available for loading cleanup schedules")
                return

            # Get all enabled scheduled cleanups
            scheduled_cleanups = db.get_scheduled_cleanups(enabled_only=True)

            for cleanup in scheduled_cleanups:
                await self.add_schedule(cleanup)

            logger.info(f"Loaded {len(scheduled_cleanups)} scheduled cleanups")

        except Exception as e:
            logger.error(f"Failed to load cleanup schedules: {e}")

    async def add_schedule(self, cleanup: Dict[str, Any]):
        """Add a scheduled cleanup to the scheduler"""
        try:
            job_id = f"cleanup_{cleanup['id']}"

            # Remove existing job if it exists
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # Create cron trigger
            trigger = CronTrigger.from_crontab(cleanup['cron_expression'])

            # Add job to scheduler
            self.scheduler.add_job(
                func=self._execute_scheduled_cleanup,
                trigger=trigger,
                id=job_id,
                args=[cleanup['id']],
                name=f"Scheduled Cleanup: {cleanup['name']}",
                replace_existing=True
            )

            # Update next run time in database
            next_run = self.scheduler.get_job(job_id).next_run_time
            if next_run:
                db = self.dependencies.get("db")
                if db:
                    db.update_cleanup_next_run(cleanup['id'], next_run)

            logger.info(f"✅ Added scheduled cleanup: {cleanup['name']} ({cleanup['cron_expression']})")

        except Exception as e:
            logger.error(f"Failed to add schedule for cleanup {cleanup['id']}: {e}")

    async def remove_schedule(self, cleanup_id: int):
        """Remove a scheduled cleanup from the scheduler"""
        try:
            job_id = f"cleanup_{cleanup_id}"

            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"✅ Removed scheduled cleanup: {cleanup_id}")
            else:
                logger.warning(f"No job found for cleanup ID: {cleanup_id}")

        except Exception as e:
            logger.error(f"Failed to remove schedule for cleanup {cleanup_id}: {e}")

    async def update_schedule(self, cleanup: Dict[str, Any]):
        """Update an existing scheduled cleanup"""
        try:
            # Remove old schedule and add new one
            await self.remove_schedule(cleanup['id'])
            if cleanup['enabled']:
                await self.add_schedule(cleanup)

        except Exception as e:
            logger.error(f"Failed to update schedule for cleanup {cleanup['id']}: {e}")

    async def _execute_scheduled_cleanup(self, cleanup_id: int):
        """Execute a scheduled cleanup"""
        db = self.dependencies.get("db")
        if not db:
            logger.error(f"Database not available for executing cleanup {cleanup_id}")
            return

        # Get cleanup details
        cleanup = db.get_scheduled_cleanup(cleanup_id)
        if not cleanup:
            logger.error(f"Scheduled cleanup {cleanup_id} not found")
            return

        if not cleanup['enabled']:
            logger.info(f"Skipping disabled cleanup: {cleanup['name']}")
            return

        execution_id = None
        try:
            logger.info(f"🧹 Starting scheduled cleanup: {cleanup['name']} (ID: {cleanup_id})")

            # Create execution record
            execution_id = db.create_cleanup_execution(
                schedule_id=cleanup_id,
                triggered_by="scheduler"
            )

            # Update last run time
            db.update_cleanup_last_run(cleanup_id)

            # Execute the actual cleanup
            result = await self._run_orphaned_cleanup(cleanup, execution_id)

            # Update execution with results
            db.update_cleanup_execution(
                execution_id=execution_id,
                status="completed",
                movies_removed=result.get('movies_removed', 0),
                series_removed=result.get('series_removed', 0),
                episodes_removed=result.get('episodes_removed', 0),
                report_json=json.dumps(result.get('report', {}))
            )

            logger.info(f"✅ Completed scheduled cleanup: {cleanup['name']} - Movies: {result.get('movies_removed', 0)}, Series: {result.get('series_removed', 0)}, Episodes: {result.get('episodes_removed', 0)}")

        except Exception as e:
            logger.error(f"❌ Failed scheduled cleanup: {cleanup['name']} - {e}")

            if execution_id:
                db.update_cleanup_execution(
                    execution_id=execution_id,
                    status="failed",
                    error_message=str(e)
                )

    async def _run_orphaned_cleanup(self, cleanup: Dict[str, Any], execution_id: int) -> Dict[str, Any]:
        """Run the actual orphaned record cleanup based on cleanup configuration"""
        try:
            from utils.orphaned_cleanup import OrphanedRecordCleaner

            db = self.dependencies.get("db")
            radarr_db_client = self.dependencies.get("radarr_db_client")
            sonarr_db_client = self.dependencies.get("sonarr_db_client")

            # Initialize the cleaner
            cleaner = OrphanedRecordCleaner(
                chronarr_db=db,
                radarr_db_client=radarr_db_client,
                sonarr_db_client=sonarr_db_client
            )

            # Run cleanup with configured options
            report = cleaner.cleanup_orphaned_records(
                check_movies=cleanup.get('check_movies', True),
                check_series=cleanup.get('check_series', True),
                check_filesystem=cleanup.get('check_filesystem', True),
                check_database=cleanup.get('check_database', True),
                dry_run=False  # Never dry-run for scheduled cleanups
            )

            return {
                'movies_removed': report['movies']['removed'],
                'series_removed': report['series']['removed'],
                'episodes_removed': report['series']['removed_episodes'],
                'report': report
            }

        except Exception as e:
            logger.error(f"Error in cleanup execution: {e}")
            return {
                'movies_removed': 0,
                'series_removed': 0,
                'episodes_removed': 0,
                'report': {'error': str(e)}
            }

    async def run_manual_cleanup(self, cleanup_id: int) -> Dict[str, Any]:
        """Manually trigger a scheduled cleanup"""
        try:
            db = self.dependencies.get("db")
            cleanup = db.get_scheduled_cleanup(cleanup_id)

            if not cleanup:
                return {
                    'success': False,
                    'error': 'Scheduled cleanup not found'
                }

            # Execute the cleanup in the background
            asyncio.create_task(self._execute_scheduled_cleanup(cleanup_id))

            return {
                'success': True,
                'message': f"Manual execution of '{cleanup['name']}' started"
            }

        except Exception as e:
            logger.error(f"Failed to run manual cleanup {cleanup_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_job_status(self, cleanup_id: int) -> Optional[Dict[str, Any]]:
        """Get the status of a scheduled cleanup job"""
        try:
            job_id = f"cleanup_{cleanup_id}"
            job = self.scheduler.get_job(job_id)

            if not job:
                return None

            return {
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            }

        except Exception as e:
            logger.error(f"Failed to get job status for cleanup {cleanup_id}: {e}")
            return None

    def list_jobs(self) -> list:
        """List all scheduled cleanup jobs"""
        try:
            jobs = []
            for job in self.scheduler.get_jobs():
                jobs.append({
                    'id': job.id,
                    'name': job.name,
                    'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                    'trigger': str(job.trigger)
                })
            return jobs
        except Exception as e:
            logger.error(f"Failed to list cleanup jobs: {e}")
            return []


# Global cleanup scheduler instance
cleanup_scheduler_instance: Optional[CleanupScheduler] = None


async def get_cleanup_scheduler(dependencies: Dict[str, Any]) -> CleanupScheduler:
    """Get or create the global cleanup scheduler instance"""
    global cleanup_scheduler_instance

    if cleanup_scheduler_instance is None:
        cleanup_scheduler_instance = CleanupScheduler(dependencies)
        await cleanup_scheduler_instance.start()

    return cleanup_scheduler_instance


async def shutdown_cleanup_scheduler():
    """Shutdown the global cleanup scheduler instance"""
    global cleanup_scheduler_instance

    if cleanup_scheduler_instance:
        await cleanup_scheduler_instance.stop()
        cleanup_scheduler_instance = None
