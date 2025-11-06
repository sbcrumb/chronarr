"""
Chronarr Background Scheduler
Manages scheduled scans using APScheduler with cron-like functionality
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

logger = logging.getLogger(__name__)


class ChronarrScheduler:
    """
    Background scheduler for Chronarr that manages scheduled scans
    """
    
    def __init__(self, dependencies: Dict[str, Any]):
        """Initialize the scheduler with dependencies"""
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
            logger.warning("Scheduler is already running")
            return
        
        try:
            self.scheduler.start()
            self.running = True
            logger.info("✅ Chronarr Scheduler started successfully")
            
            # Load existing scheduled scans from database
            await self.load_schedules()
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise
    
    async def stop(self):
        """Stop the scheduler gracefully"""
        if not self.running:
            return
        
        try:
            self.scheduler.shutdown()
            self.running = False
            logger.info("✅ Chronarr Scheduler stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
    
    async def load_schedules(self):
        """Load all enabled scheduled scans from database and add them to scheduler"""
        try:
            db = self.dependencies.get("db")
            if not db:
                logger.error("Database not available for loading schedules")
                return
            
            # Get all enabled scheduled scans
            scheduled_scans = db.get_scheduled_scans(enabled_only=True)
            
            for scan in scheduled_scans:
                await self.add_schedule(scan)
            
            logger.info(f"Loaded {len(scheduled_scans)} scheduled scans")
            
        except Exception as e:
            logger.error(f"Failed to load schedules: {e}")
    
    async def add_schedule(self, scan: Dict[str, Any]):
        """Add a scheduled scan to the scheduler"""
        try:
            job_id = f"scan_{scan['id']}"
            
            # Remove existing job if it exists
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            
            # Create cron trigger
            trigger = CronTrigger.from_crontab(scan['cron_expression'])
            
            # Add job to scheduler
            self.scheduler.add_job(
                func=self._execute_scheduled_scan,
                trigger=trigger,
                id=job_id,
                args=[scan['id']],
                name=f"Scheduled Scan: {scan['name']}",
                replace_existing=True
            )
            
            # Update next run time in database
            next_run = self.scheduler.get_job(job_id).next_run_time
            if next_run:
                db = self.dependencies.get("db")
                if db:
                    db.update_scan_next_run(scan['id'], next_run)
            
            logger.info(f"✅ Added scheduled scan: {scan['name']} ({scan['cron_expression']})")
            
        except Exception as e:
            logger.error(f"Failed to add schedule for scan {scan['id']}: {e}")
    
    async def remove_schedule(self, scan_id: int):
        """Remove a scheduled scan from the scheduler"""
        try:
            job_id = f"scan_{scan_id}"
            
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"✅ Removed scheduled scan: {scan_id}")
            else:
                logger.warning(f"No job found for scan ID: {scan_id}")
                
        except Exception as e:
            logger.error(f"Failed to remove schedule for scan {scan_id}: {e}")
    
    async def update_schedule(self, scan: Dict[str, Any]):
        """Update an existing scheduled scan"""
        try:
            # Remove old schedule and add new one
            await self.remove_schedule(scan['id'])
            if scan['enabled']:
                await self.add_schedule(scan)
            
        except Exception as e:
            logger.error(f"Failed to update schedule for scan {scan['id']}: {e}")
    
    async def _execute_scheduled_scan(self, scan_id: int):
        """Execute a scheduled scan"""
        db = self.dependencies.get("db")
        if not db:
            logger.error(f"Database not available for executing scan {scan_id}")
            return
        
        # Get scan details
        scan = db.get_scheduled_scan(scan_id)
        if not scan:
            logger.error(f"Scheduled scan {scan_id} not found")
            return
        
        if not scan['enabled']:
            logger.info(f"Skipping disabled scan: {scan['name']}")
            return
        
        execution_id = None
        try:
            logger.info(f"🚀 Starting scheduled scan: {scan['name']} (ID: {scan_id})")
            
            # Create execution record
            execution_id = db.create_schedule_execution(
                schedule_id=scan_id,
                media_type=scan['media_type'],
                scan_mode=scan['scan_mode'],
                triggered_by="scheduler"
            )
            
            # Update last run time
            db.update_scan_last_run(scan_id)
            
            # Execute the actual scan
            result = await self._run_media_scan(scan, execution_id)
            
            # Update execution with results
            db.update_schedule_execution(
                execution_id=execution_id,
                status="completed",
                items_processed=result.get('items_processed', 0),
                items_skipped=result.get('items_skipped', 0),
                items_failed=result.get('items_failed', 0),
                logs=result.get('logs', '')
            )
            
            logger.info(f"✅ Completed scheduled scan: {scan['name']} - Processed: {result.get('items_processed', 0)}, Skipped: {result.get('items_skipped', 0)}, Failed: {result.get('items_failed', 0)}")
            
        except Exception as e:
            logger.error(f"❌ Failed scheduled scan: {scan['name']} - {e}")
            
            if execution_id:
                db.update_schedule_execution(
                    execution_id=execution_id,
                    status="failed",
                    error_message=str(e)
                )
    
    async def _run_media_scan(self, scan: Dict[str, Any], execution_id: int) -> Dict[str, Any]:
        """Run the actual media scan based on scan configuration"""
        try:
            media_type = scan['media_type']
            scan_mode = scan['scan_mode']
            specific_paths = scan.get('specific_paths', '').strip()

            logger.info(f"Executing scheduled scan: {scan['name']} (type: {media_type}, mode: {scan_mode})")

            # Import necessary functions
            from api.routes import manual_scan, populate_database
            from fastapi import BackgroundTasks

            # Create a dummy BackgroundTasks since we're already running in background
            class DummyBackgroundTasks:
                def add_task(self, func, *args, **kwargs):
                    # Execute immediately instead of adding to background
                    import asyncio
                    if asyncio.iscoroutinefunction(func):
                        asyncio.create_task(func(*args, **kwargs))
                    else:
                        func(*args, **kwargs)

            background_tasks = DummyBackgroundTasks()

            # Handle database population mode
            if scan_mode == 'populate':
                logger.info(f"Running database population for {media_type}")
                result = await populate_database(
                    background_tasks=background_tasks,
                    media_type=media_type,
                    dependencies=self.dependencies
                )
                return {
                    'items_processed': 1,
                    'items_skipped': 0,
                    'items_failed': 0,
                    'logs': f"Database population started: {media_type}"
                }
            else:
                # Handle regular scan modes (smart, full, incomplete)
                # Prepare path parameter
                path = specific_paths if specific_paths else None

                # Call the actual manual scan function
                result = await manual_scan(
                    background_tasks=background_tasks,
                    path=path,
                    scan_type=media_type,
                    scan_mode=scan_mode,
                    dependencies=self.dependencies
                )

                # Parse the result to extract statistics
                # The manual_scan returns a status message, but we need to track actual results
                # For now, we'll return a success indicator
                return {
                    'items_processed': result.get('processed', 0) if isinstance(result, dict) else 1,
                    'items_skipped': result.get('skipped', 0) if isinstance(result, dict) else 0,
                    'items_failed': result.get('failed', 0) if isinstance(result, dict) else 0,
                    'logs': f"Scan completed: {media_type} ({scan_mode})"
                }

        except Exception as e:
            logger.error(f"Error in media scan execution: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'items_processed': 0,
                'items_skipped': 0,
                'items_failed': 1,
                'logs': f"Scan failed: {str(e)}"
            }
    
    async def run_manual_scan(self, scan_id: int) -> Dict[str, Any]:
        """Manually trigger a scheduled scan"""
        try:
            db = self.dependencies.get("db")
            scan = db.get_scheduled_scan(scan_id)
            
            if not scan:
                return {
                    'success': False,
                    'error': 'Scheduled scan not found'
                }
            
            # Execute the scan in the background
            asyncio.create_task(self._execute_scheduled_scan(scan_id))
            
            return {
                'success': True,
                'message': f"Manual execution of '{scan['name']}' started"
            }
            
        except Exception as e:
            logger.error(f"Failed to run manual scan {scan_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_job_status(self, scan_id: int) -> Optional[Dict[str, Any]]:
        """Get the status of a scheduled job"""
        try:
            job_id = f"scan_{scan_id}"
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
            logger.error(f"Failed to get job status for scan {scan_id}: {e}")
            return None
    
    def list_jobs(self) -> list:
        """List all scheduled jobs"""
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
            logger.error(f"Failed to list jobs: {e}")
            return []


# Global scheduler instance
scheduler_instance: Optional[ChronarrScheduler] = None


async def get_scheduler(dependencies: Dict[str, Any]) -> ChronarrScheduler:
    """Get or create the global scheduler instance"""
    global scheduler_instance
    
    if scheduler_instance is None:
        scheduler_instance = ChronarrScheduler(dependencies)
        await scheduler_instance.start()
    
    return scheduler_instance


async def shutdown_scheduler():
    """Shutdown the global scheduler instance"""
    global scheduler_instance
    
    if scheduler_instance:
        await scheduler_instance.stop()
        scheduler_instance = None