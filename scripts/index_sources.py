import argparse
import asyncio
import sys

from app.ai.embeddings import vector_parameter
from app.ai.ingestion import index_sources
from app.ai.providers import ProviderUnavailable
from app.ai.settings import settings_from_env
from app.ai.wiring import configured_providers
from app.core.database import engine


async def main(check_provider: bool) -> int:
    try:
        settings = settings_from_env()
        async with configured_providers(settings) as (embedding, _, __):
            if check_provider:
                vector_parameter(await embedding.embed_query("Synthetic embedding dimension check"))
                print("Embedding provider returned a valid 384-dimensional vector")
                return 0
            print(f"Indexed sources: {await index_sources(embedding, settings)}")
        return 0
    except ProviderUnavailable as error:
        print(f"Indexing paused: {error}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index catalog sources using a remote embedding API.")
    parser.add_argument("--check-provider", action="store_true", help="Test dimensions using synthetic text")
    sys.exit(asyncio.run(main(parser.parse_args().check_provider)))
