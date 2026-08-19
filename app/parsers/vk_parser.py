"""
Парсер ВКонтакте (VK.com).
Использует официальный API wall.get для получения постов из сообществ.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from .base import BaseParser, RawMeme

logger = logging.getLogger(__name__)


class VKParser(BaseParser):
    """
    Парсер для сообществ ВКонтакте.
    Извлекает изображения, GIF и видео из постов.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.token = config.get("vk", {}).get("service_token", "")
        self.communities = config.get("vk", {}).get("communities", [])
        self.api_url = "https://api.vk.com/method/wall.get"
        self.api_version = "5.131"

    def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        """
        Получает посты из сообществ VK за последние N часов.
        Фильтрует по популярности (лайки + репосты).
        """
        memes = []
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        if not self.token:
            logger.warning("[VK Parser] Токен не указан, пропуск парсинга VK.")
            return memes

        threshold = self.config.get("thresholds", {}).get("vk", 200)

        for domain in self.communities:
            params = {
                "domain": domain,
                "count": 30,
                "access_token": self.token,
                "v": self.api_version
            }
            
            try:
                response = self.session.get(self.api_url, params=params, timeout=15)
                data = response.json()
                
                if "error" in data:
                    logger.error(f"VK API error for {domain}: {data['error']}")
                    continue
                
                items = data.get("response", {}).get("items", [])
                
                for post in items:
                    published_at = datetime.fromtimestamp(post.get("date", 0))
                    if published_at < cutoff_time:
                        continue
                    
                    likes = post.get("likes", {}).get("count", 0)
                    reposts = post.get("reposts", {}).get("count", 0)
                    popularity = likes + reposts
                    
                    if popularity < threshold:
                        continue
                    
                    media_items = self._extract_media(post)
                    
                    for media in media_items:
                        meme = RawMeme(
                            source="vk",
                            source_ref=domain,
                            post_url=f"https://vk.com/wall{post['owner_id']}_{post['id']}",
                            media_url=media["url"],
                            media_type=media["type"],
                            text=post.get("text"),
                            published_at=published_at,
                            popularity=popularity
                        )
                        memes.append(meme)
                        
            except Exception as e:
                logger.error(f"Ошибка парсинга сообщества {domain}: {e}")
        
        logger.info(f"[VK Parser] Найдено {len(memes)} мемов за {time_window_hours}ч.")
        return memes

    def _extract_media(self, post: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Извлекает ссылки на медиа (фото, GIF, видео) из поста VK.
        """
        media_list = []
        attachments = post.get("attachments", [])
        
        for attach in attachments:
            att_type = attach.get("type")
            
            if att_type == "photo":
                photo = attach.get("photo", {})
                url = photo.get("sizes", [-1])[0].get("url") or photo.get("photo_1280") or photo.get("photo_807") or photo.get("photo_604")
                if url:
                    is_gif = photo.get("has_animation", False) or (url.endswith(".gif") or "gif" in url.lower())
                    media_list.append({"url": url, "type": "gif" if is_gif else "image"})
            
            elif att_type == "doc" and attach.get("doc", {}).get("is_gif", False):
                doc = attach.get("doc", {})
                media_list.append({"url": doc.get("url", ""), "type": "gif"})
            
            elif att_type == "video":
                video = attach.get("video", {})
                url = video.get("photo_1280") or video.get("photo_800") or video.get("photo_640")
                if url:
                    media_list.append({"url": url, "type": "video"})
        
        if not media_list and "photo" in post:
            photo = post.get("photo", {})
            url = photo.get("sizes", [-1])[0].get("url") or photo.get("photo_1280")
            if url:
                media_list.append({"url": url, "type": "image"})
        
        return media_list
