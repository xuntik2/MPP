import os
from PIL import Image
from io import BytesIO
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ImageCompressor:
    def __init__(self, target_kb: int = 150, min_quality: int = 60, min_dimension: int = 800):
        self.target_kb = target_kb
        self.min_quality = min_quality
        self.min_dimension = min_dimension

    def compress(self, input_path: str, output_path: str) -> Dict[str, Any]:
        """
        Сжимает изображение до target_kb.
        Возвращает словарь: {"success": bool, "original_kb": float, "compressed_kb": float, "error": str}
        """
        if not os.path.exists(input_path):
            logger.error(f"File not found: {input_path}")
            return {"success": False, "error": "File not found"}

        try:
            with Image.open(input_path) as img:
                original_size = os.path.getsize(input_path) / 1024
                
                # Конвертация в RGB для JPEG/WebP (убираем альфа-канал)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                width, height = img.size
                max_dim = max(width, height)
                
                quality = 85
                current_img = img
                
                # Этап 1: Подбор качества без изменения размера
                while quality >= self.min_quality:
                    buffer = BytesIO()
                    current_img.save(buffer, format="WEBP", quality=quality, optimize=True)
                    size_kb = len(buffer.getvalue()) / 1024
                    
                    if size_kb <= self.target_kb:
                        # Успех, записываем файл
                        with open(output_path, 'wb') as f:
                            f.write(buffer.getvalue())
                        
                        logger.info(f"Compressed {input_path}: {original_size:.1f}KB -> {size_kb:.1f}KB (q={quality})")
                        return {
                            "success": True,
                            "original_kb": round(original_size, 2),
                            "compressed_kb": round(size_kb, 2),
                            "ratio": round((1 - size_kb/original_size)*100, 1) if original_size > 0 else 0
                        }
                    
                    quality -= 5

                # Этап 2: Если качество упало до минимума, а размер все еще велик -> уменьшаем разрешение
                if max_dim > self.min_dimension:
                    logger.warning(f"Quality min reached, resizing {input_path}...")
                    ratio = self.min_dimension / max_dim
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Пробуем сохранить с качеством по умолчанию (85) после ресайза
                    buffer = BytesIO()
                    resized_img.save(buffer, format="WEBP", quality=85, optimize=True)
                    size_kb = len(buffer.getvalue()) / 1024
                    
                    # Если все еще велико, снижаем качество снова
                    q = 85
                    while size_kb > self.target_kb and q >= self.min_quality:
                        buffer = BytesIO()
                        resized_img.save(buffer, format="WEBP", quality=q, optimize=True)
                        size_kb = len(buffer.getvalue()) / 1024
                        q -= 5
                    
                    with open(output_path, 'wb') as f:
                        f.write(buffer.getvalue())
                        
                    logger.info(f"Compressed with resize {input_path}: {original_size:.1f}KB -> {size_kb:.1f}KB")
                    return {
                        "success": True,
                        "original_kb": round(original_size, 2),
                        "compressed_kb": round(size_kb, 2),
                        "ratio": round((1 - size_kb/original_size)*100, 1) if original_size > 0 else 0
                    }

                # Этап 3: Предельный случай (нельзя уменьшить ни качество, ни размер)
                # Сохраняем как есть с минимальным качеством, даже если > target_kb
                logger.warning(f"Cannot compress {input_path} below target. Saving best effort.")
                buffer = BytesIO()
                current_img.save(buffer, format="WEBP", quality=self.min_quality, optimize=True)
                with open(output_path, 'wb') as f:
                    f.write(buffer.getvalue())
                
                final_size = os.path.getsize(output_path) / 1024
                return {
                    "success": True, # Считаем успехом, что файл сохранен
                    "original_kb": round(original_size, 2),
                    "compressed_kb": round(final_size, 2),
                    "warning": "Target size not reachable without significant quality loss",
                    "ratio": 0
                }

        except Exception as e:
            logger.error(f"Compression error for {input_path}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
