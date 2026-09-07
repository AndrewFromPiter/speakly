#!/usr/bin/env python3
"""
Полный пайплайн: транскрипция + обработка текста.
"""

import sys
import os
import time
from datetime import datetime
from pathlib import Path
from whisper_transcriber import WhisperTranscriber
from text_processor import TextProcessor, SimpleTextProcessor


def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}ч {minutes}м {secs}с"
    elif minutes > 0:
        return f"{minutes}м {secs}с"
    return f"{secs}с"


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_menu():
    clear_screen()
    print_header("🎙️  ТРАНСКРИПЦИЯ + ОБРАБОТКА ТЕКСТА")
    print("\n📋 ГЛАВНОЕ МЕНЮ:")
    print("  1. Транскрипция аудио + обработка")
    print("  2. Обработка готового текста (из файла)")
    print("  3. Тест LLM на примере")
    print("  0. Выход")
    print("\n" + "-" * 60)


def print_processing_modes():
    print("\n📝 РЕЖИМЫ ОБРАБОТКИ:")
    print("  1. Только транскрипция (без обработки)")
    print("  2. Очистка текста (Simple)")
    print("  3. Структурирование (Simple)")
    print("  4. LLM очистка (нужен Ollama)")
    print("  5. LLM структурирование (нужен Ollama)")
    print("  6. LLM краткий конспект (нужен Ollama)")
    print("  7. LLM форматирование (нужен Ollama)")
    print("  8. ✨ LLM ПОДРОБНЫЙ АККУРАТНЫЙ КОНСПЕКТ (нужен Ollama) ✨")


def print_llm_models():
    print("\n🤖 ДОСТУПНЫЕ LLM МОДЕЛИ:")
    print("  1. mistral (7B, хороша для русского) [по умолчанию]")
    print("  2. gemma2:9b (9B, качественная)")
    print("  3. qwen2.5-coder:7b (7.6B, для кода)")
    print("  4. qwen2.5-coder:3b (3.1B, быстрая)")
    print("  5. Другая (ввести вручную)")


def get_user_choice(prompt, min_val, max_val):
    while True:
        try:
            choice = input(f"\n{prompt} ").strip()
            if not choice:
                return None
            choice = int(choice)
            if min_val <= choice <= max_val:
                return choice
            print(f"❌ Введите число от {min_val} до {max_val}")
        except ValueError:
            print("❌ Введите число")


def get_llm_model():
    print_llm_models()
    choice = get_user_choice("Выберите модель (1-5):", 1, 5)
    
    models = {
        1: "mistral",
        2: "gemma2:9b",
        3: "qwen2.5-coder:7b",
        4: "qwen2.5-coder:3b",
    }
    
    if choice in models:
        return models[choice]
    elif choice == 5:
        return input("Введите название модели: ").strip()
    else:
        return "mistral"


def read_text_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return None


def save_text_file(text, prefix):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{prefix}_{timestamp}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(text)
    return filename


def process_text(text, mode, model_name="mistral"):
    if not text:
        return "", "пустой текст"
    
    start_time = time.time()
    
    modes = {
        1: ("без обработки", None, None),
        2: ("очистка (Simple)", SimpleTextProcessor, "clean"),
        3: ("структурирование (Simple)", SimpleTextProcessor, "structure"),
    }
    
    llm_modes = {
        4: ("LLM очистка", "clean"),
        5: ("LLM структурирование", "structure"),
        6: ("LLM краткий конспект", "summary"),
        7: ("LLM форматирование", "formatted"),
        8: ("LLM подробный конспект", "detailed"),  # НОВЫЙ РЕЖИМ
    }
    
    if mode in modes:
        name, processor_class, task = modes[mode]
        if processor_class:
            processor = processor_class()
            processed = processor.process(text, task=task)
        else:
            processed = text
    
    elif mode in llm_modes:
        name, task = llm_modes[mode]
        try:
            print(f"🔄 Использую модель: {model_name}")
            print(f"⏳ Ожидайте, обработка может занять 5-10 минут...")
            processor = TextProcessor(model_type="ollama", model_name=model_name)
            processed = processor.process(text, task=task)
        except Exception as e:
            print(f"⚠️ Ошибка LLM: {e}")
            print("Использую простую обработку...")
            processor = SimpleTextProcessor()
            processed = processor.process(text, task="structure")
            name = "структурирование (fallback)"
    
    else:
        print("❌ Неверный режим")
        return text, "без обработки"
    
    elapsed = time.time() - start_time
    print(f"⏱️  Обработка заняла: {format_time(elapsed)}")
    
    return processed, name


def mode_transcription():
    print_header("🎤 ТРАНСКРИПЦИЯ АУДИО")
    
    audio_file = input("\n📁 Введите путь к аудиофайлу: ").strip().strip('"').strip("'")
    
    if not os.path.exists(audio_file):
        print(f"❌ Файл не найден: {audio_file}")
        input("\nНажмите Enter для продолжения...")
        return
    
    print("\n🤖 Выберите модель Whisper:")
    print("  1. tiny (быстро, низкая точность)")
    print("  2. base (средне)")
    print("  3. small (рекомендуется)")
    print("  4. medium (медленно, высокая точность)")
    model_choice = get_user_choice("Выберите (1-4):", 1, 4)
    
    whisper_models = {1: "tiny", 2: "base", 3: "small", 4: "medium"}
    whisper_model = whisper_models.get(model_choice, "small")
    
    print_processing_modes()
    mode = get_user_choice("Выберите режим (1-8):", 1, 8)
    
    llm_model = "mistral"
    use_llm = mode in [4, 5, 6, 7, 8]
    if use_llm:
        print("\n🔄 Проверка Ollama...")
        try:
            import requests
            requests.get("http://localhost:11434/api/tags", timeout=3)
            print("✅ Ollama доступен")
            llm_model = get_llm_model()
            print(f"✅ Выбрана модель: {llm_model}")
        except:
            print("❌ Ollama не доступен, использую простую обработку")
            use_llm = False
            mode = 3
    
    print("\n" + "-" * 60)
    print("⏳ Начинаю транскрипцию...")
    start_time = time.time()
    
    try:
        transcriber = WhisperTranscriber(model_name=whisper_model)
        raw_text = transcriber.transcribe(audio_file)
        
        if not raw_text:
            print("❌ Транскрипция пуста")
            input("\nНажмите Enter для продолжения...")
            return
        
        transcribe_time = time.time() - start_time
        print(f"\n✅ Транскрипция завершена за {format_time(transcribe_time)}")
        print(f"📊 Размер: {len(raw_text)} символов")
        
        raw_file = save_text_file(raw_text, "transcript_raw")
        print(f"💾 Сырой текст сохранен: {raw_file}")
        
        print("\n" + "-" * 60)
        print("🔄 ОБРАБОТКА ТЕКСТА")
        
        processed_text, mode_name = process_text(raw_text, mode, llm_model)
        
        processed_file = save_text_file(processed_text, "transcript_processed")
        print(f"💾 Обработанный текст сохранен: {processed_file}")
        
        print("\n" + "=" * 60)
        print(f"📝 ПРЕВЬЮ ({mode_name}):")
        print("=" * 60)
        preview = processed_text[:800] + "..." if len(processed_text) > 800 else processed_text
        print(preview)
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНажмите Enter для продолжения...")


def mode_process_text():
    print_header("📄 ОБРАБОТКА ТЕКСТОВОГО ФАЙЛА")
    
    text_file = input("\n📁 Введите путь к текстовому файлу: ").strip().strip('"').strip("'")
    
    if not os.path.exists(text_file):
        print(f"❌ Файл не найден: {text_file}")
        input("\nНажмите Enter для продолжения...")
        return
    
    text = read_text_file(text_file)
    if text is None:
        input("\nНажмите Enter для продолжения...")
        return
    
    print(f"✅ Файл загружен: {len(text)} символов")
    
    print_processing_modes()
    mode = get_user_choice("Выберите режим (1-8):", 1, 8)
    
    llm_model = "mistral"
    use_llm = mode in [4, 5, 6, 7, 8]
    if use_llm:
        print("\n🔄 Проверка Ollama...")
        try:
            import requests
            requests.get("http://localhost:11434/api/tags", timeout=3)
            print("✅ Ollama доступен")
            llm_model = get_llm_model()
            print(f"✅ Выбрана модель: {llm_model}")
        except:
            print("❌ Ollama не доступен, использую простую обработку")
            use_llm = False
            mode = 3
    
    print("\n" + "-" * 60)
    print("🔄 ОБРАБОТКА ТЕКСТА")
    
    processed_text, mode_name = process_text(text, mode, llm_model)
    
    output_file = save_text_file(processed_text, "processed")
    print(f"💾 Обработанный текст сохранен: {output_file}")
    
    print("\n" + "=" * 60)
    print(f"📝 РЕЗУЛЬТАТ ({mode_name}):")
    print("=" * 60)
    preview = processed_text[:800] + "..." if len(processed_text) > 800 else processed_text
    print(preview)
    print("=" * 60)
    
    input("\nНажмите Enter для продолжения...")


def mode_test_llm():
    print_header("🧪 ТЕСТ LLM")
    
    print("\n🔄 Проверка Ollama...")
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            print(f"✅ Ollama доступен")
            print(f"📚 Доступные модели: {', '.join(model_names) if model_names else 'нет'}")
            if not model_names:
                print("\n❌ Нет моделей. Скачайте: ollama pull mistral")
                input("\nНажмите Enter для продолжения...")
                return
        else:
            print("❌ Ollama не отвечает")
            input("\nНажмите Enter для продолжения...")
            return
    except:
        print("❌ Ollama не запущен")
        input("\nНажмите Enter для продолжения...")
        return
    
    llm_model = get_llm_model()
    print(f"✅ Выбрана модель: {llm_model}")
    
    example_text = """
    ну и так мы продолжаем нашу лекцию по анатомии сегодня мы будем говорить о сердечно-сосудистой системе ну сердце это мышечный орган который качает кровь по сосудам аорта это самый крупный сосуд который отходит от левого желудочка и кровь по артериям идет от сердца а по венам кровь возвращается к сердцу так вот еще есть такое понятие как кровеносное давление это давление которое кровь оказывает на стенки сосудов ну и оно измеряется в миллиметрах ртутного столба систолическое давление это давление в момент сокращения сердца а диастолическое в момент расслабления
    """
    
    print("\n📝 Тестовый текст (транскрипция лекции):")
    print("-" * 60)
    print(example_text)
    print("-" * 60)
    
    print("\n📝 Режимы обработки:")
    print("  1. Очистка")
    print("  2. Структурирование")
    print("  3. Краткий конспект")
    print("  4. Форматирование")
    print("  5. ✨ Подробный аккуратный конспект")
    mode = get_user_choice("Выберите (1-5):", 1, 5)
    
    task_map = {1: "clean", 2: "structure", 3: "summary", 4: "formatted", 5: "detailed"}
    task = task_map.get(mode, "clean")
    
    print(f"\n🔄 Обработка моделью {llm_model}...")
    start_time = time.time()
    
    try:
        processor = TextProcessor(model_type="ollama", model_name=llm_model)
        result = processor.process(example_text, task=task)
        
        elapsed = time.time() - start_time
        
        print(f"\n✅ Готово за {format_time(elapsed)}")
        print("\n" + "=" * 60)
        print("📝 РЕЗУЛЬТАТ:")
        print("=" * 60)
        print(result)
        print("=" * 60)
        
        output_file = save_text_file(result, "llm_test")
        print(f"\n💾 Результат сохранен: {output_file}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    input("\nНажмите Enter для продолжения...")


def main():
    while True:
        print_menu()
        choice = get_user_choice("Выберите опцию (0-3):", 0, 3)
        
        if choice == 0:
            print("\n👋 До свидания!")
            break
        elif choice == 1:
            mode_transcription()
        elif choice == 2:
            mode_process_text()
        elif choice == 3:
            mode_test_llm()
        else:
            print("❌ Неверный выбор")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Программа прервана пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        input("\nНажмите Enter для выхода...")