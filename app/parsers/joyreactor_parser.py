"""
Парсер JoyReactor.cc.
Использует BeautifulSoup для разбора HTML.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from bs4 import BeautifulSoup

from .base import BaseParser, RawMeme

logger = logging.getLogger(__name__)


class JoyReactorParser(BaseParser):
    """Парсер для JoyReactor.cc по тегам."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = config.get("parsers", {}).get("joyreactor", True)
        self.base_url = "https://joyreactor.cc/tag/"
        self.tags = ["мемы", "офисный юмор"]
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://joyreactor.cc/"
        })

    def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        memes = []
        if not self.enabled:
            return memes
        
        threshold = self.config.get("thresholds", {}).get("joyreactor", 50)
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        for tag in self.tags:
            url = f"{self.base_url}{tag}"
            try:
                response = self.session.get(url, timeout=15)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                posts = soup.find_all("div", class_="post")
                
                for post in posts:
                    link_elem = post.find("a", class_="title")
                    if not link_elem:
                        continue
                    
                    post_url = link_elem.get("href", "")
                    if post_url.startswith("//"):
                        post_url = "https:" + post_url
                    
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
                    
                    rating_elem = post.find("span", class_="votes")
                    if not rating_elem:
                        continue
                    
                    try:
                        popularity = int(rating_elem.get_text(strip=True))
                    except:
                        continue
                    
                    if popularity < threshold:
                        continue
                    
                    media_items = self._extract_media(post)
                    for media in media_items:
                        meme = RawMeme(
                            source="joyreactor",
                            source_ref=f"tag:{tag}",
                            post_url=post_url,
                            media_url=media["url"],
                            media_type=media["type"],
                            text=link_elem.get_text(strip=True),
                            published_at=published_at,
                            popularity=popularity
                        )
                        memes.append(meme)
                        
            except Exception as e:
                logger.error(f"Ошибка парсинга JoyReactor {tag}: {e}")
        
        return memes

    def _extract_media(self, post) -> List[Dict[str, str]]:
        media_list = []
        img_container = post.find("div", class_="image")
        if img_container:
            img = img_container.find("img")
            if img:
                src = img.get("src") or img.get("data-src")
                if src and src.startswith("//"):
                    src = "https:" + src
                if src:
                    media_list.append({"url": src, "type": "image"})
        return media_list
