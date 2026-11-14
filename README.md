# IGNIS 0G backend

API каталога читает данные из локального PostgreSQL. Пустая база возвращает пустой каталог. AI пока использует мок: отвечает `insufficient_evidence`. Импорт и полноценный AI ещё не реализованы.

## Запуск

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Интерактивный контракт: http://127.0.0.1:8000/docs. Целевая схема БД и полный контракт, включая P1 и импорт, зафиксированы в [архитектуре](docs/ARCHITECTURE.md) и [спецификации API](docs/API_SPEC.md). Реализованы маршруты P0 каталога, datasets и чата; чат возвращает `insufficient_evidence`. `/health` проверяет PostgreSQL через SELECT 1 и возвращает 503 при недоступности БД.

## Схема PostgreSQL

Задайте `DATABASE_URL` с драйвером asyncpg, например `postgresql+asyncpg://user:password@localhost:5432/ignis`, затем выполните `alembic upgrade head`. Для отката: `alembic downgrade base`. API использует DATABASE_URL из окружения; по умолчанию подключается к локальному Compose на порту 55432.

Миграция создаёт таблицы studies, sources, findings, datasets, media и relations. Принадлежность источника одной из сторон relation проверяется будущим импортёром. Таблица chunks и расширение pgvector будут добавлены отдельной миграцией после согласования модели и размерности эмбеддингов.

## Локальная база данных

Нужны Docker и Docker Compose. Данные хранятся в Docker-томе `postgres_data` и сохраняются после остановки контейнера.

```bash
docker compose up -d --wait
DATABASE_URL=postgresql+asyncpg://ignis:ignis_local@127.0.0.1:55432/ignis .venv/bin/alembic upgrade head
```

Адрес доступен только на этом компьютере; `ignis_local` — пароль исключительно для локальной разработки. После изменения `POSTGRES_PASSWORD` в окружении используйте тот же пароль в `DATABASE_URL`; пароль существующего тома автоматически не меняется. Остановить базу: `docker compose stop`. После запуска БД и миграции `/health` возвращает 200.

## Проверки

После запуска БД и миграции: `.venv/bin/pip install -e ".[test]"` и `.venv/bin/python -m pytest -q`. Интеграционные данные создаются в транзакции и откатываются.
