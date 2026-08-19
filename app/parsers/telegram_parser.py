"""
Парсер Telegram-каналов через Telethon (MTProto API).
Работает даже при блокировке t.me в браузере.
"""
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from .base import BaseParser, RawMeme

logger = logging.getLogger(__name__)

try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, Message
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    logger.warning("Telethon не установлен. Парсер Telegram будет пропущен.")


class TelegramParser(BaseParser):
    """
    Парсер для Telegram-каналов.
    Требует api_id и api_hash от my.telegram.org.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        tg_config = config.get("telegram", {})
        self.api_id = tg_config.get("api_id")
        self.api_hash = tg_config.get("api_hash", "")
        self.channels = tg_config.get("channels", [])
        self.session_name = "memesbor_telegram"
        self.client: Optional[TelegramClient] = None

    async def _get_client(self) -> Optional[TelegramClient]:
        """Инициализирует клиента Telethon."""
        if not TELETHON_AVAILABLE:
            return None
        
        if not self.api_id or not self.api_hash:
            logger.warning("[TG Parser] API ключи Telegram не указаны.")
            return None
        
        if self.client is None:
            self.client = TelegramClient(
                self.session_name,
                int(self.api_id),
                self.api_hash
            )
            await self.client.start()
        
        return self.client

    async def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        """
        Получает сообщения из каналов Telegram за последние N часов.
        """
        memes = []
        
        if not await self._get_client():
            return memes
        
        threshold = self.config.get("thresholds", {}).get("telegram", 1000)
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        for channel in self.channels:
            try:
                entity = await self.client.get_entity(channel)
                
                # Получаем последние сообщения
                messages = await self.client.get_messages(entity, limit=50)
                
                for msg in messages:
                    if not msg.date:
                        continue
                    
                    if msg.date < cutoff_time:
                        continue
                    
                    # Проверка популярности (просмотры)
                    views = getattr(msg, 'views', 0) or 0
                    if views < threshold:
                        continue
                    
                    media_info = await self._extract_media(msg)
                    
                    for media in media_info:
                        meme = RawMeme(
                            source="telegram",
                            source_ref=channel,
                            post_url=f"https://t.me/{channel}/{msg.id}",
                            media_url=media["url"],
                            media_type=media["type"],
                            text=msg.text,
                            published_at=msg.date,
                            popularity=views
                        )
                        memes.append(meme)
                        
            except Exception as e:
                logger.error(f"Ошибка парсинга канала {channel}: {e}")
        
        logger.info(f"[TG Parser] Найдено {len(memes)} мемов за {time_window_hours}ч.")
        return memes

    async def _extract_media(self, msg: Message) -> List[Dict[str, str]]:
        """Извлекает медиа из сообщения Telegram."""
        media_list = []
        
        if msg.media:
            if isinstance(msg.media, MessageMediaPhoto):
                # Фото
                url = await self.client.download_media(msg.media, bytes)
                if url:
                    media_list.append({"url": f"tg_photo_{msg.id}", "type": "image"})
            
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                mime_type = getattr(doc, 'mime_type', '')
                
                if 'gif' in mime_type:
                    media_list.append({"url": f"tg_gif_{msg.id}", "type": "gif"})
                elif 'video' in mime_type:
                    media_list.append({"url": f"tg_video_{msg.id}", "type": "video"})
                elif 'image' in mime_type:
                    media_list.append({"url": f"tg_doc_{msg.id}", "type": "image"})
        
        return media_list
