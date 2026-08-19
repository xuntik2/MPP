import os
from PIL import Image
from io import BytesIO
from typing import Tuple, Optional

class ImageCompressor:
    TARGET_SIZE_KB = 150
    MIN_QUALITY = 60
    MIN_DIMENSION = 800

    @staticmethod
    def compress_image(input_path: str, output_path: str) -> Tuple[bool, int, int]:
        """
        Сжимает изображение до TARGET_SIZE_KB.
        Возвращает: (success, original_size_kb, new_size_kb)
        """
        if not os.path.exists(input_path):
            return False, 0, 0

        try:
            with Image.open(input_path) as img:
                original_size = os.path.getsize(input_path) / 1024
                
                # Конвертация в RGB если нужно (для JPEG/WebP)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                width, height = img.size
                max_dim = max(width, height)
                
                quality = 85
                current_dim = max_dim
                
                # Итеративный подбор качества и размера
                while True:
                    buffer = BytesIO()
                    
                    # Сохраняем в буфер с текущими параметрами
                    img.save(buffer, format="WEBP", quality=quality, optimize=True)
                    size_kb = buffer.tell() / 1024
                    
                    if size_kb <= ImageCompressor.TARGET_SIZE_KB or quality < ImageCompressor.MIN_QUALITY:
                        # Успех или достигнут минимум качества
                        with open(output_path, 'wb') as f:
                            f.write(buffer.getvalue())
                        return True, int(original_size), int(size_kb)
                    
                    # Уменьшаем качество
                    quality -= 5
                    
                    # Если качество упало ниже минимума, уменьшаем размер
                    if quality < ImageCompressor.MIN_QUALITY:
                        quality = 85 # Сброс качества
                        current_dim = int(current_dim * 0.85)
                        
                        if current_dim < ImageCompressor.MIN_DIMENSION:
                            # Предельный случай: сохраняем как есть с минимальным качеством
                            img.save(buffer, format="WEBP", quality=ImageCompressor.MIN_QUALITY, optimize=True)
                            with open(output_path, 'wb') as f:
                                f.write(buffer.getvalue())
                            final_size = os.path.getsize(output_path) / 1024
                            return True, int(original_size), int(final_size)
                        
                        # Ресайз
                        scale = current_dim / max_dim
                        new_size = (int(width * scale), int(height * scale))
                        img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
                        # Обновляем img для следующей итерации (но не меняем оригинал в цикле неправильно)
                        # В данном упрощенном варианте мы просто перезапустим логику с новым размером в следующем шаге
                        # Для простоты здесь делаем ресайз один раз при падении качества
                        img = img_resized
                        width, height = new_size
                        max_dim = current_dim

        except Exception as e:
            print(f"Error compressing {input_path}: {e}")
            return False, 0, 0

        return False, 0, 0