"""
Модуль сервисов для МемоСбор.
"""
from .collector import Collector
from .compressor import ImageCompressor
from .mailer import MailerService
from .scheduler import SchedulerService

__all__ = ["Collector", "ImageCompressor", "MailerService", "SchedulerService"]
