"""
Парсер Pikabu.ru.
Использует BeautifulSoup для разбора HTML.
Fallback на Playwright при блокировке Cloudflare.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from bs4 import BeautifulSoup

from .base import BaseParser, RawMeme

logger = logging.getLogger(__name__)


class PikabuParser(BaseParser):
    """
    Парсер для Pikabu.ru по тегам.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = config.get("parsers", {}).get("pikabu", True)
        self.base_url = "https://pikabu.ru/tag/"
        self.tags = ["Мемы", "Офисный юмор"]
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://pikabu.ru/"
        })

    def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        """
        Получает посты с Pikabu по тегам за последние N часов.
        """
        memes = []
        
        if not self.enabled:
            logger.info("[Pikabu Parser] Отключен в конфиге.")
            return memes
        
        threshold = self.config.get("thresholds", {}).get("pikabu", 100)
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        for tag in self.tags:
            url = f"{self.base_url}{tag}"
            
            try:
                response = self.session.get(url, timeout=15)
                
                # Проверка на Cloudflare (код 503 или капча)
                if response.status_code == 503 or "cloudflare" in response.text.lower():
                    logger.warning(f"[Pikabu Parser] Cloudflare защита для {url}. Требуется Playwright.")
                    # Здесь можно добавить fallback на Playwright
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                posts = soup.find_all("article", class_="story")
                
                for post in posts:
                    # Извлечение данных поста
                    post_link_elem = post.find("a", class_="story__title-link")
                    if not post_link_elem:
                        continue
                    
                    post_url = post_link_elem.get("href", "")
                    if post_url.startswith("//"):
                        post_url = "https:" + post_url
                    elif post_url.startswith("/"):
                        post_url = f"https://pikabu.ru{post_url}"
                    
                    # Время публикации
                    time_elem = post.find("time")
                    if not time_elem:
                        continue
                    
                    published_at_str = time_elem.get("datetime", "")
                    try:
                        published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                    except:
                        continue
                    
                    if published_at < cutoff_time:
                        continue
                    
                    # Популярность (рейтинг)
                    rating_elem = post.find("span", class_="story__vote-count")
                    if not rating_elem:
                        continue
                    
                    try:
                        popularity = int(rating_elem.get_text(strip=True))
                    except:
                        continue
                    
                    if popularity < threshold:
                        continue
                    
                    # Извлечение медиа
                    media_items = self._extract_media(post)
                    
                    for media in media_items:
                        meme = RawMeme(
                            source="pikabu",
                            source_ref=f"tag:{tag}",
                            post_url=post_url,
                            media_url=media["url"],
                            media_type=media["type"],
                            text=post_link_elem.get_text(strip=True),
                            published_at=published_at,
                            popularity=popularity
                        )
                        memes.append(meme)
                        
            except Exception as e:
                logger.error(f"Ошибка парсинга тега {tag}: {e}")
        
        logger.info(f"[Pikabu Parser] Найдено {len(memes)} мемов за {time_window_hours}ч.")
        return memes

    def _extract_media(self, post) -> List[Dict[str, str]]:
        """Извлекает медиа из поста Pikabu."""
        media_list = []
        
        # Поиск изображений
        img_container = post.find("div", class_="story__image-container") or post.find("div", class_="story-image")
        
        if img_container:
            imgs = img_container.find_all("img")
            for img in imgs:
                src = img.get("src") or img.get("data-src")
                if src and src.startswith("//"):
                    src = "https:" + src
                if src:
                    media_list.append({"url": src, "type": "image"})
        
        # Если нет контейнера, ищем просто img в посте
        if not media_list:
            content = post.find("div", class_="story__content-inner")
            if content:
                img = content.find("img")
                if img:
                    src = img.get("src") or img.get("data-src")
                    if src:
                        media_list.append({"url": src, "type": "image"})
        
        return media_list
