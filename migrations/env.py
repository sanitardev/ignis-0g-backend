import asyncio
import os
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.core.database import async_database_url
from app.models import Base, EmbeddingVector

config = context.config
url = os.environ.get('DATABASE_URL')
if url:
    config.set_main_option('sqlalchemy.url', async_database_url(url).replace('%', '%%'))
target_metadata = Base.metadata

def offline():
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()

def migrate(connection):
    connection.dialect.ischema_names = {**connection.dialect.ischema_names, 'vector': EmbeddingVector}
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

async def online():
    engine = async_engine_from_config(config.get_section(config.config_ini_section), prefix='sqlalchemy.', poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()

if context.is_offline_mode():
    offline()
else:
    asyncio.run(online())
