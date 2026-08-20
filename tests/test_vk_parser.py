"""
Тесты для VK парсера с rate limiting.
"""
import pytest
from unittest.mock import MagicMock
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parsers.vk_parser import VKParser, RateLimitExceeded


class TestVKParserRateLimit:
    @pytest.fixture
    def mock_config(self):
        return {
            "vk": {
                "service_token": "test_token",
                "communities": ["test_community"]
            },
            "thresholds": {"vk": 100}
        }

    @pytest.fixture
    def vk_parser(self, mock_config):
        parser = VKParser(mock_config)
        parser._last_request_time = 0.0
        parser._request_count_in_window = 0
        parser._consecutive_errors = 0
        parser._circuit_breaker_open = False
        return parser

    def test_rate_limit_initialization(self, vk_parser):
        """Тест: проверка инициализации rate limit параметров."""
        assert vk_parser.VK_API_RATE_LIMIT == 3
        assert vk_parser._rate_limit_window == 1.0
        assert vk_parser._last_request_time == 0.0
        assert vk_parser._request_count_in_window == 0

    def test_check_rate_limit_first_request(self, vk_parser):
        """Тест: первый запрос должен проходить без задержки."""
        start_time = time.time()
        vk_parser._check_rate_limit()
        elapsed = time.time() - start_time
        
        assert elapsed < 0.1
        assert vk_parser._request_count_in_window == 1

    def test_circuit_breaker_activation(self, vk_parser):
        """Тест: circuit breaker активируется после 5 ошибок."""
        assert vk_parser._circuit_breaker_open is False
        
        vk_parser._trigger_circuit_breaker(timeout=1)
        
        assert vk_parser._circuit_breaker_open is True
        assert vk_parser._circuit_breaker_reset_time > time.time()

    def test_circuit_breaker_raises_exception(self, vk_parser):
        """Тест: circuit breaker вызывает исключение при активном состоянии."""
        vk_parser._circuit_breaker_open = True
        vk_parser._circuit_breaker_reset_time = time.time() + 60
        
        with pytest.raises(RateLimitExceeded):
            vk_parser._check_rate_limit()

    def test_circuit_breaker_auto_reset(self, vk_parser):
        """Тест: circuit breaker сбрасывается после timeout."""
        vk_parser._circuit_breaker_open = True
        vk_parser._circuit_breaker_reset_time = time.time() - 1
        
        vk_parser._check_rate_limit()
        assert vk_parser._circuit_breaker_open is False
        assert vk_parser._consecutive_errors == 0

    def test_make_api_request_success(self, vk_parser):
        """Тест: успешный запрос к API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"items": []}}
        vk_parser.session.get = MagicMock(return_value=mock_response)
        
        result = vk_parser._make_api_request({"domain": "test"})
        
        assert "response" in result
        assert vk_parser._consecutive_errors == 0

    def test_make_api_request_rate_limit_error(self, vk_parser):
        """Тест: обработка ошибки rate limit от VK API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {"error_code": 6, "error_msg": "Too many requests"}
        }
        vk_parser.session.get = MagicMock(return_value=mock_response)
        
        # Декоратор делает несколько попыток (retry), поэтому errors будет > 1
        with pytest.raises(RateLimitExceeded):
            vk_parser._make_api_request({"domain": "test"})
        
        # После всех retry счетчик должен быть увеличен
        assert vk_parser._consecutive_errors >= 1

    def test_make_api_request_flood_control_error(self, vk_parser):
        """Тест: обработка ошибки flood control от VK API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {"error_code": 9, "error_msg": "Flood control"}
        }
        vk_parser.session.get = MagicMock(return_value=mock_response)
        
        with pytest.raises(RateLimitExceeded):
            vk_parser._make_api_request({"domain": "test"})
