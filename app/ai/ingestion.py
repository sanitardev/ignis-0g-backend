"""Extract and index source documents stored in the existing catalog."""
import asyncio
import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import tiktoken
from pypdf import PdfReader
from sqlalchemy import delete, select, text

from app.ai.embeddings import vector_parameter
from app.ai.providers import EmbeddingProvider, ProviderUnavailable
from app.ai.settings import RagSettings
from app.core.database import session_factory
from app.models import Chunk, Source, Study


@dataclass(frozen=True)
class DocumentChunk:
    content: str
    page: int | None
    section: str | None


@lru_cache(maxsize=1)
def tokenizer():
    return tiktoken.get_encoding("cl100k_base")


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = [page.extract_text() or "" for page in PdfReader(path).pages]
        if not any(page.strip() for page in pages):
            raise ValueError(f"{path.name} has no embedded text")
        return "\f".join(pages) + "\f"
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8-sig")
    raise ValueError(f"Unsupported document extension: {suffix}")


def _sections(page: str) -> Iterator[tuple[str | None, str]]:
    path = {}
    lines = []
    for line in page.splitlines():
        header = re.fullmatch(r" {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*", line)
        if header:
            yield " / ".join(path.values()) or None, "\n".join(lines)
            depth = len(header[1])
            path = {level: label for level, label in path.items() if level < depth}
            path[depth] = header[2]
            lines = []
        else:
            lines.append(line)
    yield " / ".join(path.values()) or None, "\n".join(lines)


def document_chunks(content: str, settings: RagSettings) -> Iterator[DocumentChunk]:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|$)", "", content, count=1, flags=re.S)
    content = re.sub(r"<!--[\s\S]*?-->|[\x00-\x08\x0b\x0e-\x1f\x7f\u00ad\u200b\ufeff]", "", content)
    encoding = tokenizer()
    pages = content.split("\f")
    for page, content_page in enumerate(pages, 1):
        for section, body in _sections(content_page):
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            if not body:
                continue

            ids = encoding.encode_ordinary(body)
            _, offsets = encoding.decode_with_offsets(ids)
            offsets.append(len(body))
            start = 0
            while start < len(ids):
                end = min(start + settings.chunk_tokens, len(ids))
                if end < len(ids):
                    # Prefer paragraph and sentence boundaries in the latter half of the window.
                    lower = start + max(settings.chunk_overlap + 1, settings.chunk_tokens // 2)
                    for cut in range(end, lower - 1, -1):
                        offset = offsets[cut]
                        if body[max(0, offset - 2):offset] == "\n\n" or (
                            offset and body[offset - 1] in ".!?" and body[offset:offset + 1].isspace()
                        ):
                            end = cut
                            break
                excerpt = body[offsets[start]:offsets[end]].strip()
                if excerpt:
                    yield DocumentChunk(excerpt, page if len(pages) > 1 else None, section)
                if end == len(ids):
                    break
                start = end - settings.chunk_overlap


def index_revision(embedding: EmbeddingProvider, settings: RagSettings) -> str:
    spec = ["document-v2-cl100k_base", embedding.model_id, settings.chunk_tokens, settings.chunk_overlap]
    return hashlib.sha256(json.dumps(spec).encode()).hexdigest()


_INSERT = text("""
    INSERT INTO chunks (id, source_id, chunk_index, content, metadata, embedding)
    VALUES (:id, :source_id, :chunk_index, :content, CAST(:metadata AS jsonb),
            CAST(:embedding AS vector))
""")

_STALE_INDEX = text("""
    SELECT EXISTS (
        SELECT 1 FROM chunks
        WHERE source_id = :source_id
          AND (metadata ->> 'index_revision') IS DISTINCT FROM :revision
    )
""")


async def index_sources(embedding: EmbeddingProvider, settings: RagSettings) -> int:
    revision = index_revision(embedding, settings)
    async with session_factory() as session:
        sources = (await session.execute(select(Source.id, Study.slug).join(
            Study, Source.study_id == Study.id
        ).order_by(Source.id))).all()

    indexed = 0
    for source_id, study_slug in sources:
        async with session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None or (
                source.content_hash == source.indexed_hash
                and not await session.scalar(_STALE_INDEX, {"source_id": source_id, "revision": revision})
            ):
                continue
            original_text, original_hash = source.text_content, source.content_hash

        chunks = await asyncio.to_thread(lambda: list(document_chunks(original_text, settings))) if original_text else []
        rows = []
        for start in range(0, len(chunks), settings.batch_size):
            batch = chunks[start:start + settings.batch_size]
            vectors = await embedding.embed_documents([item.content for item in batch])
            if len(vectors) != len(batch):
                raise ProviderUnavailable("Embedding count differs from the batch size")
            for index, (item, vector) in enumerate(zip(batch, vectors, strict=True), start):
                locator = " · ".join(filter(None, [f"p. {item.page}" if item.page else None, item.section]))
                rows.append({
                    "id": uuid4(), "source_id": source_id, "chunk_index": index,
                    "content": item.content, "embedding": vector_parameter(vector),
                    "metadata": json.dumps({
                        "source_id": str(source_id), "study_id": study_slug,
                        "page": item.page, "section": item.section, "locator": locator or None,
                        "index_revision": revision,
                    }),
                })

        async with session_factory.begin() as session:
            current = await session.get(Source, source_id, with_for_update=True)
            if (
                current is None or current.text_content != original_text or current.content_hash != original_hash
                or (current.indexed_hash == original_hash and not await session.scalar(
                    _STALE_INDEX, {"source_id": source_id, "revision": revision}
                ))
            ):
                continue
            await session.execute(delete(Chunk).where(Chunk.source_id == source_id))
            if rows:
                await session.execute(_INSERT, rows)
            current.indexed_hash = original_hash
        indexed += 1
    return indexed
