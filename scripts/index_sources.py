import asyncio

from app.ai.ingestion import index_sources
from app.core.database import engine


async def main():
    try:
        print(f"Indexed sources: {await index_sources()}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
