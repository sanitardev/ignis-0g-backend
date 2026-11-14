# IGNIS 0G backend

Начальный контрактный мок API для независимой разработки фронтенда и AI. В каталоге есть вымышленное исследование `demo-study`; оно не содержит научных данных. Мок не подключён к PostgreSQL: `/health` честно возвращает 503. Настоящий импорт, миграции и AI ещё не реализованы.

## Запуск

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Интерактивный контракт: http://127.0.0.1:8000/docs. Целевая схема БД и полный контракт, включая P1 и импорт, зафиксированы в [архитектуре](docs/ARCHITECTURE.md) и [спецификации API](docs/API_SPEC.md). Реализованы маршруты P0 каталога, datasets и чата; чат возвращает `insufficient_evidence`. `/health` начинает возвращать успех только после реализации проверки реальной БД.

## Схема PostgreSQL

Задайте `DATABASE_URL` с драйвером asyncpg, например `postgresql+asyncpg://user:password@localhost:5432/ignis`, затем выполните `alembic upgrade head`. Для отката: `alembic downgrade base`. API пока продолжает использовать моковые данные и не подключается к этой схеме.

Миграция создаёт таблицы studies, sources, findings, datasets, media и relations. Принадлежность источника одной из сторон relation проверяется будущим импортёром. Таблица chunks и расширение pgvector будут добавлены отдельной миграцией после согласования модели и размерности эмбеддингов.
