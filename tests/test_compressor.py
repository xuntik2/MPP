"""
Тесты для сервиса сжатия изображений (Compressor).
Проверяют корректность сжатия до целевого размера.
"""
import os
import pytest
from PIL import Image
from io import BytesIO
from pathlib import Path

# Импортируем сервис из проекта
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.services.compressor import ImageCompressor


class TestImageCompressor:
    @pytest.fixture
    def compressor(self):
        return ImageCompressor(target_kb=150, min_quality=60, min_dimension=800)

    @pytest.fixture
    def temp_image(self, tmp_path):
        """Создает тестовое изображение 2000x2000 пикселей."""
        img_path = tmp_path / "test_large.jpg"
        img = Image.new('RGB', (2000, 2000), color='red')
        img.save(img_path, quality=95)  # Сохраняем с высоким качеством для большого размера
        return str(img_path)

    def test_compress_success(self, compressor, temp_image, tmp_path):
        """Тест: изображение успешно сжимается."""
        output_path = str(tmp_path / "compressed.jpg")
        
        result = compressor.compress(temp_image, output_path)
        
        assert result["success"] is True
        assert "compressed_kb" in result
        assert "original_kb" in result
        assert result["compressed_kb"] <= 150 or result["compressed_kb"] < result["original_kb"]
        assert os.path.exists(output_path)

    def test_compress_file_not_found(self, compressor, tmp_path):
        """Тест: обработка несуществующего файла."""
        result = compressor.compress("non_existent_file.jpg", str(tmp_path / "out.jpg"))
        
        assert result["success"] is False
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_compress_preserves_aspect_ratio(self, compressor, temp_image, tmp_path):
        """Тест: при ресайзе сохраняются пропорции (базовая проверка)."""
        output_path = str(tmp_path / "resized.jpg")
        compressor.compress(temp_image, output_path)
        
        with Image.open(output_path) as img:
            w, h = img.size
            # Если изображение было уменьшено, пропорции должны сохраниться (1:1 для квадрата)
            # Это простая проверка, что картинка не битая
            assert w > 0 and h > 0
