import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.models import Chunk, Source, Study


def test_chunks_constraints_and_cosine_search():
    async def run():
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    async with AsyncSession(connection) as session:
                        study = Study(slug=f'chunk-test-{uuid4().hex}', title='Test', description='Synthetic', category='test')
                        session.add(study)
                        await session.flush()
                        source = Source(study_id=study.id, source_key='test', title='Test', url='https://example.com', source_type='other')
                        session.add(source)
                        await session.flush()
                        source_id = source.id
                        session.add_all([
                            Chunk(source_id=source_id, chunk_index=0, content='first', embedding=[1, 0]),
                            Chunk(source_id=source_id, chunk_index=1, content='second', embedding=[0, 1]),
                        ])
                        await session.flush()
                        query = select(Chunk.content).where(Chunk.source_id == source_id).order_by(Chunk.embedding.cosine_distance([1, 0]))
                        assert list(await session.scalars(query)) == ['first', 'second']
                        for index, ref in [(0, source_id), (-1, source_id), (0, uuid4())]:
                            with pytest.raises(IntegrityError):
                                async with session.begin_nested():
                                    session.add(Chunk(source_id=ref, chunk_index=index, content='invalid', embedding=[1, 0]))
                                    await session.flush()
                        await session.execute(delete(Source).where(Source.id == source_id))
                        assert list(await session.scalars(query)) == []
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())
