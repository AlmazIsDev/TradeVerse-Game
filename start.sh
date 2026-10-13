#!/usr/bin/env bash
# TradeVerse: обновление из GitHub и запуск (frontend + backend).
# Запуск:  bash start.sh   (или ./start.sh после chmod +x)
set -e
cd "$(dirname "$0")"

echo "[1/4] Обновление из GitHub (AlmazIsDev/TradeVerse-Game)..."
git pull origin main

echo "[2/4] Зависимости..."
[ -d node_modules ] || npm install
pip3 install -q -r backend/requirements.txt

echo "[3/4] Проверка конфига..."
if [ ! -f backend/.env ]; then
  echo "ОШИБКА: нет backend/.env — скопируй из backend/.env.example и заполни."
  exit 1
fi

echo "[4/4] Сборка и запуск: фронт http://<ip>:20300, бэкенд :20301"
echo "Останов — Ctrl+C. Для фонового запуска: nohup npm run start > /var/log/tradeverse.log 2>&1 &"
exec npm run start
