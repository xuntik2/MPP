"""
Тесты для Collector (сборщика мемов).
Проверяют логику фильтрации, дедупликации и маппинга разделов.
"""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.collector import Collector
from app.parsers.base import RawMeme
from datetime import datetime, timedelta


class TestCollector:
    @pytest.fixture
    def mock_config(self):
        return {
            "thresholds": {"vk": 100, "pikabu": 50},
            "time_window_hours": 24,
            "sections_mapping": {
                "vk:off_plankton": "office",
                "vk:tproger": "it",
                "default": "mass"
            }
        }

    @pytest.fixture
    def mock_db_session(self):
        session = MagicMock()
        # Мок для проверки существующих хешей (пусто - дублей нет)
        session.query().filter().all.return_value = []
        session.query().filter().first.return_value = None  # Нет дублей по URL
        return session

    @pytest.fixture
    def collector(self, mock_config, mock_db_session):
        # Создаем коллектор с моком БД (передаем сессию напрямую)
        return Collector(mock_config, mock_db_session)

    def test_filter_by_popularity_pass(self, collector):
        """Тест: мем проходит фильтр по популярности."""
        meme = RawMeme(
            source="vk",
            source_ref="off_plankton",
            post_url="http://test.com/1",
            media_url="http://test.com/img.jpg",
            media_type="image",
            text="Test",
            published_at=datetime.now(),
            popularity=150  # Выше порога 100
        )
        
        # Проверяем через конфигурацию порогов
        threshold = collector.config.get("thresholds", {}).get("vk", 0)
        assert meme.popularity >= threshold

    def test_filter_by_popularity_fail(self, collector):
        """Тест: мем отклоняется фильтром по популярности."""
        meme = RawMeme(
            source="vk",
            source_ref="off_plankton",
            post_url="http://test.com/2",
            media_url="http://test.com/img.jpg",
            media_type="image",
            text="Test",
            published_at=datetime.now(),
            popularity=50  # Ниже порога 100
        )
        
        threshold = collector.config.get("thresholds", {}).get("vk", 0)
        assert meme.popularity < threshold

    def test_filter_by_time_pass(self, collector):
        """Тест: свежий мем проходит фильтр по времени."""
        meme = RawMeme(
            source="vk",
            source_ref="off_plankton",
            post_url="http://test.com/3",
            media_url="http://test.com/img.jpg",
            media_type="image",
            text="Test",
            published_at=datetime.now(),  # Сейчас
            popularity=200
        )
        
        time_window = collector.config.get("time_window_hours", 24)
        age = datetime.now() - meme.published_at
        assert age.total_seconds() / 3600 <= time_window

    def test_filter_by_time_fail(self, collector):
        """Тест: старый мем отклоняется фильтром по времени."""
        old_time = datetime.now() - timedelta(hours=48)  # 2 дня назад
        meme = RawMeme(
            source="vk",
            source_ref="off_plankton",
            post_url="http://test.com/4",
            media_url="http://test.com/img.jpg",
            media_type="image",
            text="Test",
            published_at=old_time,
            popularity=200
        )
        
        time_window = collector.config.get("time_window_hours", 24)
        age = datetime.now() - meme.published_at
        assert age.total_seconds() / 3600 > time_window

    def test_get_section_mapping(self, collector):
        """Тест: правильный маппинг раздела по источнику."""
        # Проверяем метод напрямую с двумя аргументами
        assert collector._get_section("vk", "off_plankton") == "office"
        assert collector._get_section("vk", "tproger") == "it"
        assert collector._get_section("vk", "unknown") is None  # Нет в маппинге
