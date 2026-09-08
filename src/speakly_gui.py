#!/usr/bin/env python3
"""
Speakly - полная версия с транскрипцией и обработкой через Ollama
"""

import sys
import os
import re
import json
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFileDialog, QProgressBar,
    QMessageBox, QTabWidget, QGroupBox, QComboBox, QCheckBox,
    QSpinBox, QStatusBar, QPlainTextEdit, QSplitter
)
from PyQt5.QtCore import Qt, QProcess, pyqtSignal, QThread, QSettings
from PyQt5.QtGui import QFont, QIcon


# ============================================================================
# Класс для запуска транскрипции в отдельном процессе
# ============================================================================

class TranscriptionProcess(QProcess):
    line_received = pyqtSignal(str)
    process_finished = pyqtSignal(str)  # переименовано, чтобы не конфликтовать с QProcess.finished
    error = pyqtSignal(str)
    
    def __init__(self, audio_path, model_name="tiny"):
        super().__init__()
        self.audio_path = audio_path
        self.model_name = model_name
        self.output_lines = []
        self.result_lines = []
        self.in_result = False
        
        # Читаем stdout и stderr отдельно
        self.setProcessChannelMode(QProcess.SeparateChannels)
        self.readyReadStandardOutput.connect(self.on_ready_read)
        self.readyReadStandardError.connect(self.on_error_read)
        # Подключаем оригинальный сигнал finished от QProcess
        self.finished.connect(self.on_finished)
    
    def start_transcription(self):
        # Определяем путь к воркеру
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(current_dir) == 'src':
            project_root = os.path.dirname(current_dir)
        else:
            project_root = current_dir
        worker_path = os.path.join(project_root, 'src', 'transcribe_worker.py')
        if not os.path.exists(worker_path):
            worker_path = os.path.join(project_root, 'transcribe_worker.py')
        if not os.path.exists(worker_path):
            self.error.emit(f"Не найден transcribe_worker.py по пути: {worker_path}")
            return
        
        args = [
            sys.executable,
            worker_path,
            self.audio_path,
            '--model', self.model_name
        ]
        self.line_received.emit(f"▶️ Запуск: {' '.join(args)}")
        self.start(args[0], args[1:])
        if not self.waitForStarted(3000):
            self.error.emit("Не удалось запустить процесс")
    
    def on_ready_read(self):
        data = self.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        for line in data.splitlines():
            if not line.strip():
                continue
            self.output_lines.append(line)
            if line == '===RESULT_START===':
                self.in_result = True
                self.result_lines = []
                continue
            elif line == '===RESULT_END===':
                self.in_result = False
                continue
            if self.in_result:
                self.result_lines.append(line)
            else:
                self.line_received.emit(line)
    
    def on_error_read(self):
        data = self.readAllStandardError().data().decode('utf-8', errors='ignore')
        for line in data.splitlines():
            if line.strip():
                self.line_received.emit(f"⚠️ {line}")
    
    def on_finished(self, exit_code, exit_status):
        if exit_code == 0:
            result_text = '\n'.join(self.result_lines).strip()
            self.process_finished.emit(result_text)
        else:
            error_text = '\n'.join(self.output_lines[-30:])
            self.error.emit(f"Процесс завершен с кодом {exit_code}\n{error_text}")


# ============================================================================
# Класс для обработки текста через Ollama (в отдельном потоке)
# ============================================================================

class OllamaWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, text, model, mode):
        super().__init__()
        self.text = text
        self.model = model
        self.mode = mode
    
    def run(self):
        try:
            import requests
            prompts = {
                "clean": "Очисти текст от ошибок, повторов и слов-паразитов. Сохрани смысл.",
                "structure": "Структурируй текст: разбей на разделы с заголовками, используй списки.",
                "summary": "Сделай краткий конспект текста, выдели главное.",
                "formatted": "Отформатируй текст: разбей на абзацы, исправь пунктуацию.",
                "detailed": "Сделай подробный аккуратный конспект с терминами и пояснениями."
            }
            instruction = prompts.get(self.mode, prompts["detailed"])
            prompt = f"{instruction}\n\nТекст:\n{self.text}"
            
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_ctx": 8192}
                },
                timeout=600
            )
            if response.status_code == 200:
                result = response.json().get("response", "")
                self.finished.emit(result)
            else:
                self.error.emit(f"Ошибка Ollama: {response.status_code}")
        except Exception as e:
            self.error.emit(str(e))


# ============================================================================
# Главное окно
# ============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Speakly", "Settings")
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        self.setWindowTitle("🎙️ Speakly — Транскрипция + Обработка")
        self.setGeometry(50, 50, 1100, 800)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        self.transcription_tab = self.create_transcription_tab()
        self.tabs.addTab(self.transcription_tab, "🎤 Транскрипция")
        
        self.processing_tab = self.create_processing_tab()
        self.tabs.addTab(self.processing_tab, "📝 Обработка (Ollama)")
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готов")
        
        self.setStyleSheet("""
            QMainWindow { background: #f5f5f5; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 5px; margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QPushButton { padding: 6px 12px; border-radius: 4px; background: #e0e0e0; border: 1px solid #ccc; }
            QPushButton:hover { background: #d0d0d0; }
            QPushButton:disabled { background: #cccccc; color: #666; }
            QTextEdit, QPlainTextEdit { border: 1px solid #ccc; border-radius: 4px; padding: 5px; font-family: Consolas; }
            QProgressBar { border: 1px solid #ccc; border-radius: 3px; text-align: center; }
            QProgressBar::chunk { background-color: #4CAF50; border-radius: 3px; }
            QTabWidget::pane { border: 1px solid #ccc; border-radius: 4px; background: white; }
            QTabBar::tab { padding: 8px 16px; }
            QTabBar::tab:selected { background: #4CAF50; color: white; }
        """)
    
    # ========================================================================
    # Вкладка транскрипции
    # ========================================================================
    
    def create_transcription_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        settings_group = QGroupBox("⚙️ Настройки")
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.addWidget(QLabel("Модель Whisper:"))
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(["tiny", "base", "small", "medium"])
        self.whisper_model.setCurrentText(self.settings.value("whisper_model", "tiny"))
        settings_layout.addWidget(self.whisper_model)
        settings_layout.addStretch()
        layout.addWidget(settings_group)
        
        file_group = QGroupBox("📁 Аудиофайл")
        file_layout = QHBoxLayout(file_group)
        self.file_label = QLabel("Файл не выбран")
        self.file_label.setStyleSheet("padding: 5px; background: #f0f0f0; border-radius: 4px;")
        file_layout.addWidget(self.file_label, 1)
        self.btn_select = QPushButton("📂 Выбрать")
        self.btn_select.clicked.connect(self.select_audio_file)
        file_layout.addWidget(self.btn_select)
        layout.addWidget(file_group)
        
        progress_group = QGroupBox("📊 Прогресс")
        progress_layout = QVBoxLayout(progress_group)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        progress_layout.addWidget(self.progress)
        self.status_label = QLabel("Готов")
        self.status_label.setStyleSheet("color: #555;")
        progress_layout.addWidget(self.status_label)
        layout.addWidget(progress_group)
        
        self.btn_start = QPushButton("🚀 Начать транскрипцию")
        self.btn_start.clicked.connect(self.start_transcription)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: #4CAF50; color: white; font-size: 14px;
                font-weight: bold; padding: 12px; border-radius: 6px;
            }
            QPushButton:hover { background: #45a049; }
            QPushButton:disabled { background: #cccccc; color: #666; }
        """)
        layout.addWidget(self.btn_start)
        
        splitter = QSplitter(Qt.Vertical)
        
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(QLabel("📊 Лог транскрипции:"))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        splitter.addWidget(log_widget)
        
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(QLabel("📝 Результат транскрипции:"))
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)
        splitter.addWidget(result_widget)
        
        layout.addWidget(splitter)
        
        action_layout = QHBoxLayout()
        self.btn_copy = QPushButton("📋 Копировать")
        self.btn_copy.clicked.connect(self.copy_transcription)
        self.btn_copy.setEnabled(False)
        action_layout.addWidget(self.btn_copy)
        
        self.btn_save = QPushButton("💾 Сохранить")
        self.btn_save.clicked.connect(self.save_transcription)
        self.btn_save.setEnabled(False)
        action_layout.addWidget(self.btn_save)
        
        self.btn_send_to_ollama = QPushButton("🔄 Отправить в обработку")
        self.btn_send_to_ollama.clicked.connect(self.send_to_ollama)
        self.btn_send_to_ollama.setEnabled(False)
        action_layout.addWidget(self.btn_send_to_ollama)
        
        action_layout.addStretch()
        layout.addLayout(action_layout)
        
        self.audio_path = None
        self.process = None
        self.transcription_result = ""
        
        return tab
    
    def select_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите аудиофайл", "",
            "Аудио файлы (*.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*.*)"
        )
        if file_path:
            self.audio_path = file_path
            self.file_label.setText(f"📁 {os.path.basename(file_path)}")
            self.btn_start.setEnabled(True)
            self.log_text.clear()
            self.result_text.clear()
            self.transcription_result = ""
            self.btn_copy.setEnabled(False)
            self.btn_save.setEnabled(False)
            self.btn_send_to_ollama.setEnabled(False)
    
    def start_transcription(self):
        if not self.audio_path:
            return
        
        self.btn_start.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.btn_send_to_ollama.setEnabled(False)
        self.result_text.clear()
        self.log_text.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status_label.setText("Запуск...")
        self.status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
        self.transcription_result = ""
        
        model = self.whisper_model.currentText()
        self.settings.setValue("whisper_model", model)
        
        self.process = TranscriptionProcess(self.audio_path, model)
        self.process.line_received.connect(self.on_transcription_line)
        self.process.process_finished.connect(self.on_transcription_finished)  # изменено
        self.process.error.connect(self.on_transcription_error)
        self.process.start_transcription()
        
        self.status_bar.showMessage("Транскрипция запущена...")
    
    def on_transcription_line(self, line):
        self.log_text.appendPlainText(line)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
        
        if "Разбито на" in line:
            match = re.search(r'Разбито на (\d+) частей', line)
            if match:
                total = int(match.group(1))
                self.progress.setRange(0, total)
                self.progress.setValue(0)
                self.status_label.setText(f"Разбито на {total} частей")
        elif "Транскрипция части" in line:
            match = re.search(r'Транскрипция части (\d+)/(\d+)', line)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                self.progress.setRange(0, total)
                self.progress.setValue(current)
                self.status_label.setText(f"Транскрипция: часть {current}/{total}")
        elif "Часть" in line and "готова" in line:
            self.status_label.setText(line[:80])
        elif "ТРАНСКРИПЦИЯ ЗАВЕРШЕНА" in line:
            self.status_label.setText("Завершается...")
        elif "Аудиофайл не требует разбиения" in line:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.status_label.setText("Транскрипция одного файла...")
        elif "Готово" in line and "ТРАНСКРИПЦИЯ ЗАВЕРШЕНА" in line:
            self.status_label.setText("Завершается...")
        
        QApplication.processEvents()
    
    def on_transcription_finished(self, result):
        print("✅ Транскрипция завершена")
        self.transcription_result = result
        self.result_text.setText(result)
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.status_label.setText("✅ Готово!")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.btn_start.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.btn_send_to_ollama.setEnabled(True)
        self.status_bar.showMessage("Транскрипция завершена")
        
        if result.strip():
            QMessageBox.information(
                self, "Готово",
                f"Транскрипция завершена!\nДлина текста: {len(result)} символов"
            )
        else:
            QMessageBox.warning(self, "Предупреждение", "Транскрипция вернула пустой результат")
    
    def on_transcription_error(self, error):
        self.result_text.setText(f"❌ Ошибка транскрипции:\n\n{error}")
        self.btn_start.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText("❌ Ошибка")
        self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        self.status_bar.showMessage("Ошибка транскрипции")
        QMessageBox.critical(self, "Ошибка", f"Ошибка транскрипции:\n\n{error[:500]}")
    
    def copy_transcription(self):
        text = self.result_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_label.setText("✅ Скопировано")
    
    def save_transcription(self):
        text = self.result_text.toPlainText()
        if not text:
            return
        filename = f"transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить результат", filename, "Текстовые файлы (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                self.status_label.setText("✅ Сохранено")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def send_to_ollama(self):
        text = self.result_text.toPlainText()
        if not text:
            return
        self.tabs.setCurrentIndex(1)
        self.input_text.setText(text)
        self.status_bar.showMessage("Текст передан в обработку. Выберите режим и нажмите 'Обработать'.")
    
    # ========================================================================
    # Вкладка обработки текста через Ollama
    # ========================================================================
    
    def create_processing_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        settings_group = QGroupBox("⚙️ Настройки Ollama")
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.addWidget(QLabel("Модель:"))
        self.ollama_model = QComboBox()
        self.ollama_model.addItems(["mistral", "gemma2:9b", "llama3.2", "qwen2.5-coder:7b"])
        self.ollama_model.setCurrentText(self.settings.value("ollama_model", "mistral"))
        settings_layout.addWidget(self.ollama_model)
        
        settings_layout.addWidget(QLabel("Режим:"))
        self.ollama_mode = QComboBox()
        self.ollama_mode.addItems([
            "Очистка", "Структурирование", "Краткий конспект",
            "Форматирование", "Подробный конспект"
        ])
        self.ollama_mode.setCurrentIndex(4)
        settings_layout.addWidget(self.ollama_mode)
        
        settings_layout.addStretch()
        layout.addWidget(settings_group)
        
        input_group = QGroupBox("📝 Входной текст")
        input_layout = QVBoxLayout(input_group)
        btn_load_text = QPushButton("📂 Загрузить текстовый файл")
        btn_load_text.clicked.connect(self.load_text_file)
        input_layout.addWidget(btn_load_text)
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("Вставьте текст для обработки...")
        input_layout.addWidget(self.input_text)
        layout.addWidget(input_group)
        
        self.btn_process = QPushButton("🧠 Обработать через Ollama")
        self.btn_process.clicked.connect(self.start_ollama_processing)
        self.btn_process.setStyleSheet("""
            QPushButton {
                background: #FF9800; color: white; font-size: 14px;
                font-weight: bold; padding: 12px; border-radius: 6px;
            }
            QPushButton:hover { background: #F57C00; }
            QPushButton:disabled { background: #cccccc; color: #666; }
        """)
        layout.addWidget(self.btn_process)
        
        self.ollama_progress = QProgressBar()
        self.ollama_progress.setVisible(False)
        layout.addWidget(self.ollama_progress)
        self.ollama_status = QLabel("Готов")
        self.ollama_status.setStyleSheet("color: #555;")
        layout.addWidget(self.ollama_status)
        
        result_group = QGroupBox("📝 Результат обработки")
        result_layout = QVBoxLayout(result_group)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        result_layout.addWidget(self.output_text)
        layout.addWidget(result_group)
        
        action_layout = QHBoxLayout()
        btn_copy_out = QPushButton("📋 Копировать")
        btn_copy_out.clicked.connect(lambda: self.copy_text(self.output_text))
        action_layout.addWidget(btn_copy_out)
        btn_save_out = QPushButton("💾 Сохранить")
        btn_save_out.clicked.connect(self.save_processed)
        action_layout.addWidget(btn_save_out)
        action_layout.addStretch()
        layout.addLayout(action_layout)
        
        self.ollama_thread = None
        return tab
    
    def load_text_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите текстовый файл", "", "Текстовые файлы (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.input_text.setText(f.read())
                self.status_bar.showMessage(f"Загружен {os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def start_ollama_processing(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Ошибка", "Введите текст для обработки")
            return
        
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=3)
            if response.status_code != 200:
                QMessageBox.critical(self, "Ошибка", "Ollama не отвечает. Запустите: ollama serve")
                return
        except:
            QMessageBox.critical(self, "Ошибка", "Ollama не запущен")
            return
        
        model = self.ollama_model.currentText()
        mode_map = {
            "Очистка": "clean",
            "Структурирование": "structure",
            "Краткий конспект": "summary",
            "Форматирование": "formatted",
            "Подробный конспект": "detailed"
        }
        mode = mode_map[self.ollama_mode.currentText()]
        self.settings.setValue("ollama_model", model)
        
        self.btn_process.setEnabled(False)
        self.ollama_progress.setVisible(True)
        self.ollama_progress.setRange(0, 0)
        self.ollama_status.setText("Обработка...")
        self.ollama_status.setStyleSheet("color: #FF9800; font-weight: bold;")
        self.output_text.clear()
        
        self.ollama_thread = OllamaWorker(text, model, mode)
        self.ollama_thread.progress.connect(lambda msg: self.ollama_status.setText(msg))
        self.ollama_thread.finished.connect(self.on_ollama_finished)
        self.ollama_thread.error.connect(self.on_ollama_error)
        self.ollama_thread.start()
        
        self.status_bar.showMessage("Обработка через Ollama запущена...")
    
    def on_ollama_finished(self, result):
        self.output_text.setText(result)
        self.btn_process.setEnabled(True)
        self.ollama_progress.setVisible(False)
        self.ollama_status.setText("✅ Готово")
        self.ollama_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.status_bar.showMessage("Обработка завершена")
        QMessageBox.information(
            self, "Готово",
            f"Обработка завершена!\nДлина текста: {len(result)} символов"
        )
    
    def on_ollama_error(self, error):
        self.output_text.setText(f"❌ Ошибка обработки:\n\n{error}")
        self.btn_process.setEnabled(True)
        self.ollama_progress.setVisible(False)
        self.ollama_status.setText("❌ Ошибка")
        self.ollama_status.setStyleSheet("color: #f44336; font-weight: bold;")
        self.status_bar.showMessage("Ошибка обработки")
        QMessageBox.critical(self, "Ошибка", f"Ошибка обработки:\n\n{error}")
    
    def copy_text(self, text_edit):
        text = text_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_bar.showMessage("Скопировано")
    
    def save_processed(self):
        text = self.output_text.toPlainText()
        if not text:
            return
        filename = f"processed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить результат", filename, "Текстовые файлы (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                self.status_bar.showMessage("Сохранено")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def load_settings(self):
        pass


# ============================================================================
# Запуск
# ============================================================================

def main():
    print("=" * 60)
    print("Запуск Speakly Full")
    print("=" * 60)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()