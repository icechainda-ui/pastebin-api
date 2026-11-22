# Pastebin Service

[![Tests](https://github.com/icechainda-ui/pastebin-api/actions/workflows/tests.yml/badge.svg)](https://github.com/icechainda-ui/pastebin-api/actions/workflows/tests.yml)

REST API для создания, хранения и управления текстовыми записями, разработанный на **Python, FastAPI и PostgreSQL**.

Сервис позволяет создавать записи, получать их по публичному идентификатору, редактировать метаданные и удалять записи с помощью секретного ключа управления.

Проект демонстрирует работу с REST API, реляционной базой данных, миграциями, контейнеризацией и интеграционным тестированием.

## Технологии

- **Python 3.12+**
- **FastAPI** — разработка REST API
- **Pydantic** — валидация данных
- **SQLAlchemy 2** — ORM и управление транзакциями
- **PostgreSQL 17** — хранение данных
- **Alembic** — миграции базы данных
- **Docker Compose** — контейнеризация приложения и БД
- **Pytest + HTTPX** — интеграционное тестирование
- **GitHub Actions** — автоматический запуск тестов

## Возможности

- Создание и получение текстовых записей по уникальному ID.
- Необязательные метаданные `title` и `language`.
- Редактирование метаданных через PATCH.
- Удаление записей через DELETE.
- Управление записями с помощью криптографически случайного ключа.
- Хранение SHA-256 хеша ключа вместо самого ключа.
- Валидация входных данных и обработка HTTP-ошибок.
- Сохранение данных PostgreSQL между перезапусками контейнеров.
- Миграции базы данных с сохранением существующих записей.
- Автоматическая документация API через Swagger UI.
- 66 интеграционных тестов с настоящей PostgreSQL.

## Быстрый запуск

### Требования

- Docker с поддержкой Docker Compose
- Git

Локальная установка Python и PostgreSQL не требуется.

### 1. Клонирование репозитория

```bash
git clone https://github.com/icechainda-ui/pastebin-api.git
cd pastebin-api
```

### 2. Настройка окружения

Создайте `.env` на основе примера.

macOS / Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Замените `POSTGRES_PASSWORD` в `.env` на собственный длинный случайный пароль из латинских букв, цифр, `-` и `_`.

Если файл `.env` уже существует, не перезаписывайте его.

### 3. Запуск приложения

Выполните команды последовательно:

```bash
docker compose build api
docker compose up -d --wait db
docker compose run --rm api alembic upgrade head
docker compose up -d --wait api
```

Проверить состояние контейнеров:

```bash
docker compose ps
```

После запуска доступны:

- **Swagger UI:** http://localhost:8000/docs
- **OpenAPI:** http://localhost:8000/openapi.json

API доступен только локально через `127.0.0.1:8000`. Порт PostgreSQL наружу не опубликован.

### Остановка

```bash
docker compose down
```

Данные PostgreSQL сохраняются в Docker volume.

**Важно:** команда `docker compose down -v` удаляет volume с данными БД. Не используйте её, если хотите сохранить записи.

## API

| Метод | Endpoint | Описание | Успешный ответ |
|---|---|---|---|
| POST | `/pastes` | Создать запись | 201 |
| GET | `/pastes/{paste_id}` | Получить запись | 200 |
| PATCH | `/pastes/{paste_id}` | Изменить метаданные | 200 |
| DELETE | `/pastes/{paste_id}` | Удалить запись | 204 |

### POST /pastes

Создание новой текстовой записи.

Пример тела запроса:

```json
{
  "content": "print('Hello, world!')",
  "title": "Hello World",
  "language": "python"
}
```

Пример ответа `201 Created`:

```json
{
  "id": "V1StGXR8_Z5jdHi6B-myTA",
  "created_at": "2026-11-22T12:00:00Z",
  "title": "Hello World",
  "language": "python",
  "management_key": "<secret-management-key>"
}
```

`management_key` возвращается только при создании записи. Сохраните его для дальнейшего редактирования и удаления.

Поле `content` обязательно и принимает от 1 до 100 000 Unicode-символов. Поля `title` и `language` необязательны.

### GET /pastes/{paste_id}

Получение записи по публичному идентификатору.

Пример ответа:

```json
{
  "id": "V1StGXR8_Z5jdHi6B-myTA",
  "created_at": "2026-11-22T12:00:00Z",
  "title": "Hello World",
  "language": "python",
  "content": "print('Hello, world!')"
}
```

Ключ управления и его хеш в публичный ответ не включаются.

### PATCH /pastes/{paste_id}

Позволяет изменять только поля `title` и `language`.

Для выполнения запроса необходим заголовок:

```text
Authorization: Bearer <management_key>
```

Пример тела запроса:

```json
{
  "title": "Updated Hello World",
  "language": null
}
```

Явное значение `null` очищает поле. Отсутствующее поле сохраняет прежнее значение.

Поля `content`, `id` и `created_at` после создания записи неизменяемы.

### DELETE /pastes/{paste_id}

Удаляет запись при предъявлении корректного management key.

Успешный ответ — `204 No Content`.

После удаления запись становится недоступной; последующий GET возвращает `404 Not Found`.

### Обработка ошибок

| HTTP-статус | Значение |
|---|---|
| 401 | Отсутствует или некорректен Bearer-токен |
| 403 | Неверный ключ управления или запись создана до появления ключей |
| 404 | Запись не найдена |
| 422 | Ошибка валидации данных |
| 503 | Ошибка работы с базой данных или невозможность выделить ID |

## Безопасность

Каждая запись получает независимый от публичного ID секретный ключ управления.

- Ключ генерируется с помощью `secrets.token_hex(32)`.
- В PostgreSQL сохраняется только SHA-256 хеш ключа.
- Сравнение хешей выполняется через `hmac.compare_digest`.
- Ключ выдаётся однократно, в ответе POST с заголовком `Cache-Control: no-store`.
- API не возвращает ключ или его хеш при получении записи.
- Ключ управления не записывается приложением в логи.
- Pydantic запрещает неизвестные поля в POST и PATCH.

Авторизация пользователей и учётные записи в текущей версии не предусмотрены.

## Архитектура проекта

```text
pastebin-api/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   └── routers/
│       └── pastes.py
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_create_pastes.py
│       └── 0002_add_paste_management.py
├── tests/
│   ├── conftest.py
│   ├── test_pastes.py
│   └── test_management.py
├── .github/workflows/
│   └── tests.yml
├── Dockerfile
├── compose.yaml
├── alembic.ini
├── pyproject.toml
└── README.md
```

### Основные компоненты

- `app/main.py` — инициализация FastAPI, подключение маршрутов и обработка ошибок БД.
- `app/config.py` — получение и проверка конфигурации подключения.
- `app/database.py` — SQLAlchemy Engine и управление сессиями.
- `app/models.py` — ORM-модель записи.
- `app/schemas.py` — Pydantic-схемы запросов и ответов.
- `app/routers/pastes.py` — REST endpoints, генерация ID и проверка management key.
- `migrations/` — управление схемой PostgreSQL через Alembic.
- `tests/` — интеграционные проверки API, БД и миграций.

Приложение использует синхронные обработчики и синхронный драйвер Psycopg.

Каждый запрос работает со своей SQLAlchemy Session. При ошибках транзакции выполняется rollback.

Идентификаторы записей генерируются через `secrets.token_urlsafe(16)`. При конфликте первичного ключа предусмотрены повторные попытки вставки.

Время создания устанавливается PostgreSQL через `TIMESTAMPTZ DEFAULT now()`.

## Миграции

В проекте реализованы две миграции Alembic:

- `0001` — создание таблицы `pastes`.
- `0002` — добавление `title`, `language` и `management_key_hash`.

Миграция v0.1 → v0.2 сохраняет старые записи, их идентификаторы, содержимое и время создания.

Старые записи остаются доступными для чтения, но не могут редактироваться или удаляться через management key, поскольку до v0.2 ключи управления не выдавались.

Применение актуальных миграций:

```bash
docker compose run --rm api alembic upgrade head
```

Проверка текущей версии:

```bash
docker compose run --rm api alembic current
```

Для v0.2 ожидается `0002 (head)`.

Перед миграцией рабочей БД рекомендуется создать резервную копию.

## Тестирование

Проект содержит **66 интеграционных тестов**, использующих настоящую PostgreSQL.

Тесты проверяют:

- Создание, получение, редактирование и удаление записей.
- Валидацию текста, Unicode и ограничения длины.
- Сохранение исходного содержимого без изменения.
- Обработку HTTP-ошибок.
- Генерацию и проверку management key.
- Недоступность секретных данных через публичный API.
- Транзакции, rollback и конфликты первичных ключей.
- Совместимость миграций v0.1 и v0.2.
- Проверку схемы через `alembic check`.

Для локального запуска используется отдельная база `pastebin_test`.

### Запуск тестов через Docker

Убедитесь, что `.env` настроен, затем выполните:

```bash
docker compose up -d --wait db
docker compose exec -T db createdb -U pastebin pastebin_test
docker compose --profile test run --build --rm tests
```

Команда `createdb` выполняется только при первом создании тестовой БД. Если `pastebin_test` уже существует, пропустите её.

Тесты не используют рабочую базу `pastebin`.

### GitHub Actions

Workflow расположен в `.github/workflows/tests.yml`.

Он автоматически запускается при:

- Push в ветку `main`.
- Создании или обновлении pull request.

GitHub Actions поднимает PostgreSQL, создаёт тестовую базу и выполняет интеграционные тесты в Docker.

[Посмотреть результаты CI](https://github.com/icechainda-ui/pastebin-api/actions)

## Статус проекта

**Текущая версия: v0.2.0**

- Реализованы основные операции REST API.
- Поддерживается управление записями через секретный ключ.
- Миграция `0002` успешно применена к рабочей БД.
- Приложение запущено и проверено в Docker на macOS.
- POST, PATCH и Bearer-авторизация проверены через Swagger UI.
- Проверена очистка метаданных через JSON `null`.
- При повторном DELETE получен ожидаемый ответ `404`.
- 66 интеграционных тестов успешно прошли в Docker.
- Настроен GitHub Actions; первый запуск CI завершился успешно.

Проект реализован как самостоятельный учебный backend-сервис для демонстрации навыков разработки REST API на Python.
