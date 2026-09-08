"""
Speakly - модуль для транскрипции и обработки текста
"""

__version__ = "1.0.0"
__author__ = "Speakly Team"

# Экспортируем основные классы для удобного импорта
from .whisper_transcriber import WhisperTranscriber
from .text_processor import TextProcessor, SimpleTextProcessor

__all__ = [
    'WhisperTranscriber',
    'TextProcessor', 
    'SimpleTextProcessor'
]