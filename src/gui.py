"""
Графический интерфейс для программы транскрипции и обработки текста.
Использует PyQt5.
"""

import sys
import os
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QProgressBar, QFileDialog,
    QMessageBox, QTabWidget, QGroupBox, QRadioButton, QButtonGroup,
    QComboBox, QCheckBox, QSpinBox, QSplitter, QStatusBar,
    QListWidget, QListWidgetItem, QFrame, QGridLayout
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSettings,
    QPropertyAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QFont, QIcon, QPixmap, QPalette, QColor,
    QTextCursor, QFontDatabase
)

# Импорт наших модулей
from whisper_transcriber import WhisperTranscriber
from text_processor import TextProcessor, SimpleTextProcessor


# ============================================================================
# ПОТОКИ ДЛЯ ФОНОВОЙ ОБРАБОТКИ
# ============================================================================

class TranscriptionThread(QThread):
    """Поток для транскрипции аудио."""
    
    progress = pyqtSignal(int, str)  # процент, сообщение
    finished = pyqtSignal(str)       # результат (текст)
    error = pyqtSignal(str)          # ошибка
    
    def __init__(self, audio_path, model_name="small", device="auto"):
        super().__init__()
        self.audio_path = audio_path
        self.model_name = model_name
        self.device = device
    
    def run(self):
        try:
            self.progress.emit(0, "Загрузка модели...")
            transcriber = WhisperTranscriber(
                model_name=self.model_name,
                device=self.device
            )
            
            self.progress.emit(20, "Конвертация и разбиение аудио...")
            result = transcriber.transcribe(self.audio_path)
            
            self.progress.emit(100, "Готово!")
            self.finished.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))


class ProcessingThread(QThread):
    """Поток для обработки текста."""
    
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, text, mode="detailed", model_name="mistral"):
        super().__init__()
        self.text = text
        self.mode = mode
        self.model_name = model_name
    
    def run(self):
        try:
            self.progress.emit(0, "Подготовка к обработке...")
            
            if self.mode in ["clean", "structure"]:
                processor = SimpleTextProcessor()
            else:
                processor = TextProcessor(
                    model_type="ollama",
                    model_name=self.model_name
                )
            
            self.progress.emit(30, "Обработка текста...")
            result = processor.process(self.text, task=self.mode)
            
            self.progress.emit(100, "Готово!")
            self.finished.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))


# ============================================================================
# ГЛАВНОЕ ОКНО
# ============================================================================

class MainWindow(QMainWindow):
    """Главное окно приложения."""
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Speakly", "TranscriptionApp")
        self.transcription_thread = None
        self.processing_thread = None
        self.current_audio_path = None
        self.current_text = ""
        self.init_ui()
        self.load_settings()
        self.check_ollama()
    
    def init_ui(self):
        """Инициализация интерфейса."""
        self.setWindowTitle("🎙️ Speakly - Транскрипция и конспектирование")
        self.setGeometry(100, 100, 1200, 800)
        
        # Центральный виджет
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        
        # Верхняя панель с заголовком
        header = self.create_header()
        layout.addWidget(header)
        
        # Основная область с вкладками
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ccc;
                border-radius: 5px;
                background: white;
            }
            QTabBar::tab {
                padding: 8px 20px;
                margin: 2px;
                border-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #4CAF50;
                color: white;
            }
        """)
        layout.addWidget(self.tabs)
        
        # Создаем вкладки
        self.tabs.addTab(self.create_transcription_tab(), "🎤 Транскрипция")
        self.tabs.addTab(self.create_processing_tab(), "📝 Обработка")
        self.tabs.addTab(self.create_settings_tab(), "⚙️ Настройки")
        self.tabs.addTab(self.create_history_tab(), "📚 История")
        
        # Строка статуса
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готов к работе")
        
        # Применяем стили
        self.apply_styles()
    
    def create_header(self):
        """Создает заголовок приложения."""
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2c3e50, stop:1 #3498db);
                border-radius: 8px;
                padding: 10px;
            }
            QLabel {
                color: white;
                font-size: 18px;
                font-weight: bold;
            }
        """)
        
        layout = QHBoxLayout(header)
        
        title = QLabel("🎙️ Speakly - Умная транскрипция")
        title.setStyleSheet("font-size: 20px;")
        layout.addWidget(title)
        
        # Кнопка проверки Ollama
        self.ollama_status = QLabel("🔄 Проверка...")
        self.ollama_status.setStyleSheet("color: white; font-size: 14px;")
        layout.addStretch()
        layout.addWidget(self.ollama_status)
        
        return header
    
    def create_transcription_tab(self):
        """Создает вкладку транскрипции."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Верхняя панель с выбором файла
        file_group = QGroupBox("📁 Аудиофайл")
        file_layout = QHBoxLayout(file_group)
        
        self.file_label = QLabel("Файл не выбран")
        self.file_label.setStyleSheet("padding: 5px; background: #f0f0f0; border-radius: 4px;")
        file_layout.addWidget(self.file_label, 1)
        
        btn_select = QPushButton("📂 Выбрать файл")
        btn_select.clicked.connect(self.select_audio_file)
        file_layout.addWidget(btn_select)
        
        layout.addWidget(file_group)
        
        # Настройки транскрипции
        settings_group = QGroupBox("⚙️ Настройки")
        settings_layout = QGridLayout(settings_group)
        
        # Модель Whisper
        settings_layout.addWidget(QLabel("Модель Whisper:"), 0, 0)
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(["tiny", "base", "small", "medium"])
        self.whisper_model.setCurrentText("small")
        settings_layout.addWidget(self.whisper_model, 0, 1)
        
        # Устройство
        settings_layout.addWidget(QLabel("Устройство:"), 0, 2)
        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cpu", "cuda"])
        self.device_combo.setCurrentText("auto")
        settings_layout.addWidget(self.device_combo, 0, 3)
        
        # Чанки
        settings_layout.addWidget(QLabel("Длительность чанка (сек):"), 1, 0)
        self.chunk_size = QSpinBox()
        self.chunk_size.setRange(60, 3600)
        self.chunk_size.setValue(600)
        self.chunk_size.setSuffix(" сек")
        settings_layout.addWidget(self.chunk_size, 1, 1)
        
        # Кнопка запуска
        self.btn_transcribe = QPushButton("🚀 Начать транскрипцию")
        self.btn_transcribe.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #45a049;
            }
            QPushButton:disabled {
                background: #cccccc;
            }
        """)
        self.btn_transcribe.clicked.connect(self.start_transcription)
        settings_layout.addWidget(self.btn_transcribe, 1, 2, 1, 2)
        
        layout.addWidget(settings_group)
        
        # Прогресс
        progress_group = QGroupBox("📊 Прогресс")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("Ожидание")
        self.progress_label.setStyleSheet("color: #555;")
        progress_layout.addWidget(self.progress_label)
        
        layout.addWidget(progress_group)
        
        # Результат
        result_group = QGroupBox("📝 Результат транскрипции")
        result_layout = QVBoxLayout(result_group)
        
        self.result_text = QTextEdit()
        self.result_text.setFont(QFont("Courier New", 10))
        self.result_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
                background: #fafafa;
            }
        """)
        result_layout.addWidget(self.result_text)
        
        # Кнопки для результата
        btn_layout = QHBoxLayout()
        
        btn_copy = QPushButton("📋 Копировать")
        btn_copy.clicked.connect(self.copy_result)
        btn_layout.addWidget(btn_copy)
        
        btn_save = QPushButton("💾 Сохранить")
        btn_save.clicked.connect(self.save_result)
        btn_layout.addWidget(btn_save)
        
        self.btn_process = QPushButton("🔄 Обработать текст")
        self.btn_process.clicked.connect(self.process_transcribed_text)
        self.btn_process.setEnabled(False)
        btn_layout.addWidget(self.btn_process)
        
        btn_layout.addStretch()
        result_layout.addLayout(btn_layout)
        
        layout.addWidget(result_group)
        
        return tab
    
    def create_processing_tab(self):
        """Создает вкладку обработки текста."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Входной текст
        input_group = QGroupBox("📝 Входной текст")
        input_layout = QVBoxLayout(input_group)
        
        btn_load = QPushButton("📂 Загрузить текстовый файл")
        btn_load.clicked.connect(self.load_text_file)
        input_layout.addWidget(btn_load)
        
        self.input_text = QTextEdit()
        self.input_text.setFont(QFont("Courier New", 10))
        self.input_text.setPlaceholderText("Вставьте текст для обработки здесь...")
        input_layout.addWidget(self.input_text)
        
        layout.addWidget(input_group)
        
        # Настройки обработки
        settings_group = QGroupBox("⚙️ Настройки обработки")
        settings_layout = QGridLayout(settings_group)
        
        # Режим обработки
        settings_layout.addWidget(QLabel("Режим:"), 0, 0)
        self.process_mode = QComboBox()
        self.process_mode.addItems([
            "Очистка (Simple)",
            "Структурирование (Simple)",
            "LLM очистка",
            "LLM структурирование",
            "LLM краткий конспект",
            "LLM форматирование",
            "LLM подробный конспект"
        ])
        self.process_mode.setCurrentIndex(6)  # Подробный конспект
        self.process_mode.currentIndexChanged.connect(self.on_mode_changed)
        settings_layout.addWidget(self.process_mode, 0, 1)
        
        # Модель LLM
        settings_layout.addWidget(QLabel("LLM модель:"), 0, 2)
        self.llm_model = QComboBox()
        self.llm_model.addItems(["mistral", "gemma2:9b", "qwen2.5-coder:7b", "qwen2.5-coder:3b"])
        self.llm_model.setCurrentText("mistral")
        settings_layout.addWidget(self.llm_model, 0, 3)
        
        # Кнопка запуска
        self.btn_process_text = QPushButton("🚀 Обработать текст")
        self.btn_process_text.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #1976D2;
            }
            QPushButton:disabled {
                background: #cccccc;
            }
        """)
        self.btn_process_text.clicked.connect(self.start_processing)
        settings_layout.addWidget(self.btn_process_text, 1, 0, 1, 4)
        
        layout.addWidget(settings_group)
        
        # Прогресс обработки
        progress_group = QGroupBox("📊 Прогресс")
        progress_layout = QVBoxLayout(progress_group)
        
        self.process_progress = QProgressBar()
        progress_layout.addWidget(self.process_progress)
        
        self.process_label = QLabel("Ожидание")
        progress_layout.addWidget(self.process_label)
        
        layout.addWidget(progress_group)
        
        # Результат обработки
        result_group = QGroupBox("📝 Результат обработки")
        result_layout = QVBoxLayout(result_group)
        
        self.output_text = QTextEdit()
        self.output_text.setFont(QFont("Courier New", 10))
        self.output_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
                background: #fafafa;
            }
        """)
        result_layout.addWidget(self.output_text)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        
        btn_copy_out = QPushButton("📋 Копировать")
        btn_copy_out.clicked.connect(self.copy_output)
        btn_layout.addWidget(btn_copy_out)
        
        btn_save_out = QPushButton("💾 Сохранить")
        btn_save_out.clicked.connect(self.save_output)
        btn_layout.addWidget(btn_save_out)
        
        btn_layout.addStretch()
        result_layout.addLayout(btn_layout)
        
        layout.addWidget(result_group)
        
        return tab
    
    def create_settings_tab(self):
        """Создает вкладку настроек."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Общие настройки
        general_group = QGroupBox("🔧 Общие настройки")
        general_layout = QVBoxLayout(general_group)
        
        # Автосохранение
        self.auto_save = QCheckBox("Автосохранять результаты")
        self.auto_save.setChecked(True)
        general_layout.addWidget(self.auto_save)
        
        # Путь сохранения
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Папка для сохранения:"))
        self.save_path = QLabel(os.path.expanduser("~/Documents/Speakly"))
        path_layout.addWidget(self.save_path, 1)
        btn_change_path = QPushButton("Изменить")
        btn_change_path.clicked.connect(self.change_save_path)
        path_layout.addWidget(btn_change_path)
        general_layout.addLayout(path_layout)
        
        layout.addWidget(general_group)
        
        # Настройки Ollama
        ollama_group = QGroupBox("🤖 Ollama")
        ollama_layout = QVBoxLayout(ollama_group)
        
        ollama_info = QLabel(
            "Ollama используется для обработки текста с помощью LLM.\n"
            "Убедитесь, что Ollama запущен: ollama serve"
        )
        ollama_info.setWordWrap(True)
        ollama_info.setStyleSheet("color: #555; padding: 5px;")
        ollama_layout.addWidget(ollama_info)
        
        btn_check = QPushButton("🔄 Проверить Ollama")
        btn_check.clicked.connect(self.check_ollama)
        ollama_layout.addWidget(btn_check)
        
        layout.addWidget(ollama_group)
        
        # Информация
        info_group = QGroupBox("ℹ️ О программе")
        info_layout = QVBoxLayout(info_group)
        
        info_text = QLabel(
            "Speakly - программа для транскрипции аудио и создания конспектов.\n\n"
            "Технологии:\n"
            "• Whisper - распознавание речи\n"
            "• Ollama - обработка текста\n"
            "• PyQt5 - графический интерфейс\n\n"
            "Версия: 1.0.0"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        
        layout.addWidget(info_group)
        
        layout.addStretch()
        return tab
    
    def create_history_tab(self):
        """Создает вкладку истории."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.load_history_item)
        layout.addWidget(self.history_list)
        
        btn_clear = QPushButton("🗑️ Очистить историю")
        btn_clear.clicked.connect(self.clear_history)
        layout.addWidget(btn_clear)
        
        self.load_history()
        return tab
    
    def apply_styles(self):
        """Применяет стили к приложению."""
        self.setStyleSheet("""
            QMainWindow {
                background: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                padding: 6px 12px;
                border-radius: 4px;
                background: #e0e0e0;
                border: 1px solid #ccc;
            }
            QPushButton:hover {
                background: #d0d0d0;
            }
            QPushButton:pressed {
                background: #c0c0c0;
            }
            QComboBox, QSpinBox {
                padding: 4px;
                border-radius: 3px;
                border: 1px solid #ccc;
                background: white;
            }
            QTextEdit {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
    
    # ========================================================================
    # МЕТОДЫ ТРАНСКРИПЦИИ
    # ========================================================================
    
    def select_audio_file(self):
        """Выбор аудиофайла."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите аудиофайл",
            "",
            "Аудио файлы (*.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*.*)"
        )
        if file_path:
            self.current_audio_path = file_path
            self.file_label.setText(f"📁 {os.path.basename(file_path)}")
            self.file_label.setToolTip(file_path)
            self.btn_transcribe.setEnabled(True)
    
    def start_transcription(self):
        """Запуск транскрипции."""
        if not self.current_audio_path:
            QMessageBox.warning(self, "Ошибка", "Выберите аудиофайл")
            return
        
        self.btn_transcribe.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Начинаем...")
        self.result_text.clear()
        
        model = self.whisper_model.currentText()
        device = self.device_combo.currentText()
        
        self.transcription_thread = TranscriptionThread(
            self.current_audio_path,
            model,
            device
        )
        self.transcription_thread.progress.connect(self.update_transcription_progress)
        self.transcription_thread.finished.connect(self.transcription_finished)
        self.transcription_thread.error.connect(self.transcription_error)
        self.transcription_thread.start()
    
    def update_transcription_progress(self, value, message):
        """Обновление прогресса транскрипции."""
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)
        self.status_bar.showMessage(message)
    
    def transcription_finished(self, text):
        """Завершение транскрипции."""
        self.result_text.setText(text)
        self.current_text = text
        self.btn_transcribe.setEnabled(True)
        self.btn_process.setEnabled(True)
        self.progress_label.setText("✅ Готово!")
        self.status_bar.showMessage("Транскрипция завершена")
        
        # Автосохранение
        if self.auto_save.isChecked():
            self.save_transcript(text)
    
    def transcription_error(self, error):
        """Ошибка транскрипции."""
        QMessageBox.critical(self, "Ошибка", f"Ошибка транскрипции:\n{error}")
        self.btn_transcribe.setEnabled(True)
        self.progress_label.setText("❌ Ошибка")
    
    def process_transcribed_text(self):
        """Обработка транскрибированного текста."""
        text = self.result_text.toPlainText()
        if not text:
            QMessageBox.warning(self, "Ошибка", "Нет текста для обработки")
            return
        
        # Переключаемся на вкладку обработки
        self.tabs.setCurrentIndex(1)
        self.input_text.setText(text)
        self.start_processing()
    
    def save_transcript(self, text):
        """Сохраняет транскрипцию в файл."""
        try:
            os.makedirs(self.save_path.text(), exist_ok=True)
            filename = f"transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(self.save_path.text(), filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)
            self.add_to_history(f"Транскрипция", filename)
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
    
    # ========================================================================
    # МЕТОДЫ ОБРАБОТКИ
    # ========================================================================
    
    def load_text_file(self):
        """Загрузка текстового файла."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите текстовый файл",
            "",
            "Текстовые файлы (*.txt);;Все файлы (*.*)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                self.input_text.setText(text)
                self.status_bar.showMessage(f"Загружен файл: {os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")
    
    def on_mode_changed(self, index):
        """Изменение режима обработки."""
        is_llm = index >= 3  # Индексы 0-2: Simple, 3+: LLM
        self.llm_model.setEnabled(is_llm)
    
    def start_processing(self):
        """Запуск обработки текста."""
        text = self.input_text.toPlainText()
        if not text:
            QMessageBox.warning(self, "Ошибка", "Введите текст для обработки")
            return
        
        self.btn_process_text.setEnabled(False)
        self.process_progress.setValue(0)
        self.process_label.setText("Начинаем...")
        self.output_text.clear()
        
        mode_index = self.process_mode.currentIndex()
        mode_map = {
            0: "clean",
            1: "structure",
            2: "clean",
            3: "structure",
            4: "summary",
            5: "formatted",
            6: "detailed"
        }
        mode = mode_map.get(mode_index, "detailed")
        model = self.llm_model.currentText()
        
        self.processing_thread = ProcessingThread(text, mode, model)
        self.processing_thread.progress.connect(self.update_processing_progress)
        self.processing_thread.finished.connect(self.processing_finished)
        self.processing_thread.error.connect(self.processing_error)
        self.processing_thread.start()
    
    def update_processing_progress(self, value, message):
        """Обновление прогресса обработки."""
        self.process_progress.setValue(value)
        self.process_label.setText(message)
        self.status_bar.showMessage(message)
    
    def processing_finished(self, text):
        """Завершение обработки."""
        self.output_text.setText(text)
        self.btn_process_text.setEnabled(True)
        self.process_label.setText("✅ Готово!")
        self.status_bar.showMessage("Обработка завершена")
        
        # Автосохранение
        if self.auto_save.isChecked():
            self.save_processed(text)
    
    def processing_error(self, error):
        """Ошибка обработки."""
        QMessageBox.critical(self, "Ошибка", f"Ошибка обработки:\n{error}")
        self.btn_process_text.setEnabled(True)
        self.process_label.setText("❌ Ошибка")
    
    def save_processed(self, text):
        """Сохраняет обработанный текст."""
        try:
            os.makedirs(self.save_path.text(), exist_ok=True)
            mode = self.process_mode.currentText().replace(" ", "_")
            filename = f"processed_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(self.save_path.text(), filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)
            self.add_to_history(f"Обработка ({mode})", filename)
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
    
    # ========================================================================
    # ОБЩИЕ МЕТОДЫ
    # ========================================================================
    
    def copy_result(self):
        """Копирует результат транскрипции."""
        text = self.result_text.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_bar.showMessage("Скопировано в буфер обмена")
    
    def copy_output(self):
        """Копирует результат обработки."""
        text = self.output_text.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_bar.showMessage("Скопировано в буфер обмена")
    
    def save_result(self):
        """Сохраняет результат транскрипции."""
        text = self.result_text.toPlainText()
        if text:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить результат",
                self.save_path.text(),
                "Текстовые файлы (*.txt)"
            )
            if file_path:
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                    self.status_bar.showMessage(f"Сохранено: {os.path.basename(file_path)}")
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
    
    def save_output(self):
        """Сохраняет результат обработки."""
        text = self.output_text.toPlainText()
        if text:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить результат",
                self.save_path.text(),
                "Текстовые файлы (*.txt)"
            )
            if file_path:
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                    self.status_bar.showMessage(f"Сохранено: {os.path.basename(file_path)}")
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
    
    def change_save_path(self):
        """Изменяет папку сохранения."""
        path = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения",
            self.save_path.text()
        )
        if path:
            self.save_path.setText(path)
            self.settings.setValue("save_path", path)
    
    def check_ollama(self):
        """Проверяет доступность Ollama."""
        self.ollama_status.setText("🔄 Проверка...")
        
        def check():
            try:
                import requests
                response = requests.get("http://localhost:11434/api/tags", timeout=3)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    status = f"✅ Ollama работает (моделей: {len(model_names)})"
                    self.ollama_status.setText(status)
                    self.ollama_status.setStyleSheet("color: #4CAF50;")
                else:
                    self.ollama_status.setText("❌ Ollama не отвечает")
                    self.ollama_status.setStyleSheet("color: #f44336;")
            except:
                self.ollama_status.setText("❌ Ollama не запущен")
                self.ollama_status.setStyleSheet("color: #f44336;")
        
        threading.Thread(target=check, daemon=True).start()
    
    def load_settings(self):
        """Загружает настройки."""
        save_path = self.settings.value("save_path", os.path.expanduser("~/Documents/Speakly"))
        self.save_path.setText(save_path)
        
        whisper_model = self.settings.value("whisper_model", "small")
        index = self.whisper_model.findText(whisper_model)
        if index >= 0:
            self.whisper_model.setCurrentIndex(index)
        
        device = self.settings.value("device", "auto")
        index = self.device_combo.findText(device)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
    
    def save_settings(self):
        """Сохраняет настройки."""
        self.settings.setValue("save_path", self.save_path.text())
        self.settings.setValue("whisper_model", self.whisper_model.currentText())
        self.settings.setValue("device", self.device_combo.currentText())
    
    def add_to_history(self, action, filename):
        """Добавляет запись в историю."""
        item = QListWidgetItem(f"{action} - {filename}")
        item.setData(Qt.UserRole, filename)
        self.history_list.insertItem(0, item)
        
        # Сохраняем историю в файл
        try:
            history_file = os.path.join(self.save_path.text(), "history.txt")
            with open(history_file, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()}: {action} - {filename}\n")
        except:
            pass
    
    def load_history(self):
        """Загружает историю."""
        try:
            history_file = os.path.join(self.save_path.text(), "history.txt")
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                for line in reversed(lines[-100:]):  # Последние 100 записей
                    item = QListWidgetItem(line.strip())
                    self.history_list.addItem(item)
        except:
            pass
    
    def load_history_item(self, item):
        """Загружает элемент истории."""
        # Пытаемся найти файл
        filename = item.data(Qt.UserRole)
        if filename:
            filepath = os.path.join(self.save_path.text(), filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text = f.read()
                    self.result_text.setText(text)
                    self.tabs.setCurrentIndex(0)
                except:
                    pass
    
    def clear_history(self):
        """Очищает историю."""
        self.history_list.clear()
        try:
            history_file = os.path.join(self.save_path.text(), "history.txt")
            if os.path.exists(history_file):
                os.remove(history_file)
        except:
            pass
    
    def closeEvent(self, event):
        """Событие закрытия окна."""
        self.save_settings()
        event.accept()


# ============================================================================
# ЗАПУСК
# ============================================================================

def run_gui():
    """Запускает графический интерфейс."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Устанавливаем иконку приложения
    try:
        app.setWindowIcon(QIcon())
    except:
        pass
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    run_gui()