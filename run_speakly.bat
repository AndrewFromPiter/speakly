@echo off
chcp 65001 >nul
title Speakly GUI

echo ============================================================
echo  Запуск Speakly GUI
echo ============================================================

:: Активируем виртуальное окружение
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось активировать виртуальное окружение.
        pause
        exit /b %errorlevel%
    )
) else (
    echo [ОШИБКА] Виртуальное окружение не найдено. Создайте его: python -m venv .venv
    pause
    exit /b 1
)

:: Проверяем наличие Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден. Установите Python и повторите.
    pause
    exit /b 1
)

:: Проверяем установку основных зависимостей
echo Проверка зависимостей...
python -c "import faster_whisper, PyQt5, requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ПРЕДУПРЕЖДЕНИЕ] Некоторые зависимости не установлены.
    echo Установите их командой: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: Запускаем GUI
echo Запуск Speakly GUI...
python src\speakly_gui.py

:: Если программа завершилась с ошибкой, покажем сообщение
if %errorlevel% neq 0 (
    echo.
    echo [ОШИБКА] Программа завершилась с кодом %errorlevel%.
    echo Проверьте логи в консоли.
)

pause