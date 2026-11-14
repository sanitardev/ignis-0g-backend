import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from app.ai.embeddings import embed
from app.ai.llm import ProviderUnavailable
from app.core.database import session_factory
from app.schemas.assistant import ChatRequest


@dataclass(frozen=True)
class Evidence:
    chunk_id: UUID
    source_id: UUID
    study_slug: str
    title: str
    url: str
    excerpt: str
    locator: str | None


_CURRENT_CHUNKS = """
    FROM chunks AS c
    JOIN sources AS s ON s.id = c.source_id
    JOIN studies AS st ON st.id = s.study_id
    WHERE s.indexed_hash = s.content_hash
      AND (CAST(:scope_slug AS text) IS NULL OR st.slug = :scope_slug)
"""

_HAS_CHUNKS = text("SELECT EXISTS (SELECT 1 " + _CURRENT_CHUNKS + ")")

_SEARCH = text("""
    SELECT c.id AS chunk_id, s.id AS source_id, st.slug AS study_slug,
           s.title, s.url, c.content AS excerpt, c.metadata ->> 'locator' AS locator
""" + _CURRENT_CHUNKS + """
    ORDER BY (c.embedding <=> CAST(:embedding AS vector))
             - CASE WHEN st.slug = CAST(:preferred_slug AS text) THEN 0.03 ELSE 0 END,
             c.id
    LIMIT 6
""")


async def retrieve(request: ChatRequest) -> list[Evidence]:
    filters = {"scope_slug": request.study_id if request.scope == "study" else None}
    async with session_factory() as session:
        if not await session.scalar(_HAS_CHUNKS, filters):
            return []

    # Previous user questions provide terms for short follow-ups.
    previous = [item.content for item in request.history if item.role == "user"]
    query = "\n".join([request.message, *reversed(previous[-2:])])
    try:
        embedding, = await asyncio.to_thread(embed, [query])
    except Exception:
        raise ProviderUnavailable from None

    async with session_factory() as session:
        rows = await session.execute(
            _SEARCH, {**filters, "preferred_slug": request.study_id, "embedding": embedding}
        )
        return [Evidence(**row) for row in rows.mappings()]
