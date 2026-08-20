"""
Парсер ВКонтакте (VK.com).
Использует официальный API wall.get для получения постов из сообществ.
Реализует rate limiting и exponential backoff.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from functools import wraps

from .base import BaseParser, RawMeme

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Превышен лимит запросов к API."""
    pass


def rate_limit_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Декоратор для rate limiting с exponential backoff.
    Применяется к методам, делающим запросы к VK API.
    
    :param max_retries: Максимальное количество попыток
    :param base_delay: Базовая задержка в секундах
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    # Проверка rate limit перед запросом
                    self._check_rate_limit()
                    
                    result = func(self, *args, **kwargs)
                    
                    # Успешный запрос - сбрасываем счетчик ошибок
                    self._consecutive_errors = 0
                    return result
                    
                except RateLimitExceeded as e:
                    last_error = e
                    if attempt < max_retries:
                        # Exponential backoff: 1s, 2s, 4s, 8s...
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Rate limit hit. Waiting {delay}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(delay)
                    else:
                        logger.error(f"Max retries exceeded for VK API call: {e}")
                        
                except Exception as e:
                    last_error = e
                    self._consecutive_errors += 1
                    
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Request failed: {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        logger.error(f"Max retries exceeded: {e}")
            
            raise last_error
        
        return wrapper
    return decorator


class VKParser(BaseParser):
    """
    Парсер для сообществ ВКонтакте.
    Извлекает изображения, GIF и видео из постов.
    Реализует rate limiting: 3 запроса в секунду (ограничение VK API).
    """

    # Лимиты VK API
    VK_API_RATE_LIMIT = 3  # запросов в секунду
    VK_API_ERROR_CODES = {
        6: "Too many requests",
        9: "Flood control",
        100: "One of the parameters is wrong",
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.token = config.get("vk", {}).get("service_token", "")
        self.communities = config.get("vk", {}).get("communities", [])
        self.api_url = "https://api.vk.com/method/wall.get"
        self.api_version = "5.131"
        
        # Rate limiting state
        self._last_request_time = 0.0
        self._request_count_in_window = 0
        self._rate_limit_window = 1.0
        self._consecutive_errors = 0
        self._circuit_breaker_open = False
        self._circuit_breaker_reset_time = 0.0

    def _check_rate_limit(self):
        """
        Проверяет и соблюдает rate limit VK API (3 запроса/сек).
        Использует sliding window approach.
        """
        current_time = time.time()
        
        # Проверка circuit breaker
        if self._circuit_breaker_open:
            if current_time > self._circuit_breaker_reset_time:
                logger.info("Circuit breaker reset, resuming requests")
                self._circuit_breaker_open = False
                self._consecutive_errors = 0
            else:
                wait_time = self._circuit_breaker_reset_time - current_time
                raise RateLimitExceeded(
                    f"Circuit breaker open. Wait {wait_time:.1f}s before next request"
                )
        
        # Сброс счетчика если прошло больше окна
        if current_time - self._last_request_time > self._rate_limit_window:
            self._request_count_in_window = 0
            self._last_request_time = current_time
        
        # Если достигнут лимит - ждем
        if self._request_count_in_window >= self.VK_API_RATE_LIMIT:
            elapsed = current_time - self._last_request_time
            if elapsed < self._rate_limit_window:
                sleep_time = self._rate_limit_window - elapsed
                logger.debug(f"Rate limit reached, sleeping for {sleep_time:.2f}s")
                time.sleep(sleep_time)
                self._request_count_in_window = 0
                self._last_request_time = time.time()
        
        # Увеличиваем счетчик запросов
        self._request_count_in_window += 1

    def _trigger_circuit_breaker(self, timeout: int = 60):
        """
        Активирует circuit breaker после множественных ошибок.
        :param timeout: Время блокировки в секундах
        """
        self._circuit_breaker_open = True
        self._circuit_breaker_reset_time = time.time() + timeout
        logger.warning(f"Circuit breaker activated. Will reset in {timeout}s")

    @rate_limit_with_backoff(max_retries=3, base_delay=1.0)
    def _make_api_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Делает запрос к VK API с учетом rate limiting.
        :param params: Параметры запроса
        :return: JSON ответ
        """
        response = self.session.get(self.api_url, params=params, timeout=15)
        data = response.json()
        
        # Проверка на ошибки API
        if "error" in data:
            error_code = data["error"].get("error_code", 0)
            error_msg = data["error"].get("error_msg", "Unknown error")
            
            if error_code in [6, 9]:
                self._consecutive_errors += 1
                if self._consecutive_errors >= 5:
                    self._trigger_circuit_breaker()
                raise RateLimitExceeded(f"VK API error {error_code}: {error_msg}")
            
            logger.error(f"VK API error {error_code}: {error_msg}")
            raise Exception(f"VK API error {error_code}: {error_msg}")
        
        return data

    def fetch(self, time_window_hours: int = 24) -> List[RawMeme]:
        """
        Получает посты из сообществ VK за последние N часов.
        Фильтрует по популярности (лайки + репосты).
        Соблюдает rate limit VK API (3 запроса/сек).
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
                data = self._make_api_request(params)
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

            except RateLimitExceeded as e:
                logger.error(f"Rate limit exceeded for community {domain}: {e}")
                break
            except Exception as e:
                logger.error(f"Ошибка парсинга сообщества {domain}: {e}")
                continue

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
