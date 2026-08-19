from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseParser(ABC):
    @abstractmethod
    def fetch(self, time_window_hours: int) -> List[Dict[str, Any]]:
        """Возвращает список RawMeme"""
        pass