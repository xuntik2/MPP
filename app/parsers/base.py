"""
Базовый класс для всех парсеров.
Определяет интерфейс и утилиты (phash для антидубля).
"""
import hashlib
import io
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict, Any

import requests
from PIL import Image
import imagehash

logger = logging.getLogger(__name__)


class RawMeme:
    """
    Единый формат данных для сырого мема, полученного от любого источника.
    """
    def __init__(
        self,
        source: str,
        source_ref: str,
        post_url: str,
        media_url: str,
        media_type: str,  # 'image', 'gif', 'video'
        text: Optional[str],
        published_at: datetime,
        popularity: Optional[int] = None
    ):
        self.source = source
        self.source_ref = source_ref
        self.post_url = post_url
        self.media_url = media_url
        self.media_type = media_type
        self.text = text
        self.published_at = published_at
        self.popularity = popularity
        self._image_hash: Optional[str] = None

    def compute_phash(self, image_data: bytes) -> str:
        """Вычисляет перцептивный хеш изображения для поиска дублей."""
        if self._image_hash:
            return self._image_hash
        
        try:
            image = Image.open(io.BytesIO(image_data))
            # Конвертируем в RGB, если нужно (для PNG с прозрачностью)
            if image.mode in ("RGBA", "P"):
                image = image.convert("RGB")
            
            h = imagehash.phash(image)
            self._image_hash = str(h)
            return self._image_hash
        except Exception as e:
            logger.warning(f"Не удалось вычислить phash для {self.media_url}: {e}")
            # Фоллбэк на MD5 от URL, если картинку нельзя открыть сразу
            return hashlib.md5(self.media_url.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_ref": self.source_ref,
            "post_url": self.post_url,
            "media_url": self.media_url,
            "media_type": self.media_type,
            "text": self.text,
            "published_at": self.published_at.isoformat(),
            "popularity": self.popularity,
            "phash": self._image_hash
        }


class BaseParser(ABC):
    """
    Абстрактный базовый класс парсера.
    Все конкретные парсеры должны наследовать его.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        })

    @abstractmethod
    def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        """
        Основной метод сбора данных.
        :param time_window_hours: Собирать мемы только за последние N часов.
        :return: Список объектов RawMeme.
        """
        pass

    def _download_media(self, url: str) -> Optional[bytes]:
        """Скачивает медиафайл по ссылке."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"Ошибка скачивания {url}: {e}")
            return None
