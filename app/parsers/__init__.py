"""
Модуль парсеров для МемоСбор.
"""
from .base import BaseParser, RawMeme
from .vk_parser import VKParser
from .pikabu_parser import PikabuParser
from .joyreactor_parser import JoyReactorParser
from .dvach_parser import DvachParser

__all__ = [
    "BaseParser",
    "RawMeme",
    "VKParser",
    "PikabuParser",
    "JoyReactorParser",
    "DvachParser",
]

# TelegramParser импортируется отдельно из-за асинхронности и зависимости от telethon
