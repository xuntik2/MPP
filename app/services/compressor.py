import os
from PIL import Image
from io import BytesIO
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ImageCompressor:
    """
    Сервис сжатия изображений до целевого размера (по умолчанию ≤150 КБ).
    Алгоритм:
    1. Попытка сохранить в WebP/JPEG с качеством 85.
    2. Если размер > target_kb: уменьшаем качество шагом 5 до min_quality.
    3. Если всё ещё велико: уменьшаем разрешение на 15% и повторяем.
    4. Минимальное разрешение: min_dimension по длинной стороне.
    """
    
    def __init__(self, target_kb: int = 150, min_quality: int = 60, min_dimension: int = 800):
        self.target_kb = target_kb
        self.min_quality = min_quality
        self.min_dimension = min_dimension

    def compress(self, input_path: str, output_path: str) -> dict:
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            return {"success": False, "error": "File not found"}

        try:
            with Image.open(input_path) as img:
                original_size_bytes = os.path.getsize(input_path)
                original_size_kb = original_size_bytes / 1024
                
                # Конвертируем в RGB, если есть альфа-канал (для JPEG/WebP)
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")
                
                width, height = img.size
                max_dim = max(width, height)
                
                # Определяем формат сохранения (предпочитаем WebP)
                save_format = "WEBP"
                if input_path.lower().endswith(".gif"):
                    # Для GIF особая логика (упрощенно: сохраняем как статичный кадр или WebP)
                    logger.warning(f"GIF detected: {input_path}. Converting to static WebP.")
                    save_format = "WEBP"
                
                quality = 85
                current_size_kb = original_size_kb + 1  # Завышаем для входа в цикл
                
                # Шаг 1: Подбор качества
                while current_size_kb > self.target_kb and quality >= self.min_quality:
                    buffer = BytesIO()
                    if save_format == "WEBP":
                        img.save(buffer, format=save_format, quality=quality, method=6)
                    else:
                        img.save(buffer, format=save_format, quality=quality, optimize=True)
                    
                    current_size_kb = len(buffer.getvalue()) / 1024
                    if current_size_kb <= self.target_kb:
                        break
                    
                    quality -= 5

                # Шаг 2: Уменьшение разрешения, если качества недостаточно
                if current_size_kb > self.target_kb and max_dim > self.min_dimension:
                    logger.info(f"Quality reduction insufficient. Resizing {max_dim}px -> {self.min_dimension}px")
                    ratio = self.min_dimension / max_dim
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Сбрасываем качество на максимум и пробуем снова
                    quality = 85
                    while current_size_kb > self.target_kb and quality >= self.min_quality:
                        buffer = BytesIO()
                        if save_format == "WEBP":
                            img.save(buffer, format=save_format, quality=quality, method=6)
                        else:
                            img.save(buffer, format=save_format, quality=quality, optimize=True)
                        
                        current_size_kb = len(buffer.getvalue()) / 1024
                        if current_size_kb <= self.target_kb:
                            break
                        quality -= 5

                # Финальная запись
                final_buffer = BytesIO()
                final_quality = max(quality, self.min_quality)
                if save_format == "WEBP":
                    img.save(final_buffer, format=save_format, quality=final_quality, method=6)
                else:
                    img.save(final_buffer, format=save_format, quality=final_quality, optimize=True)
                
                # Создаем директорию вывода, если нет
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, "wb") as f:
                    f.write(final_buffer.getvalue())

                final_size_kb = os.path.getsize(output_path) / 1024
                
                logger.info(
                    f"Compressed: {Path(input_path).name} | "
                    f"{original_size_kb:.1f}KB -> {final_size_kb:.1f}KB "
                    f"({(1 - final_size_kb/original_size_kb)*100:.1f}% reduction)"
                )
                
                return {
                    "success": True,
                    "original_kb": round(original_size_kb, 2),
                    "compressed_kb": round(final_size_kb, 2),
                    "reduction_percent": round((1 - final_size_kb/original_size_kb)*100, 1) if original_size_kb > 0 else 0,
                    "output_path": output_path
                }

        except Exception as e:
            logger.error(f"Compression error for {input_path}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
