# IGNIS 0G backend

API каталога читает данные из локального PostgreSQL. Пустая база возвращает пустой каталог. Чат ищет подтверждения в проиндексированных источниках и передаёт найденные фрагменты провайдеру чата.

## Запуск через Docker

```bash
docker compose up --build -d --wait
curl -fsS http://127.0.0.1:8000/health
```

Compose запускает PostgreSQL, применяет миграции и поднимает API. Swagger доступен на http://127.0.0.1:8000/docs. Для остановки используйте `docker compose stop`.

## Запуск API на хосте

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
uvicorn app.main:app --reload
```

Интерактивный контракт: http://127.0.0.1:8000/docs. Целевая схема БД и полный контракт, включая P1 и импорт, зафиксированы в [архитектуре](docs/ARCHITECTURE.md) и [спецификации API](docs/API_SPEC.md). Доступны каталог, наборы данных, отдельные маршруты источников, выводов и медиа, а также проверенные связи и граф Nexus. Сравнение пока возвращает `insufficient_evidence`. `/health` проверяет PostgreSQL через SELECT 1 и возвращает 503 при недоступности БД.

## Схема PostgreSQL

Задайте `DATABASE_URL` с драйвером asyncpg, например `postgresql+asyncpg://user:password@localhost:5432/ignis`, затем выполните `alembic upgrade head`. Для отката: `alembic downgrade base`. API использует DATABASE_URL из окружения; по умолчанию подключается к локальному Compose на порту 55432.

Миграция создаёт таблицы studies, sources, findings, datasets, media и relations. Принадлежность источника одной из сторон relation проверяется импортёром. Миграции RAG включают pgvector и приводят `chunks.embedding` к размерности 1024. Для базы с уже установленным расширением будет использована существующая установка.

## Локальная база данных

Нужны Docker и Docker Compose. Данные хранятся в Docker-томе `postgres_data` и сохраняются после остановки контейнера.

```bash
docker compose up -d --wait db
DATABASE_URL=postgresql+asyncpg://ignis:ignis_local@127.0.0.1:55432/ignis .venv/bin/alembic upgrade head
```

Адрес доступен только на этом компьютере; `ignis_local` — пароль исключительно для локальной разработки. После изменения `POSTGRES_PASSWORD` в окружении используйте тот же пароль в `DATABASE_URL`; пароль существующего тома автоматически не меняется. Остановить базу: `docker compose stop`. После запуска БД и миграции `/health` возвращает 200.

## Проверки

После запуска БД и миграции выполните `.venv/bin/python -m pytest -q`. Зависимости для тестов входят в `requirements.lock`. GitHub Actions запускает тесты на чистой PostgreSQL и проверяет применение и откат миграций. Интеграционные данные создаются в транзакции и откатываются.

## Импорт исследовательских данных

Подготовьте JSON по разделу 10 `docs/API_SPEC.md`. Из корня репозитория:

```bash
.venv/bin/python -m scripts.import_studies /path/to/studies.json --dry-run
.venv/bin/python -m scripts.import_studies /path/to/studies.json
```

Обе команды используют ту же `DATABASE_URL`, что и API. `--dry-run` валидирует пакет и ссылки относительно пакета и текущей БД, без записи. Обычный импорт выполняется одной транзакцией; при ошибке пакет не записывается частично. Повторная загрузка обновляет записи по стабильным ключам, сохраняя UUID. Отсутствующие в новом пакете объекты не удаляются; optional поля переданных объектов получают контрактные defaults.

Проверяются дубликаты ключей, HTTP(S) URL, ссылки на источники и исследования, числовые ряды и обязательные пояснения для digitized/derived. Исходный текст хешируется; `indexed_hash` импортёр не меняет, поэтому изменённый текст требует переиндексации. Проверка достоверности научных утверждений и разрешение `verified=true` остаются ответственностью человека: импортируйте только проверенные материалы. Демонстрационные данные в тестах синтетические и не загружаются в рабочую базу.


## Индексация и чат

Настройте `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` по `.env.example`.
Для Alem задайте отдельные ключи `LLM_API_KEY`, `EMBEDDING_API_KEY` и
`RERANKER_API_KEY`. Модели в примере — `qwen3-8`, `text-1024` и
`reranker`. Модель эмбеддингов должна возвращать **1024** измерения. Адаптер
для `text-1024` использует её собственную размерность. Параметр
`EMBEDDING_SEND_DIMENSIONS=true` включает передачу `dimensions=1024`
для совместимых API. Миграция `0003_embedding_dimension_1024` очищает
производный индекс чанков. Повторно постройте его из сохранённых источников.

```bash
set -a
. ../.env
set +a
alembic upgrade head
python -m scripts.index_sources --check-provider
python -m scripts.import_nasa_kb /path/to/nasa-fire-safety-kb --dry-run
python -m scripts.import_nasa_kb /path/to/nasa-fire-safety-kb
python -m scripts.index_sources
uvicorn app.main:app
```

Для DeepSeek через OpenRouter задайте `LLM_BASE_URL=https://openrouter.ai/api/v1`,
`LLM_MODEL=deepseek/deepseek-v4.1-flash` и ключ OpenRouter в `LLM_API_KEY`.
Ключи эмбеддингов и reranker задаются отдельно. `RAG_MAX_OUTPUT_TOKENS`
ограничивает длину генерации, по умолчанию 3200 токенов.
Чат учитывает контекст диалога и запрошенную глубину ответа. Ссылки в тексте
соответствуют проверенным фрагментам из БД. Поле `suggested_questions`
содержит до двух коротких вопросов для продолжения разговора, если их
подсказывает найденный контекст.

Начальные параметры `RAG_CHUNK_TOKENS=400`, `RAG_CHUNK_OVERLAP=50`,
`RAG_CANDIDATE_LIMIT=20`, `RAG_CONTEXT_LIMIT=5`, `RAG_BATCH_SIZE=32`.
`RAG_TIMEOUT` задаёт таймаут каждой попытки, `RAG_RETRIES` задаёт число
повторов после временной ошибки. Для внешнего `/rerank` укажите
`RERANKER_MODEL` и при необходимости параметры отдельного сервиса.
Без reranker или при его недоступности используется порядок pgvector.

Карточки импортируются как вторичные источники. Реестр даёт ссылку на портал
NASA NTRS и идентификатор публикации, который сохраняется в названии источника.
Чанки сохраняют раздел Markdown и страницу PDF, если она существует.
Для других документов используйте существующий импорт с
`--documents manifest.json`. Манифест сопоставляет slug и ключ источника с
файлом относительно манифеста, например
`{"flex-1":{"report":"docs/report.pdf"}}`. Поддерживаются PDF с текстовым
слоем, Markdown и TXT. При сборке Docker таблица токенизации загружается
заранее. На хосте tiktoken кеширует её при первой индексации.

```bash
curl -fsS http://127.0.0.1:8000/api/v1/assistant/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Какие выводы приводит карточка FLEX-1?","study_id":"flex-1"}'
```
