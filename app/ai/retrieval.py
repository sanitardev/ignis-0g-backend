from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

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
      AND (c.metadata ->> 'index_revision') = :revision
      AND (CAST(:scope_slug AS text) IS NULL OR st.slug = :scope_slug)
"""

_HAS_CHUNKS = text("SELECT EXISTS (SELECT 1 " + _CURRENT_CHUNKS + ")")
_SEARCH = text("""
    SELECT c.id AS chunk_id, s.id AS source_id, st.slug AS study_slug,
           s.title, s.url, c.content AS excerpt, c.metadata ->> 'locator' AS locator
""" + _CURRENT_CHUNKS + """
    ORDER BY c.embedding <=> CAST(:embedding AS vector),
             (st.slug = CAST(:preferred_slug AS text)) DESC NULLS LAST, c.id
    LIMIT :limit
""")


def _filters(request: ChatRequest, revision: str) -> dict:
    return {
        "scope_slug": request.study_id if request.scope == "study" else None,
        "revision": revision,
    }


class PgVectorRepository:
    async def has_chunks(self, request: ChatRequest, revision: str) -> bool:
        async with session_factory() as session:
            return bool(await session.scalar(_HAS_CHUNKS, _filters(request, revision)))

    async def search(self, request: ChatRequest, vector: str, revision: str, limit: int) -> list[Evidence]:
        async with session_factory() as session:
            rows = await session.execute(_SEARCH, {
                **_filters(request, revision), "preferred_slug": request.study_id,
                "embedding": vector, "limit": limit,
            })
            return [Evidence(**row) for row in rows.mappings()]
