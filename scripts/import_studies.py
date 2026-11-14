"""Import a validated JSON package atomically; --dry-run checks DB references only."""
import argparse
import asyncio
import sys
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import engine
from app.schemas.ingestion import Package
from app.services.ingestion import import_package

async def run(args):
    try:
        package = Package.model_validate_json(Path(args.path).read_text(encoding='utf-8'))
        await import_package(package,dry_run=args.dry_run)
        print('Validation successful' if args.dry_run else 'Import committed')
        return 0
    except (ValueError,OSError) as exc:
        print(f'Import rejected: {exc}',file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print('Database operation failed; import was rolled back.',file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--dry-run',action='store_true')
    sys.exit(asyncio.run(run(parser.parse_args())))
