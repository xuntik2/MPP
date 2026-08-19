from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from typing import Callable, List

logger = logging.getLogger(__name__)

class SchedulerService:
    """
    Обертка над APScheduler для управления расписанием сбора мемов.
    Поддерживает запуск задач по времени (cron) без перезапуска приложения.
    """
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        logger.info("SchedulerService started successfully.")

    def add_job(self, func: Callable, cron_times: List[str], job_id_prefix: str = "daily"):
        """
        Добавляет задачи в планировщик.
        :param func: Функция для вызова.
        :param cron_times: Список строк времени в формате "HH:MM".
        :param job_id_prefix: Префикс для ID задачи.
        """
        for time_str in cron_times:
            try:
                h, m = map(int, time_str.split(":"))
                trigger = CronTrigger(hour=h, minute=m)
                job_id = f"{job_id_prefix}_{time_str.replace(':', '_')}"
                
                self.scheduler.add_job(
                    func, 
                    trigger=trigger, 
                    id=job_id, 
                    replace_existing=True,
                    name=f"Collection at {time_str}"
                )
                logger.info(f"Scheduled job '{job_id}' to run at {time_str}")
            except Exception as e:
                logger.error(f"Error scheduling job for time {time_str}: {e}", exc_info=True)

    def remove_job(self, job_id: str):
        """Удаляет задачу по ID."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Job {job_id} removed.")
        except Exception as e:
            logger.warning(f"Could not remove job {job_id}: {e}")

    def shutdown(self, wait: bool = True):
        """Останавливает планировщик."""
        logger.info("Shutting down scheduler...")
        self.scheduler.shutdown(wait=wait)
        logger.info("Scheduler stopped.")
