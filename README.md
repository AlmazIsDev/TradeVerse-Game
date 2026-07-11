# TradeVerse

**TradeVerse** — веб-приложение (браузерная экономическая игра-симулятор) с торговлей акциями, банковскими операциями, магазинами и лидербордом. Проект состоит из двух частей: **backend** на FastAPI + MongoDB и **frontend** на React 19 + Vite.

---

## Содержание

- [Архитектура](#архитектура)
- [Технологический стек](#технологический-стек)
- [Требования](#требования)
- [Быстрый старт](#быстрый-старт)
- [Backend](#backend)
- [Frontend](#frontend)
- [API](#api)
- [Структура проекта](#структура-проекта)
- [Локализация](#локализация)
- [Учётные данные по умолчанию](#учётные-данные-по-умолчанию)

---

## Архитектура

```
┌─────────────────────────┐         HTTP / JWT          ┌──────────────────────────┐
│  Frontend (React + Vite)│  ─────────────────────────► │  Backend (FastAPI)       │
│  http://localhost:5173  │  ◄───────────────────────── │  http://localhost:20301   │
└─────────────────────────┘      REST /api/*            └────────────┬─────────────┘
                                                                     │ Motor (async)
                                                                     ▼
                                                          ┌──────────────────────┐
                                                          │  MongoDB (tradeverse)│
                                                          └──────────────────────┘
```

- Frontend — SPA, общается с backend по REST через `/api/*`. В dev-режиме Vite проксирует `/api` на `http://localhost:20301`.
- Backend — асинхронный FastAPI-сервер, хранит данные в MongoDB, аутентификация через JWT (Bearer).
- CORS на бэкенде разрешает origin `http://localhost:5173`.

---

## Технологический стек

| Слой      | Технологии |
|-----------|-----------|
| **Frontend** | React 19, Vite 8, lucide-react (иконки), i18next / react-i18next, oxlint. Без Redux — состояние на React-хуках + `localStorage`. Кастомный CSS с CSS-переменными (тёмная тема). |
| **Backend**  | Python 3, FastAPI 0.138, Uvicorn, Motor (async MongoDB), Pydantic v2, bcrypt, PyJWT, python-dotenv. |
| **База данных** | MongoDB (без ORM, нативный драйвер Motor). |

---

## Требования

- **Node.js** (LTS) и **npm** — для frontend
- **Python 3.10+** и **pip** — для backend
- **MongoDB** — удалённый или локальный инстанс (строка подключения в `backend/.env`)

---

## Быстрый старт

Нужны два терминала — один для backend, один для frontend.

### 1. Backend

```bash
cd backend
pip install -r requirements.txt

# Убедитесь, что в backend/.env указан корректный MONGODB_URL и JWT_SECRET
python main.py
```

Backend поднимется на `http://localhost:20301`. Проверка:

```bash
curl http://localhost:20301/api/health
# {"status":"ok"}
```

При первом старте автоматически создаются индексы, admin-пользователь, дефолтные акции (AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA) и конфиг приложения.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend поднимется на `http://localhost:5173`. Откройте этот адрес в браузере.

> Интерактивная документация API (Swagger) доступна на `http://localhost:20301/docs`.

---

## Backend

### Переменные окружения (`backend/.env`)

```env
MONGODB_URL=mongodb://<user>:<password>@<host>:<port>/tradeverse?authSource=tradeverse
JWT_SECRET=<секретный-ключ-для-подписи-JWT>
```

### Запуск

```bash
python main.py
# или
uvicorn main:app --host 0.0.0.0 --port 20301 --reload
```

### Модель данных (коллекции MongoDB)

| Коллекция | Назначение | Ключевые поля |
|-----------|-----------|---------------|
| `users` | Аккаунты | `username` (unique), `hashed_password`, `role`, `balance`, `card_number`, `card_visible` |
| `stocks` | Акции | `symbol` (unique), `name`, `price`, `change`, `changePercent`, `currency` |
| `transactions` | История сделок | `userId`, `type` (buy/sell), `symbol`, `amount`, `price`, `timestamp` |
| `app_config` | Конфиг приложения | `key` (unique), `value` |
| `analytics` | События/аналитика | `userId`, `eventType`, `data`, `timestamp` |
| `leaderboard` | Рейтинг | `userId`, `username`, `profit`, `rank` |

### Аутентификация и роли

- Пароли хешируются через **bcrypt**.
- При логине выдаётся **JWT** (HS256, срок жизни 24 часа) с payload `{ sub, username, role }`.
- Токен передаётся в заголовке `Authorization: Bearer <token>`.
- Роли: `user` (по умолчанию) и `admin` (управление пользователями, акциями, конфигом).

---

## Frontend

### Запуск и скрипты

```bash
npm run dev      # dev-сервер (Vite, http://localhost:5173)
npm run build    # production-сборка в dist/
npm run preview  # локальный предпросмотр сборки
npm run lint     # линтинг (oxlint)
```

### Переменные окружения

- `VITE_API_URL` — базовый URL backend API (по умолчанию `http://localhost:20301`).

### Ключевые экраны

- **AuthPage** — вход / регистрация.
- **Dashboard** — основная оболочка с сайдбаром, хедером и вкладками:
  - **Account** — баланс, недельная аналитика, история транзакций
  - **Stocks** — торговля акциями (списки, графики, покупка/продажа)
  - **Bank** — история операций
  - **Shop** — магазины (GPU, CPU, кейсы, комплектующие, недвижимость, бизнес)
  - **Leaderboard** и др. разделы
- **AdminPanel** — панель администратора (акции, пользователи, транзакции, конфиги); доступна пользователям с ролью `admin`.

### Состояние

Без Redux/Context: локальный стейт на хуках + `localStorage` (ключ `TRADEVERSE_USER` хранит объект пользователя с JWT). Работа с API — через сервис `src/services/api.js` и хуки `useApi` / `useApiOnMount`.

---

## API

Базовый префикс — `/api`. Основные группы эндпоинтов:

### Аутентификация
| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| POST | `/api/register` | — | Регистрация |
| POST | `/api/login` | — | Вход, возвращает JWT |
| GET | `/api/user/me` | ✅ | Текущий пользователь |
| PATCH | `/api/user/card-visibility` | ✅ | Переключить видимость карты |

### Акции
| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| GET | `/api/stocks` | — | Все акции |
| GET | `/api/stocks/{symbol}` | — | Акция по символу |
| POST | `/api/stocks` | admin | Создать/обновить акцию |
| DELETE | `/api/stocks/{symbol}` | admin | Удалить акцию |

### Транзакции, конфиг, лидерборд
| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| GET | `/api/account/transactions` | — | История транзакций |
| GET | `/api/config/{key}` | — | Значение конфига |
| POST | `/api/config` | admin | Обновить конфиг |
| GET | `/api/leaderboard` | — | Топ пользователей |

### Админ
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/admin/users` | Список пользователей |
| PATCH | `/api/admin/users/{user_id}` | Обновить пользователя |
| DELETE | `/api/admin/users/{user_id}` | Удалить пользователя |
| GET | `/api/admin/transactions` | Все транзакции |
| DELETE | `/api/admin/transactions/{tx_id}` | Удалить транзакцию |

### Служебные
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Проверка доступности |

> Полная актуальная спецификация — в Swagger UI на `/docs`.

---

## Структура проекта

```
TradeVerse/
├── backend/
│   ├── main.py            # FastAPI-приложение, все эндпоинты, JWT-аутентификация
│   ├── database.py        # Подключение к MongoDB, helper-функции
│   ├── models.py          # Pydantic-модели документов
│   ├── schemas.py         # Pydantic-схемы валидации запросов/ответов
│   ├── init_db.py         # Инициализация БД, индексы, seed-данные
│   ├── requirements.txt   # Python-зависимости
│   └── .env               # MONGODB_URL, JWT_SECRET
│
├── frontend/
│   ├── src/
│   │   ├── components/     # React-компоненты (Dashboard, StocksTab, AdminPanel, ...)
│   │   ├── hooks/          # useApi, useApiOnMount
│   │   ├── services/       # api.js — клиент REST API
│   │   ├── i18n/           # локали en / ru / uk
│   │   ├── App.jsx         # корневой компонент (флоу авторизации)
│   │   └── main.jsx        # точка входа React
│   ├── vite.config.js      # конфиг Vite + прокси /api
│   └── package.json
│
└── README.md
```

---

## Локализация

Интерфейс поддерживает три языка через `i18next`:

- 🇬🇧 English (`en`)
- 🇷🇺 Русский (`ru`) — язык по умолчанию
- 🇺🇦 Українська (`uk`)

Файлы переводов — в `frontend/src/i18n/locales/`. Переключение языка — через компонент `LanguageSwitcher` в хедере.

---

## Учётные данные по умолчанию

При инициализации БД создаётся администратор:

- **Логин:** `admin`
- **Пароль:** задаётся в `backend/init_db.py` (сменить перед деплоем в production)

> ⚠️ **Безопасность:** не храните реальные секреты (`MONGODB_URL`, `JWT_SECRET`, пароль администратора) в репозитории. Перед публичным развёртыванием смените все дефолтные значения и вынесите `.env` из-под контроля версий.

---
:0