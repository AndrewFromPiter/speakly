@echo off
chcp 65001 >nul
title Speakly - Полная настройка

echo ============================================================
echo  Speakly - Установка и настройка окружения (полная)
echo ============================================================
echo.

set PROJECT_DIR=%CD%
set REPO_URL=https://github.com/AndrewFromPiter/speakly   :: ЗАМЕНИ НА СВОЙ РЕПО!

:: ============================================================
:: 1. Проверка и установка winget (уже есть в Win11)
:: ============================================================
echo [1/6] Проверка winget...
winget --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ПРЕДУПРЕЖДЕНИЕ] winget не найден. Установите вручную.
    echo Для Windows 10/11 он обычно уже установлен.
    pause
    exit /b 1
)
echo winget доступен.
echo.

:: ============================================================
:: 2. Проверка и установка Python
:: ============================================================
echo [2/6] Проверка Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python не найден. Установка через winget...
    winget install Python.Python.3.11 --silent --accept-package-agreements
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось установить Python.
        echo Установите вручную с https://www.python.org/downloads/
        pause
        exit /b 1
    )
    :: Обновляем переменные PATH для текущей сессии
    for /f "tokens=*" %%i in ('where python') do set PYTHON_PATH=%%i
    echo Python установлен.
) else (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
    echo Найдена версия: %PYTHON_VERSION%
)
echo.

:: ============================================================
:: 3. Проверка и установка Git
:: ============================================================
echo [3/6] Проверка Git...
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Git не найден. Установка через winget...
    winget install Git.Git --silent --accept-package-agreements
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось установить Git.
        echo Установите вручную с https://git-scm.com/download/win
        pause
        exit /b 1
    )
    :: Добавляем Git в PATH для текущей сессии
    set PATH=%PATH%;%ProgramFiles%\Git\cmd
    echo Git установлен.
) else (
    git --version
)
echo.

:: ============================================================
:: 4. Клонирование репозитория (если папка пуста)
:: ============================================================
echo [4/6] Проверка наличия исходников...
if exist "%PROJECT_DIR%\src" (
    echo Проект уже существует. Пропускаем клонирование.
) else (
    echo Папка src не найдена. Клонирование репозитория...
    if "%REPO_URL%"=="https://github.com/your-username/speakly.git" (
        echo [ВНИМАНИЕ] URL репозитория не изменён!
        echo Отредактируйте setup.bat и укажите свой REPO_URL.
        pause
        exit /b 1
    )
    git clone %REPO_URL% "%PROJECT_DIR%"
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось клонировать репозиторий.
        echo Проверьте URL и доступ к интернету.
        pause
        exit /b 1
    )
    echo Репозиторий успешно клонирован.
)
echo.

:: ============================================================
:: 5. Проверка и установка FFmpeg
:: ============================================================
echo [5/6] Проверка FFmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo FFmpeg не найден. Установка через winget...
    winget install FFmpeg --silent --accept-package-agreements
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось установить FFmpeg.
        echo Установите вручную с https://ffmpeg.org/download.html
        echo и добавьте папку bin в PATH.
        pause
        exit /b 1
    )
    :: Добавляем в PATH (предполагаем стандартный путь)
    set PATH=%PATH%;%ProgramFiles%\FFmpeg\bin
    echo FFmpeg установлен.
) else (
    echo FFmpeg найден.
)
echo.

:: ============================================================
:: 6. Создание виртуального окружения и установка зависимостей
:: ============================================================
echo [6/6] Настройка виртуального окружения...
if exist ".venv" (
    echo Виртуальное окружение уже существует.
) else (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)

echo Активация виртуального окружения...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ОШИБКА] Не удалось активировать окружение.
    pause
    exit /b 1
)

echo Обновление pip...
python -m pip install --upgrade pip

if exist "requirements.txt" (
    echo Установка зависимостей...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось установить зависимости.
        echo Попробуйте установить вручную: pip install -r requirements.txt
        pause
        exit /b 1
    )
) else (
    echo [ПРЕДУПРЕЖДЕНИЕ] Файл requirements.txt не найден.
    pause
    exit /b 1
)

echo.

:: ============================================================
:: 7. Завершение
:: ============================================================
echo ============================================================
echo  Готово!
echo ============================================================
echo.
echo Все компоненты установлены и настроены.
echo Для запуска используйте run_speakly.bat (если он есть)
echo или вручную: .venv\Scripts\python src\speakly_gui.py
echo.
pause