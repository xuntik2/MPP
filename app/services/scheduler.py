from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging
from typing import Callable

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.jobs = {}

    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started")

    def add_job(self, job_id: str, func: Callable, cron_expr: str):
        """
        cron_expr: формат "minute hour day month day_of_week"
        Пример: "0 9 * * *" (каждый день в 9:00)
        """
        try:
            parts = cron_expr.split()
            if len(parts) == 2: # Простой формат "HH:MM"
                minute, hour = parts
                trigger = CronTrigger(minute=minute, hour=hour)
            else:
                trigger = CronTrigger.from_crontab(cron_expr)
            
            self.scheduler.add_job(func, trigger, id=job_id, replace_existing=True)
            self.jobs[job_id] = func
            logger.info(f"Scheduled job {job_id} at {cron_expr}")
        except Exception as e:
            logger.error(f"Failed to schedule job {job_id}: {e}")

    def remove_job(self, job_id: str):
        try:
            self.scheduler.remove_job(job_id)
            if job_id in self.jobs:
                del self.jobs[job_id]
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")