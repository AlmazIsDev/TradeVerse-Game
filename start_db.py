#!/usr/bin/env python3
"""
TradeVerse — инициализация схемы MongoDB по настройкам из backend/.env.

Скрипт:
  1. Загружает backend/.env (создаёт из .env.example, если его нет).
  2. Проверяет, что MONGODB_URL отвечает (ping через TCP + mongosh, если установлен).
  3. Запускает backend/init_db.py для создания индексов, admin-пользователя,
     сидов акций, миграций, app_config.
  4. Опционально проксирует ping в "dry-run" — без init_db.

Саму СУБД этот скрипт НЕ запускает: её старт — ваша зона ответственности
(Docker / нативный mongod / удалённый кластер). Строка подключения — в .env.

Использование:
    python start_db.py                 # ping + init_db
    python start_db.py --check         # только ping (без init_db)
    python start_db.py --show-config   # напечатать конфиг и выйти
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import dotenv_values, load_dotenv
except ImportError:
    sys.exit(
        "❌ Не найден пакет python-dotenv.\n"
        "   Установите: pip install python-dotenv\n"
        "   Или: pip install -r backend/requirements.txt"
    )

# ── Пути ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / "backend"
INIT_DB = BACKEND_DIR / "init_db.py"
ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE = BACKEND_DIR / ".env.example"

# ── Дефолты (если в .env переменной нет) ────────────────────────────────────

DEFAULTS: dict[str, str] = {
    "MONGODB_URL": "mongodb://localhost:27017/",
    "DATABASE_NAME": "tradeverse",
    "DB_AUTO_INIT": "true",
    "DB_READY_TIMEOUT": "60",
}


# ── Чтение .env ─────────────────────────────────────────────────────────────

def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    if ENV_EXAMPLE.exists():
        print(f"ℹ  backend/.env не найден — копирую из backend/.env.example")
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        print("⚠  backend/.env и backend/.env.example отсутствуют — "
              "будут использованы только встроенные дефолты.")


def load_config() -> dict[str, str]:
    ensure_env_file()
    load_dotenv(ENV_FILE, override=False)
    cfg: dict[str, str] = dict(DEFAULTS)
    if ENV_FILE.exists():
        file_values = dotenv_values(ENV_FILE) or {}
        for k, v in file_values.items():
            if v is None:
                continue
            if k in DEFAULTS:
                cfg[k] = str(v)
    for k in cfg.keys():
        env_v = os.environ.get(k)
        if env_v is not None:
            cfg[k] = env_v
    return cfg


def parse_bool(s: str) -> bool:
    return s.strip().lower() in ("1", "true", "yes", "y", "on")


# ── Парсинг URL и ping ───────────────────────────────────────────────────────

def parse_mongo_url(url: str) -> tuple[str, int]:
    """Возвращает (host, port) из mongodb://[user:pass@]host:port[/db]."""
    if "://" not in url:
        raise ValueError(f"Некорректный MONGODB_URL: {url!r}")
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 27017
    return host, port


def wait_for_mongo(host: str, port: int, timeout: int) -> None:
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            with socket.create_connection((host, port), timeout=1):
                tcp_ok = True
        except OSError:
            tcp_ok = False
        if tcp_ok:
            if shutil.which("mongosh"):
                r = subprocess.run(
                    ["mongosh", f"mongodb://{host}:{port}/",
                     "--quiet", "--eval", "db.runCommand({ping:1}).ok"],
                    capture_output=True, text=True,
                )
                if "1" in (r.stdout or ""):
                    print(f"✓ MongoDB отвечает ({host}:{port}, попытка #{attempt}).")
                    return
            else:
                if attempt >= 3:
                    print(f"✓ MongoDB слушает {host}:{port} (попытка #{attempt}).")
                    return
        time.sleep(1)
    sys.exit(
        f"❌ MongoDB не ответил за {timeout} сек по адресу {host}:{port}.\n"
        f"   Проверьте, что СУБД запущена, и что MONGODB_URL={os.environ.get('MONGODB_URL', '<не задан>')!r} корректен."
    )


# ── init_db ──────────────────────────────────────────────────────────────────

def run_init_db() -> None:
    if not INIT_DB.exists():
        print("⚠  backend/init_db.py не найден — пропускаю.")
        return
    print("🌱 Запускаю backend/init_db.py ...")
    try:
        subprocess.run(["python", str(INIT_DB)], cwd=BACKEND_DIR, check=True)
    except subprocess.CalledProcessError:
        print("❌ init_db.py завершился с ошибкой. Возможно, нужно доустановить зависимости:")
        print(f"   pip install -r {BACKEND_DIR / 'requirements.txt'}")
        raise


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TradeVerse: инициализация схемы MongoDB по backend/.env.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--check", action="store_true",
                   help="Только ping (без init_db).")
    p.add_argument("--no-init", action="store_true",
                   help="Не запускать init_db, даже если DB_AUTO_INIT=true.")
    p.add_argument("--show-config", action="store_true",
                   help="Напечатать конфиг и выйти.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config()

    if args.show_config:
        print("— конфиг из backend/.env —")
        for k in DEFAULTS:
            print(f"  {k} = {cfg.get(k, '')!r}")
        try:
            host, port = parse_mongo_url(cfg["MONGODB_URL"])
            print(f"  (parsed) host:port = {host}:{port}")
        except ValueError as e:
            print(f"  (parsed) ошибка: {e}")
        return 0

    auto_init = (not args.no_init) and (not args.check) and parse_bool(cfg["DB_AUTO_INIT"])
    ready_timeout = int(cfg["DB_READY_TIMEOUT"])

    try:
        host, port = parse_mongo_url(cfg["MONGODB_URL"])
    except ValueError as e:
        sys.exit(f"❌ {e}")

    print(f"🔎 Проверяю MongoDB по {cfg['MONGODB_URL']!r} (host={host}, port={port}) ...")
    wait_for_mongo(host, port, ready_timeout)

    if args.check:
        print("✅ Только проверка (--check) — init_db не запускался.")
        return 0

    if auto_init:
        run_init_db()
    else:
        print("ℹ  DB_AUTO_INIT=false (или --no-init) — init_db пропущен.")

    print(f"\n✅ Всё готово. База — {cfg['DATABASE_NAME']}.")
    print(f"   Следующий шаг: cd backend && python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
