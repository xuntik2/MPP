"""
Collector - оркестратор сбора мемов.
Фильтрация по времени, популярности, дедупликация по phash.
"""
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.parsers.base import RawMeme
from app.parsers.vk_parser import VKParser
from app.parsers.pikabu_parser import PikabuParser
from app.parsers.joyreactor_parser import JoyReactorParser
from app.parsers.dvach_parser import DvachParser
from app.models import Meme, RunLog

logger = logging.getLogger(__name__)


class Collector:
    """
    Оркестрирует сбор мемов из всех источников.
    """
    
    def __init__(self, config: Dict[str, Any], db_session: Session):
        self.config = config
        self.db = db_session
        self.parsers = self._init_parsers()
        
        # Маппинг источник -> раздел
        self.section_mapping = {
            "vk": {
                "off_plankton": "office",
                "tproger": "it",
                "borsch": "mass",
                "lentach": "news"
            },
            "telegram": {
                "th_21st": "office",
                "office_plankton": "office",
                "reklamaplacit": "office",
                "it_humor": "it",
                "kb_tg": "mass",
                "dvach": "dark",
                "topor": "dark"
            },
            "pikabu": {
                "tag:Офисный юмор": "office",
                "tag:Мемы": "mass"
            },
            "joyreactor": {
                "tag:офисный юмор": "office",
                "tag:мемы": "mass"
            },
            "2ch": {
                "/b/": "dark"
            }
        }

    def _init_parsers(self) -> Dict[str, Any]:
        """Инициализирует парсеры на основе конфига."""
        parsers = {}
        
        if self.config.get("vk", {}).get("service_token"):
            parsers["vk"] = VKParser(self.config)
        
        if self.config.get("parsers", {}).get("pikabu", True):
            parsers["pikabu"] = PikabuParser(self.config)
        
        if self.config.get("parsers", {}).get("joyreactor", True):
            parsers["joyreactor"] = JoyReactorParser(self.config)
        
        if self.config.get("parsers", {}).get("dvach", False):
            parsers["2ch"] = DvachParser(self.config)
        
        # Telegram требует async, пока пропускаем
        logger.info(f"Инициализировано парсеров: {len(parsers)}")
        return parsers

    def run_collection(self, time_window_hours: int = 24) -> Dict[str, int]:
        """
        Запускает сбор мемов из всех источников.
        Возвращает статистику: найдено, сохранено, дубли, отфильтровано.
        """
        stats = {
            "found": 0,
            "saved": 0,
            "duplicates": 0,
            "filtered": 0,
            "errors": 0
        }
        
        start_time = datetime.now()
        logger.info(f"Начало сбора мемов (окно: {time_window_hours}ч)")
        
        all_raw_memes: List[RawMeme] = []
        
        # Сбор от всех парсеров
        for source_name, parser in self.parsers.items():
            try:
                raw_memes = parser.fetch(time_window_hours=time_window_hours)
                all_raw_memes.extend(raw_memes)
                stats["found"] += len(raw_memes)
                logger.info(f"[{source_name}] Найдено {len(raw_memes)} мемов")
            except Exception as e:
                logger.error(f"Ошибка парсера {source_name}: {e}")
                stats["errors"] += 1
        
        # Обработка каждого мема
        for raw_meme in all_raw_memes:
            result = self._process_meme(raw_meme, time_window_hours)
            
            if result == "saved":
                stats["saved"] += 1
            elif result == "duplicate":
                stats["duplicates"] += 1
            elif result == "filtered":
                stats["filtered"] += 1
        
        # Логирование результата
        end_time = datetime.now()
        self._log_run(start_time, end_time, stats)
        
        logger.info(f"Сбор завершен: {stats}")
        return stats

    def _process_meme(self, raw_meme: RawMeme, time_window_hours: int) -> str:
        """
        Обрабатывает один мем: проверка на дубль, определение раздела, сохранение.
        Возвращает: 'saved', 'duplicate', 'filtered'
        """
        # Определение раздела
        section = self._get_section(raw_meme.source, raw_meme.source_ref)
        if not section:
            logger.debug(f"Неизвестный раздел для {raw_meme.source_ref}, пропускаем")
            return "filtered"
        
        # Проверка на дубликат по phash
        if self._is_duplicate(raw_meme):
            logger.debug(f"Дубликат: {raw_meme.post_url}")
            return "duplicate"
        
        # Скачивание и сохранение файла
        file_path = self._save_media(raw_meme, section)
        if not file_path:
            return "filtered"
        
        # Вычисление phash после скачивания
        try:
            with open(file_path, 'rb') as f:
                image_data = f.read()
            phash = raw_meme.compute_phash(image_data)
        except Exception as e:
            logger.warning(f"Не удалось вычислить phash: {e}")
            phash = None
        
        # Запись в БД
        meme = Meme(
            phash=phash,
            source=raw_meme.source,
            source_ref=raw_meme.source_ref,
            post_url=raw_meme.post_url,
            section=section,
            file_path=file_path,
            media_type=raw_meme.media_type,
            text=raw_meme.text[:500] if raw_meme.text else None,
            popularity=raw_meme.popularity,
            published_at=raw_meme.published_at,
            status="new"
        )
        
        self.db.add(meme)
        self.db.commit()
        logger.debug(f"Сохранен мем: {meme.post_url}")
        
        return "saved"

    def _get_section(self, source: str, source_ref: str) -> Optional[str]:
        """Определяет раздел для мема."""
        source_map = self.section_mapping.get(source, {})
        return source_map.get(source_ref)

    def _is_duplicate(self, raw_meme: RawMeme) -> bool:
        """Проверяет наличие дубликата в БД по URL или phash."""
        # Проверка по URL
        existing = self.db.query(Meme).filter(
            Meme.post_url == raw_meme.post_url
        ).first()
        
        if existing:
            return True
        
        # Если phash уже вычислен, проверяем по нему
        if raw_meme._image_hash:
            existing_by_hash = self.db.query(Meme).filter(
                Meme.phash == raw_meme._image_hash
            ).first()
            if existing_by_hash:
                return True
        
        return False

    def _save_media(self, raw_meme: RawMeme, section: str) -> Optional[str]:
        """Скачивает и сохраняет медиафайл."""
        from app.parsers.base import BaseParser
        
        # Создаем временный парсер для скачивания
        parser = BaseParser(self.config)
        media_data = parser._download_media(raw_meme.media_url)
        
        if not media_data:
            logger.warning(f"Не удалось скачать {raw_meme.media_url}")
            return None
        
        # Определяем расширение
        ext = self._get_extension(raw_meme.media_url, media_data)
        
        # Путь сохранения
        filename = f"{raw_meme.source}_{raw_meme.source_ref}_{int(raw_meme.published_at.timestamp())}{ext}"
        base_dir = os.path.join("data", "memes", section)
        os.makedirs(base_dir, exist_ok=True)
        
        file_path = os.path.join(base_dir, filename)
        
        try:
            with open(file_path, 'wb') as f:
                f.write(media_data)
            return file_path
        except Exception as e:
            logger.error(f"Ошибка сохранения файла {file_path}: {e}")
            return None

    def _get_extension(self, url: str, data: bytes) -> str:
        """Определяет расширение файла по URL или содержимому."""
        url_lower = url.lower()
        if ".gif" in url_lower:
            return ".gif"
        elif ".mp4" in url_lower or ".webm" in url_lower:
            return ".mp4"
        elif ".png" in url_lower:
            return ".png"
        elif ".webp" in url_lower:
            return ".webp"
        elif ".jpg" in url_lower or ".jpeg" in url_lower:
            return ".jpg"
        
        # Fallback по magic bytes
        if data.startswith(b'\x89PNG'):
            return ".png"
        elif data.startswith(b'\xff\xd8\xff'):
            return ".jpg"
        elif data.startswith(b'GIF8'):
            return ".gif"
        
        return ".jpg"  # По умолчанию JPEG

    def _log_run(self, start: datetime, end: datetime, stats: Dict[str, int]):
        """Записывает лог запуска в БД."""
        log = RunLog(
            started_at=start,
            finished_at=end,
            source="all",
            found=stats["found"],
            saved=stats["saved"],
            skipped_dupes=stats["duplicates"],
            filtered=stats["filtered"],
            error=f"Errors: {stats['errors']}" if stats["errors"] > 0 else None
        )
        self.db.add(log)
        self.db.commit()
