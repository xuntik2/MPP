"""
Парсер 2ch (Dvach) через JSON API.
Доска /b/ - только с обязательной модерацией.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from .base import BaseParser, RawMeme

logger = logging.getLogger(__name__)


class DvachParser(BaseParser):
    """Парсер для 2ch.hk (Dvach)."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = config.get("parsers", {}).get("dvach", False)
        self.base_url = "https://2ch.hk/api"
        self.board = "b"
        self.session.headers.update({
            "Accept": "application/json",
            "Referer": "https://2ch.hk/"
        })

    def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        memes = []
        if not self.enabled:
            logger.info("[2ch Parser] Отключен в конфиге (требует модерации).")
            return memes
        
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        try:
            url = f"{self.base_url}/{self.board}/threads.json"
            response = self.session.get(url, timeout=15)
            
            if response.status_code != 200:
                logger.warning(f"[2ch Parser] Статус {response.status_code}")
                return memes
            
            data = response.json()
            threads = data.get("threads", [])
            
            for thread in threads[:20]:
                # Время треда
                published_at = datetime.fromtimestamp(thread.get("timestamp", 0))
                
                if published_at < cutoff_time:
                    continue
                
                # Извлечение медиа из треда
                media_items = self._extract_media(thread)
                
                for media in media_items:
                    meme = RawMeme(
                        source="2ch",
                        source_ref=f"/{self.board}/",
                        post_url=f"https://2ch.hk/{self.board}/res/{thread['num']}.html",
                        media_url=media["url"],
                        media_type=media["type"],
                        text=thread.get("subject", "") + " " + thread.get("comment", "")[:100],
                        published_at=published_at,
                        popularity=None
                    )
                    memes.append(meme)
                    
        except Exception as e:
            logger.error(f"Ошибка парсинга 2ch: {e}")
        
        logger.info(f"[2ch Parser] Найдено {len(memes)} мемов.")
        return memes

    def _extract_media(self, thread: Dict) -> List[Dict[str, str]]:
        media_list = []
        
        attachments = thread.get("files", [])
        for file in attachments:
            url = file.get("path", "")
            if url:
                if not url.startswith("http"):
                    url = f"https://2ch.hk{url}"
                
                ext = file.get("ext", "").lower()
                if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                    media_list.append({"url": url, "type": "image"})
                elif ext == ".gif":
                    media_list.append({"url": url, "type": "gif"})
                elif ext in [".mp4", ".webm"]:
                    media_list.append({"url": url, "type": "video"})
        
        return media_list
