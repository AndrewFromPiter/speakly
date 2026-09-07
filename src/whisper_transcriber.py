"""
Модуль для транскрипции аудио файлов с помощью faster-whisper.
НЕ использует стандартный whisper и torch.
"""

from pathlib import Path
import os
import tempfile
import logging
import subprocess
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class WhisperTranscriber:
    """
    Модуль для транскрипции аудио файлов с помощью faster-whisper.
    Использует только CPU, без CUDA.
    """
    
    def __init__(self, model_name="base", device="cpu", chunk_duration_seconds=600):
        """
        Инициализация транскрибера.
        
        Args:
            model_name: название модели (tiny, base, small, medium)
            device: пока только "cpu"
            chunk_duration_seconds: длительность чанка в секундах
        """
        self.model_name = model_name
        self.device = "cpu"  # Фиксированно CPU
        self.chunk_duration_seconds = chunk_duration_seconds
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Загружает модель faster-whisper на CPU."""
        logger.info(f"Загрузка модели '{self.model_name}' на CPU...")
        load_start = time.time()
        
        try:
            from faster_whisper import WhisperModel
            
            # Для CPU используем int8 для скорости
            self.model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                num_workers=1
            )
            
            load_time = time.time() - load_start
            logger.info(f"✅ Модель загружена через faster-whisper за {load_time:.1f} сек.")
            
        except ImportError:
            raise ImportError(
                "Установите faster-whisper:\n"
                "pip install faster-whisper"
            )
        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}")
            raise

    def _convert_to_wav(self, input_path):
        """Конвертирует аудиофайл в WAV (16 кГц, моно) используя ffmpeg."""
        logger.info(f"Конвертация файла в WAV формат...")
        convert_start = time.time()
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            output_path = tmp_file.name
        
        try:
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-ac', '1',
                '-ar', '16000',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg ошибка: {result.stderr}")
            
            convert_time = time.time() - convert_start
            logger.info(f"Файл сконвертирован за {convert_time:.1f} сек.")
            return output_path
            
        except FileNotFoundError:
            raise RuntimeError(
                "FFmpeg не найден. Установите FFmpeg:\n"
                "Windows: winget install FFmpeg\n"
                "Или скачайте с https://ffmpeg.org/download.html"
            )
        except Exception as e:
            if os.path.exists(output_path):
                os.unlink(output_path)
            raise e

    def _split_audio(self, wav_path):
        """Разбивает аудиофайл на части используя ffmpeg."""
        logger.info(f"Разбиение аудио на части по {self.chunk_duration_seconds} секунд...")
        split_start = time.time()
        
        # Получаем длительность аудио
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            wav_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        total_duration = float(result.stdout.strip())
        
        if total_duration <= self.chunk_duration_seconds:
            logger.info("Аудиофайл не требует разбиения.")
            return [wav_path]
        
        # Разбиваем на чанки
        chunk_paths = []
        num_chunks = int(total_duration // self.chunk_duration_seconds) + 1
        
        for i in range(num_chunks):
            start_time = i * self.chunk_duration_seconds
            
            with tempfile.NamedTemporaryFile(suffix=f"_chunk_{i}.wav", delete=False) as tmp_file:
                chunk_path = tmp_file.name
            
            cmd = [
                'ffmpeg',
                '-i', wav_path,
                '-ss', str(start_time),
                '-t', str(self.chunk_duration_seconds),
                '-ac', '1',
                '-ar', '16000',
                '-y',
                chunk_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            chunk_paths.append(chunk_path)
        
        split_time = time.time() - split_start
        logger.info(f"Аудио разбито на {len(chunk_paths)} частей за {split_time:.1f} сек.")
        return chunk_paths

    def _transcribe_chunk(self, chunk_path, chunk_num, total_chunks):
        """Транскрибирует один аудиочанк."""
        chunk_start = time.time()
        logger.info(f"Транскрипция части {chunk_num}/{total_chunks}...")
        
        try:
            segments, info = self.model.transcribe(
                chunk_path,
                beam_size=5,
                language="ru",
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    threshold=0.5
                )
            )
            
            detected_lang = info.language
            detected_prob = info.language_probability
            logger.info(f"Язык: '{detected_lang}' (вероятность: {detected_prob:.2f})")
            
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text)
            
            text = " ".join(text_parts).strip()
            chunk_time = time.time() - chunk_start
            logger.info(f"Часть {chunk_num} готова за {chunk_time:.1f} сек. ({len(text)} символов)")
            return text
            
        except Exception as e:
            logger.error(f"Ошибка транскрипции части {chunk_num}: {e}")
            return ""

    def transcribe(self, audio_file_path):
        """Основной метод для транскрипции аудиофайла."""
        total_start = time.time()
        
        if not self.model:
            raise RuntimeError("Модель не загружена.")

        audio_file_path = str(Path(audio_file_path))
        if not os.path.exists(audio_file_path):
            raise FileNotFoundError(f"Файл не найден: {audio_file_path}")

        temp_files = []
        try:
            # Шаг 1: Конвертация в WAV
            wav_path = self._convert_to_wav(audio_file_path)
            temp_files.append(wav_path)

            # Шаг 2: Разбиение на части
            chunk_paths = self._split_audio(wav_path)
            temp_files.extend([p for p in chunk_paths if p != wav_path])

            # Шаг 3: Транскрипция
            full_transcript_parts = []
            for i, chunk_path in enumerate(chunk_paths, 1):
                text = self._transcribe_chunk(chunk_path, i, len(chunk_paths))
                if text:
                    full_transcript_parts.append(text)

            final_transcript = " ".join(full_transcript_parts)
            
            total_time = time.time() - total_start
            logger.info("=" * 50)
            logger.info(f"✅ ТРАНСКРИПЦИЯ ЗАВЕРШЕНА")
            logger.info(f"⏱️  Время: {total_time:.1f} сек ({total_time/60:.1f} мин)")
            logger.info(f"📊 Длина текста: {len(final_transcript)} символов")
            logger.info(f"💻 Устройство: CPU")
            logger.info("=" * 50)
            
            return final_transcript

        except Exception as e:
            logger.error(f"Ошибка: {e}")
            raise
        finally:
            # Очистка временных файлов
            for file_path in temp_files:
                if os.path.exists(file_path):
                    try:
                        os.unlink(file_path)
                    except OSError:
                        pass