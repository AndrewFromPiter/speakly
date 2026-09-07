"""
Модуль для пост-обработки транскрипции с использованием Ollama.
Обрабатывает текст целиком без разделения.
"""

import logging
import time
import re
import requests
from typing import Optional, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TextProcessor:
    """
    Пост-обработка текста транскрипции через Ollama.
    """
    
    def __init__(self, model_type="ollama", model_name="mistral", device="cpu"):
        self.model_type = model_type
        self.model_name = model_name
        self.ollama_host = "http://127.0.0.1:11434"
        self.available = False
        self.timeout = 900  # 15 минут таймаут для больших текстов
        self._check_ollama()
    
    def _check_ollama(self):
        """Проверяет доступность Ollama и наличие модели."""
        try:
            response = requests.get(f"{self.ollama_host}/api/tags", timeout=5)
            
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                
                found = False
                for model in model_names:
                    if model == self.model_name or model == f"{self.model_name}:latest":
                        found = True
                        self.model_name = model
                        break
                    if model.startswith(f"{self.model_name}:"):
                        found = True
                        self.model_name = model
                        break
                
                if not found:
                    logger.warning(f"Модель '{self.model_name}' не найдена")
                    logger.info(f"Доступные модели: {', '.join(model_names) if model_names else 'нет'}")
                    self.available = False
                else:
                    logger.info(f"✅ Модель '{self.model_name}' найдена")
                    self.available = True
            else:
                logger.error(f"Ollama сервер не отвечает: {response.status_code}")
                self.available = False
                
        except requests.exceptions.ConnectionError:
            logger.error("❌ Ollama не запущен")
            self.available = False
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            self.available = False
    
    def process(self, text: str, task: str = "structure") -> str:
        """
        Обрабатывает текст с помощью Ollama.
        
        Args:
            text: исходный текст
            task: тип обработки:
                - clean: очистка
                - structure: структурирование
                - summary: краткий конспект
                - formatted: форматирование
                - detailed: подробный аккуратный конспект (НОВЫЙ!)
        """
        if not text:
            return ""
        
        if not self.available:
            logger.warning("Ollama недоступен, возвращаю исходный текст")
            return text
        
        if len(text) < 100:
            logger.warning("Текст слишком короткий для обработки")
            return text
        
        prompt = self._get_prompt(text, task)
        logger.info(f"🔄 Обработка текста (задача: {task})...")
        logger.info(f"📝 Длина текста: {len(text)} символов")
        
        start_time = time.time()
        
        try:
            result = self._generate(prompt)
            elapsed = time.time() - start_time
            logger.info(f"✅ Готово за {elapsed:.1f} сек. ({elapsed/60:.1f} мин)")
            
            if not result or len(result) < 10:
                logger.warning("Результат слишком короткий, возможно ошибка")
                return text
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return text
    
    def _generate(self, prompt: str) -> str:
        """Отправляет запрос в Ollama с увеличенным таймаутом."""
        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "top_p": 0.9,
                        "num_ctx": 8192,  # Увеличиваем контекст для больших текстов
                    }
                },
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json().get("response", "")
                if not result:
                    logger.warning("Ollama вернул пустой ответ")
                return result
            else:
                raise RuntimeError(f"Ошибка Ollama: {response.status_code} - {response.text}")
                
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Таймаут {self.timeout} секунд. Попробуйте использовать модель поменьше.")
        except requests.exceptions.ConnectionError:
            raise RuntimeError("Не удалось подключиться к Ollama. Запустите: ollama serve")
    
    def _get_prompt(self, text: str, task: str) -> str:
        """Возвращает промпт для задачи."""
        prompts = {
            "clean": self._clean_prompt(text),
            "structure": self._structure_prompt(text),
            "summary": self._summary_prompt(text),
            "formatted": self._formatted_prompt(text),
            "detailed": self._detailed_prompt(text),  # НОВЫЙ РЕЖИМ
        }
        return prompts.get(task, prompts["structure"])
    
    # ---------- Промпты ----------
    
    def _clean_prompt(self, text: str) -> str:
        return f"""Ты — профессиональный редактор текста. Исправь ошибки в транскрипции лекции.

Задача:
1. Исправь грамматические и пунктуационные ошибки
2. Удали повторы и слова-паразиты
3. Сохрани смысл и терминологию

Текст для обработки:
{text}

Отредактированный текст:"""
    
    def _structure_prompt(self, text: str) -> str:
        return f"""Ты — преподаватель. Создай структурированный конспект лекции.

Задача:
1. Разбей текст на логические разделы
2. Создай заголовки для каждого раздела
3. Выдели ключевые термины
4. Используй списки

Формат:
# Заголовок
## Раздел 1
**Термин** — определение
- пункт 1

## Раздел 2
...

Текст:
{text}

Конспект:"""
    
    def _summary_prompt(self, text: str) -> str:
        return f"""Ты — студент. Сделай краткий конспект лекции.

Задача:
1. Выдели главные темы
2. Используй структуру с заголовками
3. Убери второстепенные детали
4. Сохрани важные термины

Текст лекции:
{text}

Краткий конспект:"""
    
    def _formatted_prompt(self, text: str) -> str:
        return f"""Ты — редактор. Отформатируй текст лекции.

Задача:
1. Разбей на абзацы по смыслу
2. Исправь ошибки
3. Добавь правильную пунктуацию

Текст:
{text}

Форматированный текст:"""
    
    def _detailed_prompt(self, text: str) -> str:
        """НОВЫЙ: Подробный аккуратный конспект."""
        return f"""Ты — отличник, который делает подробный, аккуратный и структурированный конспект лекции. 

ВАЖНО:
1. Сохрани ВСЮ важную информацию из лекции
2. Структурируй по темам и подтемам
3. Используй четкие заголовки и подзаголовки
4. Выделяй КЛЮЧЕВЫЕ ТЕРМИНЫ жирным шрифтом (через **)
5. Используй маркированные и нумерованные списки
6. Добавляй краткие пояснения к терминам
7. Сохраняй логику и последовательность лекции
8. Убирай только повторы, слова-паразиты и воду
9. Конспект должен быть понятен даже тому, кто не был на лекции

ФОРМАТ ВЫВОДА:
# НАЗВАНИЕ ЛЕКЦИИ (если есть)

## Тема 1: Название
- **Ключевой термин** — краткое определение
- Важный факт или пояснение
- Дополнительный пункт

## Тема 2: Название
...

ТЕКСТ ЛЕКЦИИ:
{text}

ПОДРОБНЫЙ АККУРАТНЫЙ КОНСПЕКТ:"""


class SimpleTextProcessor:
    """Простой процессор без LLM."""
    
    def process(self, text: str, task: str = "clean") -> str:
        if not text:
            return ""
        
        if task == "clean":
            return self._clean_text(text)
        elif task == "structure":
            return self._structure_text(text)
        else:
            return text
    
    def _clean_text(self, text: str) -> str:
        text = re.sub(r'\s+', ' ', text)
        words = text.split()
        cleaned = []
        prev = ""
        for word in words:
            if word.lower() != prev.lower():
                cleaned.append(word)
                prev = word
        text = " ".join(cleaned)
        
        sentences = text.split('. ')
        sentences = [s.strip() for s in sentences if s.strip()]
        text = '. '.join(sentences)
        if text and not text.endswith('.'):
            text += '.'
        return text
    
    def _structure_text(self, text: str) -> str:
        sentences = text.split('. ')
        paragraphs = []
        for i in range(0, len(sentences), 5):
            para = '. '.join(sentences[i:i+5])
            if para:
                paragraphs.append(para.strip())
        return '\n\n'.join(paragraphs)