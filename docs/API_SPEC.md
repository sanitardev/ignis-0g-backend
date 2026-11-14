# IGNIS 0G — API Specification v0.1

**Статус:** предлагаемая спецификация MVP · 14.11.2026  
**Base URL:** `/api/v1` (health отдельно: `/health`).  
**Формат:** JSON UTF-8, кроме стандартных `/docs` и `/openapi.json`. Все примеры ниже структурные, не научные данные NASA. `...` в строках — placeholder, не содержимое для публикации.

## 1. Endpoint matrix

| Priority | Method | Route | Response |
|---|---|---|---|
| P0 | GET | `/api/v1/studies` | StudyList |
| P0 | GET | `/api/v1/studies/{study_id}` | StudyDetail |
| P0 | GET | `/api/v1/studies/{study_id}/datasets` | Dataset[] (полные ряды) |
| P0 | GET | `/api/v1/studies/{study_id}/datasets/{dataset_id}` | Dataset |
| P0 | GET | `/api/v1/catalog/filters` | CatalogFilters |
| P0 | POST | `/api/v1/assistant/chat` | ChatResponse |
| P0 | GET | `/health` | Health |
| P1 | GET | `/api/v1/studies/{study_id}/findings` | Finding[] |
| P1 | GET | `/api/v1/studies/{study_id}/sources` | Source[] |
| P1 | GET | `/api/v1/studies/{study_id}/media` | Media[] |
| P1 | GET | `/api/v1/studies/{study_id}/relations` | Relation[] |
| P1 | GET | `/api/v1/nexus/graph` | Graph |
| P1 | POST | `/api/v1/assistant/compare` | CompareResponse |

Все успешные запросы возвращают 200. API read-only для каталога; импорт и индексация через CLI. Вложенные findings/sources/media уже входят в detail, отдельные роуты не нужны для запуска P0. Public `study_id` = slug (`flex`), остальные ID — UUID в JSON. Имена полей snake_case, отсутствующие списки `[]`, неизвестные optional поля `null`. Все поля ответа обязательны по наличию, включая nullable. Никакой глобальной обертки `data`, кроме явно заданных объектов.

## 2. Общие типы (TypeScript для фронта; зеркалировать в Pydantic)

```ts
type UUID = string;
type StudyId = string; // slug: /^[a-z0-9]+(?:-[a-z0-9]+)*$/
type JsonObject = Record<string, unknown>;
type SourceType = 'article' | 'report' | 'webpage' | 'dataset' | 'video' | 'other';

type StudySummary = {
  id: StudyId;
  title: string;
  description: string;
  category: string;
  tags: string[];
  thumbnail_url: string | null;
};
type Source = {
  id: UUID;
  study_id: StudyId;
  title: string;
  url: string;
  source_type: SourceType;
};
type Finding = {
  id: UUID;
  source_id: UUID;
  claim: string;
  evidence: string;
  locator: string | null;
  safety_impact: string | null;
};
type Media = {
  id: UUID;
  source_id: UUID;
  media_type: 'image' | 'video' | 'link';
  url: string;
  caption: string;
};
type SafetyImplication = {
  finding_id: UUID;
  source_id: UUID;
  text: string;
};
type DatasetSummary = {
  id: UUID;
  source_id: UUID;
  title: string;
  chart_type: 'line' | 'scatter' | 'bar';
  locator: string | null;
  notes: string | null;
};
type StudyDetail = StudySummary & {
  methodology: string | null;
  conditions: JsonObject;
  findings: Finding[];
  sources: Source[];
  media: Media[];
  datasets: DatasetSummary[];
  safety_implications: SafetyImplication[];
};
```

`conditions` — свободный JSON для неоднородных условий, отображаемый как пары ключ-значение; не предполагает автоматического сравнения чисел. URL — HTTP(S), проверяем в импорте. Технические поля БД (UUID исследования, хеши, embeddings, полные тексты) не выдаются.

## 3. Catalog

`GET /api/v1/studies?q=flame&category=extinction&tag=microgravity&limit=20&offset=0`

| Query | Default | Validation |
|---|---|---|
| q | отсутствует | max 200, trim; пустая строка игнорируется |
| category | отсутствует | max 80, точное значение |
| tag | отсутствует | max 80, точное значение |
| limit | 20 | 1..100 |
| offset | 0 | >=0 |

```ts
type StudyList = { items: StudySummary[]; total: number; limit: number; offset: number };
type CatalogFilters = { categories: string[]; tags: string[] };
```

```json
{
  "items": [
    {
      "id": "flex",
      "title": "Flame Extinguishment Experiment",
      "description": "...",
      "category": "extinction",
      "tags": ["microgravity"],
      "thumbnail_url": null
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

При отсутствии совпадений — 200 с items=[], total=0; неизвестная категория/tag — тоже пустой результат. Если offset выходит за диапазон, items=[] и total остается фактическим. Поиск и сортировка определены в ARCHITECTURE.md.

`GET /api/v1/catalog/filters` возвращает отсортированные уникальные категории и теги по всему опубликованному каталогу, не только текущей странице: `{"categories":["extinction"],"tags":["microgravity"]}`.

## 4. Study detail

`GET /api/v1/studies/flex` → StudyDetail. Несуществующий study_id → 404.

```json
{
  "id": "flex",
  "title": "Flame Extinguishment Experiment",
  "description": "...",
  "category": "extinction",
  "tags": ["microgravity"],
  "thumbnail_url": null,
  "methodology": null,
  "conditions": {},
  "findings": [],
  "sources": [],
  "media": [],
  "datasets": [],
  "safety_implications": []
}
```

`safety_implications` — проекция findings с непустым safety_impact; соответствует source_id исходного finding. ID источников, на которые ссылаются вложенные данные, присутствуют в `sources`. Вложения P1 возвращают соответствующий массив без обертки; существующее исследование без вложений — 200 `[]`.

## 5. Datasets

`GET /api/v1/studies/{study_id}/datasets` → Dataset[].

`GET /api/v1/studies/{study_id}/datasets/{dataset_id}` → Dataset. Если набор не принадлежит исследованию или отсутствует — 404. Невалидный формат UUID — 422.

```ts
type Dataset = DatasetSummary & {
  x_label: string;
  y_label: string;
  units: { x: string | null; y: string | null };
  series: {
    id: string;
    label: string;
    points: { x: number | string; y: number | null }[];
  }[];
  provenance: 'reported' | 'digitized' | 'derived';
};
```

Правила: для line/scatter x числовой; для bar x может быть строкой или числом (тип одинаков внутри набора); y числовой или null (пропуск). Все числа конечные. Для line точки отсортированы по x; единицы/измеряемые величины одинаковы между сериями; при разных единицах — отдельные наборы. `provenance` описывает происхождение: reported — из опубликованных данных, digitized — извлечено из графика, derived — вычислено из источника (метод в notes). Для digitized/derived notes обязателен; units null только если безразмерная величина либо единица неизвестна (разъяснить в notes). Для MVP отдавать небольшие наборы (целевой бюджет до 1000 точек на dataset; большие ряды отбирать/агрегировать документированным способом в импорте, оригинал сохранять). Пример чисел намеренно отсутствует: реальный набор должен прийти от Руслана.

## 6. Assistant / RAG

`POST /api/v1/assistant/chat`.

```ts
type ChatMessage = { role: 'user' | 'assistant'; content: string };
type ChatRequest = {
  message: string;
  study_id?: StudyId | null;
  history?: ChatMessage[];
  scope?: 'study' | 'global';
};
type Citation = {
  chunk_id: UUID;
  source_id: UUID;
  title: string;
  url: string;
  excerpt: string;
  locator: string | null;
};
type ChatResponse = {
  status: 'answered' | 'insufficient_evidence';
  answer: string;
  citations: Citation[];
  related_study_ids: StudyId[];
  suggested_questions: string[];
};
```

Defaults: history=[], study_id=null; scope=study при study_id, иначе global. `scope=study` без study_id → 422; переданный неизвестный study_id в любом scope → 404. message и history.content: trim, 1..2000 символов; history до 12 сообщений в хронологическом порядке, без текущего message; history суммарно до 12000 символов. Не принимать role=system/tool. Ответ — Markdown без HTML, фронт безопасно рендерит Markdown, не исполняет HTML. В тексте ссылки `[1]`, `[2]` соответствуют порядку элементов citations.

```json
{
  "message": "Почему пламя меняет форму в микрогравитации?",
  "study_id": "flex",
  "history": [],
  "scope": "study"
}
```

Пример безопасного fallback (200):

```json
{
  "status": "insufficient_evidence",
  "answer": "В доступных источниках недостаточно данных для подтвержденного ответа.",
  "citations": [],
  "related_study_ids": [],
  "suggested_questions": []
}
```

`answered`: citations содержит хотя бы один проверенный чанк; ссылки `[n]` в ответе существуют; все excerpt извлечены из реального текста. `insufficient_evidence` не содержит неподтвержденных научных утверждений, список цитат может быть пуст. 503 — сервис недоступен, 504 — истек срок, 429 — лимит. Никакого стриминга в P0. Клиент может отменить ожидание и повторить вручную; автоматические агрессивные ретраи запрещены.

**Python boundary:** `async def ask(request: ChatRequest) -> ChatResponse` в `app.ai.service`; импорт схем из `app.schemas.assistant`. Мок возвращает этот же тип, не имитируя реальные источники. Ошибки провайдера переводятся в типизированные исключения service layer и далее в HTTP-ошибки. Контракт границы согласовать до написания обоих модулей.

## 7. Compare (P1)

`POST /api/v1/assistant/compare`

```ts
type CompareRequest = { study_ids: StudyId[]; focus?: string | null };
type CompareItem = { text: string; citation_indices: number[] }; // 1-based
// citation_indices ссылаются на citations этого ответа
type CompareResponse = {
  status: 'answered' | 'insufficient_evidence';
  summary: string;
  similarities: CompareItem[];
  differences: CompareItem[];
  limitations: string[];
  citations: Citation[];
};
```

`study_ids` — 2..3 уникальных slug; focus до 300 символов; неизвестный ID → 404, повторения/лимиты → 422. Ограничения научной сопоставимости обязательны, если условия/методы отличаются или неизвестны. Контроль ссылок аналогичен chat. Ошибки провайдера аналогичны chat.

## 8. Nexus (P1)

`GET /api/v1/nexus/graph?study_id=flex&depth=1` → Graph. study_id optional; depth default 1, allowed 1..2 (без study_id глубина не используется). Максимум 50 узлов; неизвестный study_id → 404. Изолированный исследовательский узел допустим; пустой каталог возвращает пустой граф.

```ts
type RelationType = 'supports' | 'contradicts' | 'complements' | 'similar';
type Relation = {
  id: UUID;
  from_study_id: StudyId;
  to_study_id: StudyId;
  relation_type: RelationType;
  explanation: string;
  source_id: UUID;
  source_url: string;
  evidence: { excerpt: string; locator: string | null };
};
type Graph = {
  nodes: { id: StudyId; type: 'study'; label: string }[];
  edges: {
    id: UUID;
    source: StudyId;
    target: StudyId;
    type: RelationType;
    explanation: string;
    source_id: UUID;
    source_url: string;
    evidence: { excerpt: string; locator: string | null };
  }[];
  truncated: boolean;
};
```

Обе стороны edge обязаны присутствовать в nodes. Связи только verified=true, не генерируются при HTTP-запросе. `GET /studies/{study_id}/relations` возвращает все проверенные входящие и исходящие Relation[] в стабильном порядке. Frontend adapter: React Flow node `data.label = label`, edge `data.relationType = type`; не передавать `study`/`supports` как кастомные типы React Flow без их регистрации. Координаты рассчитывает frontend.

## 9. Health, ошибки и HTTP

`GET /health` → 200 `{"status":"ok","database":"ok"}`. При недоступности БД → 503 с общим ErrorResponse, code `DATABASE_UNAVAILABLE`. Health не проверяет LLM.

```ts
type ErrorResponse = {
  error: {
    code: string;
    message: string;
    request_id: string;
    details: { field: string; message: string }[];
  };
};
```

```json
{
  "error": {
    "code": "STUDY_NOT_FOUND",
    "message": "Study not found",
    "request_id": "example-request-id",
    "details": []
  }
}
```

| HTTP | code | Причина |
|---|---|---|
| 404 | STUDY_NOT_FOUND / DATASET_NOT_FOUND / NOT_FOUND | Ресурс отсутствует |
| 413 | PAYLOAD_TOO_LARGE | Превышен лимит тела |
| 422 | VALIDATION_ERROR | Невалидные поля/параметры |
| 429 | RATE_LIMITED | Клиентский лимит или очередь AI |
| 500 | INTERNAL_ERROR | Непредвиденный сбой |
| 503 | DATABASE_UNAVAILABLE / AI_UNAVAILABLE | Зависимость недоступна |
| 504 | AI_TIMEOUT | Генерация не уложилась в timeout |

`X-Request-ID` во всех ответах FastAPI; при 429 `Retry-After` в секундах, если известен срок. Ошибки инфраструктуры/прокси вне FastAPI могут иметь другой формат, фронт должен это учитывать. CORS exposes `X-Request-ID`, `Retry-After`.

## 10. Контракт импорта для Руслана (не HTTP)

Пакет UTF-8 JSON, `schema_version=1`, массив studies и необязательный массив relations. У каждого вложенного объекта стабильный ключ внутри исследования; source_key связывает его с источником. Отсутствующие optional поля получают defaults; прочие обязательны. Для простоты на MVP один source_key на один finding/dataset/media/edge.

```json
{
  "schema_version": 1,
  "studies": [
    {
      "slug": "flex",
      "title": "Flame Extinguishment Experiment",
      "description": "...",
      "methodology": null,
      "category": "extinction",
      "tags": ["microgravity"],
      "conditions": {},
      "thumbnail_url": null,
      "sources": [],
      "findings": [],
      "datasets": [],
      "media": []
    }
  ],
  "relations": []
}
```

| Nested collection | Поля элемента |
|---|---|
| sources | source_key, title, url, source_type, text_content (nullable, очищенный текст) |
| findings | finding_key, source_key, claim, evidence, locator (nullable), safety_impact (nullable) |
| datasets | dataset_key, source_key, title, chart_type, x_label, y_label, units, series, provenance, locator (nullable), notes (nullable) |
| media | media_key, source_key, media_type, url, caption |
| relations (top-level) | from_study_id, to_study_id, relation_type, source_study_id, source_key, explanation, evidence, verified (default false) |

Dataset x_label/y_label/series/provenance сохранять в `datasets.data` JSONB; units отдельно. ID из входного пакета не нужны, генерируются БД/импортером один раз. source_study_id у relation выбирает исследование, которому принадлежит source_key. Стабильные ключи и slug не изменять без согласованной миграции. Валидировать ссылки по текущему пакету + БД; relations импортировать после studies. `verified=true` только после ручной проверки источника человеком. Не импортировать placeholder URL или неподтвержденные числа в production.

## 11. Acceptance tests

| ID | Проверка | Ожидание |
|---|---|---|
| C01 | Пустой каталог, неизвестный фильтр | 200, items=[] |
| C02 | q + category + pagination | Детерминированный порядок, total до пагинации |
| S01 | Существующий / неизвестный slug | 200 / 404 |
| D01 | Dataset с null y | 200, null сохранен |
| D02 | Dataset из чужого study | 404 |
| I01 | Двойной импорт одного пакета | Те же ID и число записей |
| I02 | Сломанный source_key | Ошибка валидации, нет частичной записи |
| A01 | Вопрос по имеющемуся источнику | answered, действительные ссылки |
| A02 | Вопрос без доказательств | insufficient_evidence |
| A03 | scope=study без ID / слишком длинная history | 422 |
| A04 | LLM timeout / недоступность | 504 / 503 |
| A05 | Чат в scope=study | Цитаты только выбранного исследования |
| H01 | PostgreSQL недоступен | /health → 503 |
| N01 (P1) | Nexus | Нет непроверенных/висячих edges |

Спецификация еще не сгенерирована из работающего FastAPI: при реализации Pydantic-модели и OpenAPI должны совпадать с этим документом. Провайдер AI, размерность векторов, реальный seed и точные параметры деплоя еще не подтверждены.
