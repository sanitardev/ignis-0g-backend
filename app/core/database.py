import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine(
    os.getenv('DATABASE_URL', 'postgresql+asyncpg://ignis:ignis_local@127.0.0.1:55432/ignis'),
    pool_pre_ping=True, pool_timeout=5,
    connect_args={'timeout': 5, 'command_timeout': 5},
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def lifespan(app):
    yield
    await engine.dispose()
