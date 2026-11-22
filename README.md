# Pastebin Service v0.2

Небольшой self-hosted API: создать текстовый paste, сохранить его в PostgreSQL
и получить по публичному ID. Текст paste неизменяемый и доступен любому, кто
знает ID. Paste хранится бессрочно, пока владелец management key не удалит его.
Ключ также позволяет менять необязательные `title` и `language`.
Учётных записей, поиска, frontend и Redis здесь нет.

## Запуск на Windows 10 через Docker Desktop

Локальный Python и локальный PostgreSQL не нужны. Нужны Docker Desktop с Compose
v2, работающий WSL 2 и режим **Linux containers**. Для Windows 10 проверьте свою
редакцию и сборку через `winver` по актуальным
[требованиям Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/).
В документации указана Windows 10 22H2, build 19045 для поддерживаемых редакций;
совместимость конкретного установщика зависит также от поддержки ОС.
Настройка WSL описана в [инструкции Docker](https://docs.docker.com/desktop/features/wsl/).

1. Установите Docker Desktop, выберите WSL 2 backend, при необходимости
   перезагрузите Windows. Запустите Docker Desktop и дождитесь запуска engine.
2. Откройте PowerShell в папке этого проекта, где лежит `compose.yaml`.
3. Проверьте инструменты:

   ```powershell
   docker version
   docker compose version
   ```

4. Создайте конфигурацию (однократно):

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   Замените `POSTGRES_PASSWORD` длинным случайным паролем из латинских букв,
   цифр, `_` и `-`. Такой пароль можно безопасно включить в URL подключения без
   дополнительного кодирования. `.env` исключён из Git и Docker build context.

5. Соберите приложение, запустите БД, примените миграцию и запустите API.
   Выполняйте следующую команду только после успешного завершения предыдущей:

   ```powershell
   docker compose build api
   docker compose up -d --wait db
   docker compose run --rm api alembic upgrade head
   docker compose up -d --wait api
   ```

6. Откройте [Swagger UI](http://localhost:8000/docs).

   ```powershell
   docker compose ps
   docker compose logs --tail 100 api db
   ```

API слушает `127.0.0.1:8000` на Windows. PostgreSQL доступен только внутри
Compose, порт БД наружу не опубликован. Для доступа с других устройств нужно
осознанно изменить привязку порта. API healthcheck проверяет HTTP-процесс через
OpenAPI; он не доказывает доступность БД. Полную проверку выполняет POST + GET.

Миграции запускаются отдельной командой; приложение не создаёт таблицы при
импорте или старте. Обычный повторный запуск: `docker compose up -d --wait`.

## Примеры API через curl в PowerShell

Используйте именно `curl.exe`: в Windows PowerShell команда `curl` может быть
алиасом `Invoke-WebRequest`. Файл JSON позволяет избежать различий в обработке
кавычек между версиями PowerShell. UTF-8 записываем без BOM.

```powershell
$text = "  Привет!`r`n`tСтрока с отступом  `n"
$json = @{ content = $text } | ConvertTo-Json -Compress
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $PWD 'request.json'), $json, $utf8)

$createdJson = curl.exe --silent --show-error --fail-with-body -X POST 'http://localhost:8000/pastes' -H 'Content-Type: application/json' --data-binary '@request.json'
if ($LASTEXITCODE -ne 0) { throw 'POST failed' }
$created = $createdJson | ConvertFrom-Json
$created | Select-Object id, created_at, title, language

curl.exe --include "http://localhost:8000/pastes/$($created.id)"
```

Если установленный в Windows `curl.exe` не поддерживает `--fail-with-body`,
замените этот флаг на `--fail`.

`POST /pastes` принимает обязательное поле `content` и необязательные
`title` / `language` (строка или `null`). Возвращает `201 Created`:

```json
{"id":"V1StGXR8_Z5jdHi6B-myTA","created_at":"2026-10-06T12:00:00Z","title":null,"language":null,"management_key":"<сохраните выданный ключ>"}
```

Заголовок `Location` содержит `/pastes/{id}`. `GET /pastes/{id}` возвращает `200`
и поля `id`, `content`, `created_at`, `title`, `language`. Ключ и его хеш
в публичный ответ не входят.

- `content`: от 1 до 100 000 Unicode-символов, без обрезания или нормализации.
  Пробелы, табуляция, CRLF/LF, пустые строки внутри текста сохраняются точно.
  Текст только из пробелов допустим. U+0000 запрещён: PostgreSQL `TEXT` не может
  его хранить. Это ошибка `422`, а не молчаливое изменение текста.
- Пустой текст, неверные типы, лишние поля и неверный JSON: `422`.
- Неизвестный ID: `404`.
- Ошибки БД и исчерпание пяти попыток выделить ID: `503`.
- Каждый POST создаёт новый paste, даже для одинакового текста. Если клиент
  потерял ответ после commit и повторил POST, возможно появление двух paste.
- Лимит символов не является лимитом размера всего HTTP-запроса в байтах.

## Управление paste в v0.2

Management key — 32 криптографически случайных байта (`secrets.token_hex(32)`),
представленные 64 hex-символами. Он независим от публичного ID и выдаётся
**только в ответе POST**, с `Cache-Control: no-store`. Сохраните его: восстановить
или повторно получить ключ нельзя. Повторный POST создаёт другой paste.
В БД хранится только SHA-256 хеш, сравнение выполняется через
`hmac.compare_digest`. Приложение не записывает ключ и заголовок Authorization
в логи. Передавайте ключ только в заголовке `Authorization: Bearer <key>`.

- `title`: необязательная строка до 200 Unicode-символов.
- `language`: необязательная строка-метка до 50 Unicode-символов; это не
  исполняемый код и не настройка подсветки на сервере.
- Оба поля принимают пустую строку и `null`, не обрезаются и не нормализуются.
  U+0000 запрещён. При отсутствии в POST сохраняется `null`.
- `PATCH /pastes/{id}` принимает только `title` и `language`: отсутствующее
  поле сохраняет значение, явный `null` очищает его. Пустой объект `{}` допустим
  и ничего не меняет. Ответ `200` имеет тот же публичный формат, что и GET.
- `content`, `id`, `created_at` после создания неизменяемы. Неизвестные поля
  в POST и PATCH запрещены (`422`).
- `DELETE /pastes/{id}` физически удаляет запись и возвращает `204` без тела.
  Последующий GET и повторный DELETE с корректным Bearer возвращают `404`.

Контракт ошибок PATCH/DELETE:

| Условие | Ответ |
|---|---|
| Нет Bearer или некорректный формат заголовка/токена | `401`, `WWW-Authenticate: Bearer` |
| Bearer синтаксически корректен, но paste не существует | `404` |
| Paste из v0.1 не имеет ключа | `403`, `This legacy paste has no management key` |
| Ключ не совпадает | `403`, `Invalid management key` |
| Невалидное тело PATCH | `422` |

Проверка Bearer предшествует поиску paste: без него даже повторный DELETE
возвращает `401`. Проверка тела PATCH выполняется до обработчика, поэтому
с корректным Bearer невалидное тело даёт `422` до поиска paste/сравнения ключа.

Пример в том же PowerShell после создания paste (ключ не выводится):

```powershell
$headers = @{ Authorization = "Bearer $($created.management_key)" }
$patchJson = @{ title = 'Example'; language = 'text' } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Patch -Uri "http://localhost:8000/pastes/$($created.id)" -Headers $headers -ContentType 'application/json' -Body $patchJson

# Очистить title, сохранив language:
Invoke-RestMethod -Method Patch -Uri "http://localhost:8000/pastes/$($created.id)" -Headers $headers -ContentType 'application/json' -Body '{"title":null}'

# Удалить этот paste (после этого сценарий persistence для него неприменим):
Invoke-RestMethod -Method Delete -Uri "http://localhost:8000/pastes/$($created.id)" -Headers $headers
```

## Обновление с v0.1

Миграция `0002` добавляет nullable-поля `management_key_hash VARCHAR(64)`,
`title VARCHAR(200)` и `language VARCHAR(50)` без изменения старых записей.
Существующие paste остаются публично доступны с прежними ID, текстом и временем
создания; новые поля равны `null`. Управление ими через API запрещено: ключа
в v0.1 не существовало, а публичный ID не подтверждает владение.

В каталоге проекта, с прежним `.env` и прежним Compose volume, последовательно:

```sh
docker compose build api
docker compose up -d --wait db
docker compose run --rm api alembic upgrade head
docker compose up -d --wait api
```

Команды подходят для macOS Terminal и PowerShell. Миграцию примените перед
запуском API v0.2. POST теперь содержит дополнительное секретное поле
`management_key`; GET содержит новые поля `title` и `language`.
Downgrade к `0001` удаляет метаданные и хеши ключей, сохраняя текст paste;
последующий upgrade не восстанавливает утраченные ключи.

## Проверка сохранности после пересоздания контейнеров

Следующий сценарий использует `$created.id` из примера выше. Выполняйте его в
том же PowerShell, из той же папки проекта. Он сравнивает ID, точный текст и
время создания до и после удаления и повторного создания контейнеров.

```powershell
$pasteId = $created.id
$before = Invoke-RestMethod "http://localhost:8000/pastes/$pasteId"

docker compose down
if ($LASTEXITCODE -ne 0) { throw 'Compose down failed' }
docker compose up -d --wait db
if ($LASTEXITCODE -ne 0) { throw 'Database startup failed' }
docker compose run --rm api alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
docker compose up -d --wait api
if ($LASTEXITCODE -ne 0) { throw 'API startup failed' }

$after = Invoke-RestMethod "http://localhost:8000/pastes/$pasteId"
if ($before.id -cne $after.id -or $before.content -cne $after.content -or $before.created_at -ne $after.created_at) {
    throw 'Persistence check failed'
}
'OK: paste survived container recreation'
```

Данные хранятся в именованном volume `pastebin-service_postgres_data`, смонтированном
в `/var/lib/postgresql/data` для PostgreSQL 17. `docker compose down` сохраняет его.
**Не добавляйте `-v` и не удаляйте volume в Docker Desktop: это удалит данные.**
Смена имени Compose-проекта через `-p` подключит другой volume.
Сохранённый volume не заменяет резервное копирование.

## Интеграционные тесты

Тесты работают с настоящим PostgreSQL, используют миграцию Alembic и отдельную
БД `pastebin_test`. Обычный запуск Compose не запускает тестовый контейнер.

```powershell
docker compose up -d --wait db
docker compose exec db createdb -U pastebin pastebin_test
docker compose --profile test run --build --rm tests
```

`createdb` выполняется один раз; если БД уже существует, пропустите эту команду.
Тесты очищают только таблицу `pastes` в выделенной тестовой БД перед и после
каждого теста. Не запускайте несколько наборов тестов параллельно на одной БД.
Без `TEST_DATABASE_URL`, драйвера `postgresql+psycopg` и суффикса `_test` в имени
БД тесты отказываются запускаться. Рабочая БД `pastebin` не используется.

Проверяются:

- POST + GET, сохранение после commit через независимую сессию;
- Unicode, отступы, CRLF/LF, границы длины, ошибки ввода и `404`;
- время PostgreSQL и запрет передачи `created_at` клиентом;
- повтор после настоящего конфликта первичного ключа, rollback и предел попыток;
- отсутствие повторов для CHECK, другого UNIQUE и ошибки соединения;
- отсутствие SQL, текста paste и пароля в ответе об ошибке и логе приложения;
- ключи управления, контракт `401`/`403`/`404`, удаление и повторное удаление;
- POST/PATCH метаданных, различие отсутствующего поля и `null`, неизменность текста;
- отсутствие ключа и его хеша в публичных ответах и ключа в логах;
- переход `0001` → `0002` с сохранением старого paste и `alembic check`.

Пересоздание Docker-контейнеров проверяется отдельным сценарием выше, поскольку
pytest внутри контейнера не управляет Docker Desktop.

## Как устроен код

| Файл | Ответственность |
|---|---|
| `app/main.py` | FastAPI, подключение роутера, безопасный ответ на ошибки БД |
| `app/config.py` | Чтение и проверка наличия `DATABASE_URL` |
| `app/database.py` | Engine, пул, Session на запрос, rollback при ошибке и закрытие |
| `app/models.py` | Таблица `pastes`, время создания, метаданные и хеш ключа |
| `app/schemas.py` | Валидация тела запроса и формат ответов |
| `app/routers/pastes.py` | POST, GET, PATCH, DELETE и проверка management key |
| `migrations/` | Версионирование схемы через Alembic |
| `tests/` | Проверки API и транзакций на отдельной PostgreSQL |

Путь POST: Pydantic проверяет вход → зависимость открывает Session → обработчик
генерирует случайный ID → PostgreSQL выполняет INSERT и возвращает `created_at`
через RETURNING → commit → ответ `201`. `expire_on_commit=False` позволяет
использовать уже полученные поля без дополнительного SELECT после commit.

ID — `secrets.token_urlsafe(16)`, 128 случайных бит, 22 URL-безопасных символа.
При `IntegrityError` выполняется rollback. Новый ID генерируется только для
`psycopg.errors.UniqueViolation` с ограничением `pastes_pkey`; ошибки других
ограничений не маскируются повтором. Максимум пять попыток вставки.

Путь GET: Session ищет по первичному ключу → возвращает paste или `404`.
Session не разделяется между запросами. Обработчики синхронные (`def`), драйвер
тоже синхронный. Отдельных сервисов и репозиториев нет.

`created_at` — `TIMESTAMPTZ NOT NULL DEFAULT now()`: значение устанавливает
PostgreSQL, приложение не подставляет часы Python. Соединения приложения
используют UTC. Первичный ключ — единственный дополнительный индекс таблицы.

## Локальная разработка без Docker для приложения

Нужны Python 3.12+ и доступный PostgreSQL. Из корня проекта:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
$env:DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:5432/pastebin'
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

В отдельном PowerShell для тестов:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:5432/pastebin_test'
.\.venv\Scripts\python.exe -m pytest
```

Приложение читает переменные окружения, а не `.env` напрямую. В Docker Compose
значения из `.env` подставляются в конфигурацию и передаются контейнеру.

## Типичные проблемы запуска

- Docker daemon недоступен: запустите Docker Desktop и проверьте Linux containers.
- Порт 8000 занят: измените левую часть привязки, например на `127.0.0.1:8001:8000`.
- `relation pastes does not exist`: выполните `alembic upgrade head` командой выше.
- Пароль изменён в `.env`, но volume старый: `POSTGRES_PASSWORD` инициализирует
  пароль только при первом создании БД. Верните прежнее значение либо измените
  пароль роли в самой БД; пересоздание контейнера пароль не сбрасывает.

Основные решения опираются на документацию
[сессий SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_basics.html),
[серверных значений и RETURNING](https://docs.sqlalchemy.org/en/20/orm/persistence_techniques.html),
[зависимостей FastAPI](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
и [образа PostgreSQL](https://hub.docker.com/_/postgres).

## Результаты проверки v0.1

v0.1 завершена и проверена.

Ранее в окружении разработки проверено:

- 22 интеграционных теста прошли на PostgreSQL 17.6 и Python 3.12.14.
- Отдельный процесс Uvicorn: реальные HTTP-запросы POST/GET возвращают
  `201`/`200`, неизвестный ID — `404`; Unicode и CRLF сохраняются точно.
- `alembic check` не обнаружил расхождений модели и миграции; downgrade/upgrade
  выполнены на отдельной тестовой БД.
- Проверка синтаксиса и Ruff прошли; пакет wheel собран.

Starlette выдал предупреждение о будущем переходе TestClient с `httpx` на
`httpx2`; текущие тесты проходят. Прямые зависимости зафиксированы в
`pyproject.toml`; полного lock-файла транзитивных зависимостей пока нет.

После переноса проекта с Windows на MacBook Air с Apple Silicon пользователь
вручную проверил v0.1 в реальном Docker-окружении с Docker Desktop:

- `docker compose build api` проходит успешно.
- PostgreSQL запускается и становится healthy; миграции Alembic применяются.
- API запускается и становится healthy.
- `POST /pastes` создаёт paste, а `GET /pastes/{id}` возвращает тот же ID,
  `created_at` и точный исходный текст.
- После `docker compose down` и повторного `docker compose up -d --wait`
  ранее созданный paste остаётся доступен: PostgreSQL volume сохраняет данные
  после пересоздания контейнеров.
- [Swagger UI](http://localhost:8000/docs) работает.

Эти результаты v0.1 предоставлены пользователем; при первоначальном обновлении
документации Docker-сценарий и интеграционные тесты повторно не запускались.

## Результаты проверки v0.2

- `docker compose --profile test run --build --rm tests`: **66 тестов прошли**
  в Docker на Python 3.12.15 с настоящим PostgreSQL и отдельной БД `pastebin_test`.
- Проверены ключи управления, ошибки доступа, POST/PATCH метаданных, удаление,
  повторное удаление, неизменность исходного текста и отсутствие ключа в
  публичных ответах и логах приложения.
- Миграция `0001` → `0002` проверена на старой записи: ID, точный текст и время
  создания сохранены; новые поля равны `null`. `alembic check` прошёл.
- Проверка синтаксиса Python прошла. Новые зависимости не добавлены.
- Остаётся предупреждение Starlette о будущем переходе TestClient с `httpx`
  на `httpx2`; ошибок тестов нет.

Рабочая БД и запущенный API v0.1 при этих проверках не обновлялись.
Для запуска v0.2 выполните команды из раздела «Обновление с v0.1».
Пересоздание рабочих контейнеров и ручная проверка Swagger для v0.2 отдельно
не выполнялись.
