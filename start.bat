@echo off
chcp 65001 >nul
title TradeVerse
cd /d "%~dp0"

echo [1/3] Обновление из GitHub (AlmazIsDev/TradeVerse-Game)...
git pull origin main
if errorlevel 1 (
    echo.
    echo ОШИБКА: git pull не удался. Проверь интернет или локальные изменения.
    pause
    exit /b 1
)

echo [2/3] Проверка зависимостей...
if not exist "node_modules" (
    echo Устанавливаю npm-зависимости...
    call npm install
)
if not exist "backend\.env" (
    echo ОШИБКА: нет backend\.env — скопируй из backend\.env.example и заполни.
    pause
    exit /b 1
)

echo [3/3] Запуск: фронт http://localhost:20300 + бэкенд :20301
echo Останов — Ctrl+C в этом окне.
call npm run start
