#!/usr/bin/env python3
"""
Speakly Pro - транскрипция очереди файлов + обработка Ollama
"""

import sys
import os
import re
import subprocess
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFileDialog, QProgressBar,
    QMessageBox, QTabWidget, QGroupBox, QComboBox, QSpinBox,
    QStatusBar, QPlainTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QDialog
)
from PyQt5.QtCore import Qt, QProcess, pyqtSignal, QThread, QSettings, QTimer, QObject


# ============================================================================
# Класс для запуска транскрипции в отдельном процессе (один файл)
# ============================================================================

class TranscriptionProcess(QProcess):
    line_received = pyqtSignal(str)
    process_finished = pyqtSignal(str, str)  # (file_path, result_text)
    error = pyqtSignal(str, str)  # (file_path, error_text)
    progress_updated = pyqtSignal(str, int, str)  # (file_path, progress_percent, status_text)
    
    def __init__(self, audio_path, model_name="tiny"):
        super().__init__()
        self.audio_path = audio_path
        self.model_name = model_name
        self.output_lines = []
        self.result_lines = []
        self.in_result = False
        self.progress = 0
        self.status = "Запуск..."
        
        self.setProcessChannelMode(QProcess.SeparateChannels)
        self.readyReadStandardOutput.connect(self.on_ready_read)
        self.readyReadStandardError.connect(self.on_error_read)
        self.finished.connect(self.on_finished)
    
    def start_transcription(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(current_dir) == 'src':
            project_root = os.path.dirname(current_dir)
        else:
            project_root = current_dir
        worker_path = os.path.join(project_root, 'src', 'transcribe_worker.py')
        if not os.path.exists(worker_path):
            worker_path = os.path.join(project_root, 'transcribe_worker.py')
        if not os.path.exists(worker_path):
            self.error.emit(self.audio_path, f"Не найден transcribe_worker.py по пути: {worker_path}")
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
            self.error.emit(self.audio_path, "Не удалось запустить процесс")
    
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
                # Обновляем прогресс на основе строк
                if "Разбито на" in line:
                    match = re.search(r'Разбито на (\d+) частей', line)
                    if match:
                        total = int(match.group(1))
                        self.progress = 0
                        self.status = f"Разбито на {total} частей"
                        self.progress_updated.emit(self.audio_path, 0, self.status)
                elif "Транскрипция части" in line:
                    match = re.search(r'Транскрипция части (\d+)/(\d+)', line)
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))
                        self.progress = int(current / total * 100)
                        self.status = f"Часть {current}/{total}"
                        self.progress_updated.emit(self.audio_path, self.progress, self.status)
                elif "Часть" in line and "готова" in line:
                    self.status = line[:80]
                    self.progress_updated.emit(self.audio_path, self.progress, self.status)
                elif "ТРАНСКРИПЦИЯ ЗАВЕРШЕНА" in line:
                    self.status = "Завершается..."
                    self.progress_updated.emit(self.audio_path, 100, self.status)
    
    def on_error_read(self):
        data = self.readAllStandardError().data().decode('utf-8', errors='ignore')
        for line in data.splitlines():
            if line.strip():
                self.line_received.emit(f"⚠️ {line}")
    
    def on_finished(self, exit_code, exit_status):
        if exit_code == 0:
            result_text = '\n'.join(self.result_lines).strip()
            self.process_finished.emit(self.audio_path, result_text)
        else:
            error_text = '\n'.join(self.output_lines[-30:])
            self.error.emit(self.audio_path, f"Код {exit_code}\n{error_text}")


# ============================================================================
# Класс для управления очередью транскрипции
# ============================================================================

class TranscriptionQueueManager(QObject):
    progress_updated = pyqtSignal(str, int, str)  # file_path, progress, status
    file_finished = pyqtSignal(str, str)  # file_path, result
    file_error = pyqtSignal(str, str)  # file_path, error
    all_finished = pyqtSignal()
    
    def __init__(self, model_name="tiny", max_workers=2):
        super().__init__()
        self.model_name = model_name
        self.max_workers = max_workers
        self.queue = []  # список файлов (пути)
        self.active_processes = {}  # file_path -> TranscriptionProcess
        self.results = {}  # file_path -> result
        self.errors = {}  # file_path -> error
        self.running = False
        self.finished_count = 0
    
    def add_files(self, file_paths):
        for path in file_paths:
            if path not in self.queue and path not in self.active_processes:
                self.queue.append(path)
    
    def start(self):
        if self.running:
            return
        self.running = True
        self.finished_count = 0
        self.results = {}
        self.errors = {}
        self._start_next()
    
    def _start_next(self):
        while len(self.active_processes) < self.max_workers and self.queue:
            file_path = self.queue.pop(0)
            process = TranscriptionProcess(file_path, self.model_name)
            process.line_received.connect(lambda line, p=file_path: print(f"[{os.path.basename(p)}] {line}"))
            process.progress_updated.connect(self._on_progress)
            process.process_finished.connect(self._on_finished)
            process.error.connect(self._on_error)
            process.start_transcription()
            self.active_processes[file_path] = process
            self.progress_updated.emit(file_path, 0, "Запуск...")
    
    def _on_progress(self, file_path, progress, status):
        self.progress_updated.emit(file_path, progress, status)
    
    def _on_finished(self, file_path, result):
        self.results[file_path] = result
        self.file_finished.emit(file_path, result)
        del self.active_processes[file_path]
        self.finished_count += 1
        if self.queue or self.active_processes:
            self._start_next()
        else:
            self.running = False
            self.all_finished.emit()
    
    def _on_error(self, file_path, error):
        self.errors[file_path] = error
        self.file_error.emit(file_path, error)
        if file_path in self.active_processes:
            del self.active_processes[file_path]
        self.finished_count += 1
        if self.queue or self.active_processes:
            self._start_next()
        else:
            self.running = False
            self.all_finished.emit()
    
    def stop(self):
        self.running = False
        for process in self.active_processes.values():
            process.kill()
        self.active_processes.clear()
        self.queue.clear()


# ============================================================================
# Класс для обработки Ollama (в отдельном потоке)
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
        self.queue_manager = None
        self.ollama_thread = None
        self.init_ui()
        self.load_settings()
        self.check_ollama()
    
    def init_ui(self):
        self.setWindowTitle("🎙️ Speakly Pro — Очередь транскрипции + Ollama")
        self.setGeometry(50, 50, 1200, 800)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Вкладка транскрипции
        self.transcription_tab = self.create_transcription_tab()
        self.tabs.addTab(self.transcription_tab, "🎤 Транскрипция (очередь)")
        
        # Вкладка обработки Ollama
        self.processing_tab = self.create_processing_tab()
        self.tabs.addTab(self.processing_tab, "📝 Обработка (Ollama)")
        
        # Статус бар
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
            QListWidget::item { padding: 5px; }
        """)
    
    # ========================================================================
    # Вкладка транскрипции (очередь)
    # ========================================================================
    
    def create_transcription_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Верхняя панель настроек
        settings_group = QGroupBox("⚙️ Настройки")
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.addWidget(QLabel("Модель Whisper:"))
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(["tiny", "base", "small", "medium"])
        self.whisper_model.setCurrentText(self.settings.value("whisper_model", "tiny"))
        settings_layout.addWidget(self.whisper_model)
        
        settings_layout.addWidget(QLabel("Одновременно:"))
        self.max_workers = QSpinBox()
        self.max_workers.setRange(1, 5)
        self.max_workers.setValue(int(self.settings.value("max_workers", 2)))
        settings_layout.addWidget(self.max_workers)
        
        settings_layout.addStretch()
        layout.addWidget(settings_group)
        
        # Список файлов
        file_group = QGroupBox("📁 Файлы для транскрипции")
        file_layout = QVBoxLayout(file_group)
        
        btn_layout = QHBoxLayout()
        self.btn_add_files = QPushButton("➕ Добавить файлы")
        self.btn_add_files.clicked.connect(self.add_files)
        btn_layout.addWidget(self.btn_add_files)
        
        self.btn_remove_selected = QPushButton("🗑️ Удалить выбранные")
        self.btn_remove_selected.clicked.connect(self.remove_selected)
        btn_layout.addWidget(self.btn_remove_selected)
        
        self.btn_clear_all = QPushButton("🧹 Очистить все")
        self.btn_clear_all.clicked.connect(self.clear_all)
        btn_layout.addWidget(self.btn_clear_all)
        
        btn_layout.addStretch()
        file_layout.addLayout(btn_layout)
        
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        file_layout.addWidget(self.file_list)
        
        layout.addWidget(file_group)
        
        # Кнопка старта/остановки
        btn_start_stop_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 Начать транскрипцию")
        self.btn_start.clicked.connect(self.start_queue)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: #4CAF50; color: white; font-size: 14px;
                font-weight: bold; padding: 12px; border-radius: 6px;
            }
            QPushButton:hover { background: #45a049; }
            QPushButton:disabled { background: #cccccc; color: #666; }
        """)
        btn_start_stop_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("⏹️ Остановить")
        self.btn_stop.clicked.connect(self.stop_queue)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: #f44336; color: white; font-size: 14px;
                font-weight: bold; padding: 12px; border-radius: 6px;
            }
            QPushButton:hover { background: #d32f2f; }
            QPushButton:disabled { background: #cccccc; color: #666; }
        """)
        btn_start_stop_layout.addWidget(self.btn_stop)
        btn_start_stop_layout.addStretch()
        layout.addLayout(btn_start_stop_layout)
        
        # Глобальный прогресс и статус
        self.global_progress = QProgressBar()
        self.global_progress.setVisible(False)
        layout.addWidget(self.global_progress)
        
        self.global_status = QLabel("Готов")
        self.global_status.setStyleSheet("color: #555;")
        layout.addWidget(self.global_status)
        
        # Детальный лог (общий для всех файлов)
        log_group = QGroupBox("📊 Лог транскрипции")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)
        
        # Результаты (таблица с результатами по каждому файлу)
        result_group = QGroupBox("📝 Результаты")
        result_layout = QVBoxLayout(result_group)
        
        self.result_list = QListWidget()
        self.result_list.setWordWrap(True)
        self.result_list.itemDoubleClicked.connect(self.show_result)
        result_layout.addWidget(self.result_list)
        
        btn_result_layout = QHBoxLayout()
        btn_save_all = QPushButton("💾 Сохранить все результаты")
        btn_save_all.clicked.connect(self.save_all_results)
        btn_result_layout.addWidget(btn_save_all)
        
        btn_clear_results = QPushButton("🗑️ Очистить результаты")
        btn_clear_results.clicked.connect(lambda: self.result_list.clear())
        btn_result_layout.addWidget(btn_clear_results)
        
        btn_result_layout.addStretch()
        result_layout.addLayout(btn_result_layout)
        
        layout.addWidget(result_group)
        
        return tab
    
    def add_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите аудиофайлы", "",
            "Аудио файлы (*.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*.*)"
        )
        if file_paths:
            for path in file_paths:
                exists = False
                for i in range(self.file_list.count()):
                    item = self.file_list.item(i)
                    if item.data(Qt.UserRole) == path:
                        exists = True
                        break
                if not exists:
                    item = QListWidgetItem(f"📄 {os.path.basename(path)}")
                    item.setData(Qt.UserRole, path)
                    item.setData(Qt.UserRole + 1, "Ожидает")  # статус
                    self.file_list.addItem(item)
            self.update_ui()
    
    def remove_selected(self):
        for item in self.file_list.selectedItems():
            row = self.file_list.row(item)
            self.file_list.takeItem(row)
        self.update_ui()
    
    def clear_all(self):
        self.file_list.clear()
        self.update_ui()
    
    def update_ui(self):
        has_files = self.file_list.count() > 0
        running = self.queue_manager is not None and self.queue_manager.running
        self.btn_start.setEnabled(has_files and not running)
        self.btn_stop.setEnabled(running)
    
    def start_queue(self):
        if self.file_list.count() == 0:
            return
        
        # Собираем пути файлов
        file_paths = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = item.data(Qt.UserRole)
            file_paths.append(path)
            item.setData(Qt.UserRole + 1, "В очереди")
            item.setText(f"📄 {os.path.basename(path)} (В очереди)")
        
        # Создаем менеджер очереди
        model = self.whisper_model.currentText()
        self.settings.setValue("whisper_model", model)
        max_workers = self.max_workers.value()
        self.settings.setValue("max_workers", max_workers)
        
        self.queue_manager = TranscriptionQueueManager(model, max_workers)
        self.queue_manager.progress_updated.connect(self.on_file_progress)
        self.queue_manager.file_finished.connect(self.on_file_finished)
        self.queue_manager.file_error.connect(self.on_file_error)
        self.queue_manager.all_finished.connect(self.on_all_finished)
        
        self.queue_manager.add_files(file_paths)
        self.queue_manager.start()
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.global_progress.setVisible(True)
        self.global_progress.setRange(0, 0)
        self.global_status.setText("Обработка очереди...")
        self.global_status.setStyleSheet("color: #2196F3; font-weight: bold;")
        self.log_text.clear()
        self.result_list.clear()
        self.status_bar.showMessage("Транскрипция очереди запущена...")
        self.update_ui()
    
    def on_file_progress(self, file_path, progress, status):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == file_path:
                item.setText(f"📄 {os.path.basename(file_path)} ({progress}%) — {status}")
                item.setData(Qt.UserRole + 1, status)
                break
        self.log_text.appendPlainText(f"[{os.path.basename(file_path)}] {status}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
        QApplication.processEvents()
    
    def on_file_finished(self, file_path, result):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == file_path:
                item.setText(f"✅ {os.path.basename(file_path)} (Завершено)")
                item.setData(Qt.UserRole + 1, "Завершено")
                break
        item = QListWidgetItem(f"✅ {os.path.basename(file_path)} — {len(result)} символов")
        item.setData(Qt.UserRole, file_path)
        item.setData(Qt.UserRole + 2, result)  # результат
        self.result_list.addItem(item)
        self.log_text.appendPlainText(f"✅ Завершено: {os.path.basename(file_path)}")
        self.status_bar.showMessage(f"Завершено: {os.path.basename(file_path)}")
        self.update_ui()
    
    def on_file_error(self, file_path, error):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == file_path:
                item.setText(f"❌ {os.path.basename(file_path)} (Ошибка)")
                item.setData(Qt.UserRole + 1, "Ошибка")
                break
        self.log_text.appendPlainText(f"❌ Ошибка: {os.path.basename(file_path)}\n{error[:200]}")
        self.status_bar.showMessage(f"Ошибка: {os.path.basename(file_path)}")
        self.update_ui()
    
    def on_all_finished(self):
        self.global_progress.setVisible(False)
        self.global_progress.setRange(0, 100)
        self.global_status.setText("✅ Все файлы обработаны!")
        self.global_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_bar.showMessage("Очередь завершена")
        self.update_ui()
        QMessageBox.information(self, "Готово", "Все файлы транскрибированы!")
    
    def stop_queue(self):
        if self.queue_manager and self.queue_manager.running:
            self.queue_manager.stop()
            self.global_status.setText("⏹️ Остановлено пользователем")
            self.global_status.setStyleSheet("color: #f44336; font-weight: bold;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.status_bar.showMessage("Очередь остановлена")
            self.update_ui()
    
    def show_result(self, item):
        result = item.data(Qt.UserRole + 2)
        if not result:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Результат: {os.path.basename(item.data(Qt.UserRole))}")
        dialog.setGeometry(200, 200, 700, 500)
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(result)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        
        btn_layout = QHBoxLayout()
        btn_copy = QPushButton("📋 Копировать")
        btn_copy.clicked.connect(lambda: self._copy_text_from_edit(text_edit))
        btn_layout.addWidget(btn_copy)
        
        btn_save = QPushButton("💾 Сохранить как...")
        btn_save.clicked.connect(lambda: self._save_text_from_edit(text_edit, item.data(Qt.UserRole)))
        btn_layout.addWidget(btn_save)
        
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dialog.accept)
        btn_layout.addWidget(btn_close)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        dialog.exec_()

    def _copy_text_from_edit(self, text_edit):
        text = text_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_bar.showMessage("Скопировано в буфер обмена")

    def _save_text_from_edit(self, text_edit, original_path):
        text = text_edit.toPlainText()
        if not text:
            return
        base = os.path.splitext(os.path.basename(original_path))[0]
        filename = f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить результат", filename, "Текстовые файлы (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                self.status_bar.showMessage(f"Сохранено: {os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    def save_all_results(self):
        if self.result_list.count() == 0:
            QMessageBox.warning(self, "Нет результатов", "Нет завершенных транскрипций.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if not folder:
            return
        saved = 0
        for i in range(self.result_list.count()):
            item = self.result_list.item(i)
            file_path = item.data(Qt.UserRole)
            result = item.data(Qt.UserRole + 2)
            if result:
                base = os.path.splitext(os.path.basename(file_path))[0]
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{base}_{timestamp}.txt"
                full_path = os.path.join(folder, filename)
                try:
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(result)
                    saved += 1
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить {filename}: {e}")
        QMessageBox.information(self, "Сохранено", f"Сохранено {saved} файлов.")
    
    # ========================================================================
    # Вкладка Ollama
    # ========================================================================
    
    def create_processing_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        ollama_status_group = QGroupBox("🤖 Статус Ollama")
        status_layout = QHBoxLayout(ollama_status_group)
        self.ollama_status_label = QLabel("Проверка...")
        status_layout.addWidget(self.ollama_status_label)
        self.btn_ollama_start = QPushButton("▶️ Запустить Ollama")
        self.btn_ollama_start.clicked.connect(self.start_ollama)
        self.btn_ollama_start.setEnabled(False)
        status_layout.addWidget(self.btn_ollama_start)
        self.btn_ollama_check = QPushButton("🔄 Проверить")
        self.btn_ollama_check.clicked.connect(self.check_ollama)
        status_layout.addWidget(self.btn_ollama_check)
        status_layout.addStretch()
        layout.addWidget(ollama_status_group)
        
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
        
        return tab
    
    # ========================================================================
    # Методы для Ollama
    # ========================================================================
    
    def check_ollama(self):
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name") for m in models]
                self.ollama_status_label.setText(f"✅ Ollama работает (модели: {', '.join(model_names) or 'нет'})")
                self.ollama_status_label.setStyleSheet("color: #4CAF50;")
                self.btn_ollama_start.setEnabled(False)
                self.btn_process.setEnabled(True)
            else:
                self.ollama_status_label.setText("❌ Ollama не отвечает (код ошибки)")
                self.ollama_status_label.setStyleSheet("color: #f44336;")
                self.btn_ollama_start.setEnabled(True)
                self.btn_process.setEnabled(False)
        except Exception as e:
            self.ollama_status_label.setText("❌ Ollama не запущен")
            self.ollama_status_label.setStyleSheet("color: #f44336;")
            self.btn_ollama_start.setEnabled(True)
            self.btn_process.setEnabled(False)
    
    def start_ollama(self):
        self.btn_ollama_start.setEnabled(False)
        self.btn_ollama_start.setText("Запуск...")
        self.ollama_status_label.setText("⏳ Запуск Ollama...")
        
        def run_ollama():
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                import time
                time.sleep(2)
                self.check_ollama()
            except Exception as e:
                self.ollama_status_label.setText(f"❌ Ошибка запуска: {e}")
                self.ollama_status_label.setStyleSheet("color: #f44336;")
                self.btn_ollama_start.setEnabled(True)
                self.btn_ollama_start.setText("▶️ Запустить Ollama")
        
        thread = QThread()
        thread.run = run_ollama
        thread.start()
    
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
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code != 200:
                QMessageBox.critical(self, "Ошибка", "Ollama не отвечает. Запустите его через кнопку выше.")
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
    print("Запуск Speakly Pro")
    print("=" * 60)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    QTimer.singleShot(1000, window.check_ollama)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()