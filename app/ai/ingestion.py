"""Index source texts imported into the catalog."""
import asyncio
from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy import delete, select, text

from app.ai.embeddings import embed
from app.core.database import session_factory
from app.models import Chunk, Source


def split_text(text: str, *, size: int = 420, overlap: int = 60) -> Iterator[str]:
    if not 0 <= overlap < size:
        raise ValueError("overlap must be nonnegative and smaller than size")

    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + max(overlap + 1, size // 2), end)
            if boundary >= 0:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end == len(text):
            break
        start = end - overlap


_PENDING = Source.content_hash.is_distinct_from(Source.indexed_hash)

_INSERT = text("""
    INSERT INTO chunks (id, source_id, chunk_index, content, metadata, embedding)
    VALUES (:id, :source_id, :chunk_index, :content, '{}', CAST(:embedding AS vector))
""")


async def index_sources() -> int:
    async with session_factory() as session:
        source_ids = (await session.scalars(select(Source.id).where(_PENDING))).all()

    indexed = 0
    for source_id in source_ids:
        async with session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None or source.content_hash == source.indexed_hash:
                continue
            original_text = source.text_content
            original_hash = source.content_hash

        chunks = list(split_text(original_text or ""))
        vectors = await asyncio.to_thread(embed, chunks) if chunks else []
        async with session_factory.begin() as session:
            current = await session.get(Source, source_id, with_for_update=True)
            if (
                current is None
                or current.text_content != original_text
                or current.content_hash != original_hash
                or current.indexed_hash == original_hash
            ):
                continue
            await session.execute(delete(Chunk).where(Chunk.source_id == source_id))
            if chunks:
                await session.execute(_INSERT, [
                    {"id": uuid4(), "source_id": source_id, "chunk_index": index,
                     "content": chunk, "embedding": vector}
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                ])
            current.indexed_hash = original_hash
        indexed += 1
    return indexed
