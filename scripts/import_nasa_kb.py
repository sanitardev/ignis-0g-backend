"""Import local NASA knowledge-base cards through the existing catalog importer."""
import argparse
import asyncio
import json
import re
from pathlib import Path

from app.ai.ingestion import read_document
from app.core.database import engine
from app.schemas.ingestion import Package
from app.services.ingestion import import_package


def load_package(directory: Path) -> Package:
    index = directory / "00_index"
    experiments = json.loads((index / "ignis_master_db.json").read_text(encoding="utf-8"))
    registry = json.loads((index / "sources_registry.json").read_text(encoding="utf-8"))
    registry_by_experiment = {row["sub_experiment"]: row for row in registry}
    cards = {}
    for folder in ("01_experiment_cards", "02_normative_baselines"):
        for path in sorted((directory / folder).rglob("*.md")):
            body = read_document(path)
            frontmatter = re.match(r"\A---\s*\n(.*?)\n---[ \t]*(?:\n|$)", body, re.S)
            identifier = re.search(r"(?m)^id:[ \t]*(\d+)[ \t]*$", frontmatter[1]) if frontmatter else None
            if not identifier or int(identifier[1]) in cards:
                raise ValueError(f"Missing or duplicate card identifier: {path.name}")
            cards[int(identifier[1])] = body

    if set(cards) != {row["id"] for row in experiments}:
        raise ValueError("The master index and Markdown cards contain different identifiers")

    studies = []
    for row in experiments:
        title = row["sub_experiment"]
        source = registry_by_experiment[title]
        if source["source_id"] != row["source_id"]:
            raise ValueError(f"Source mismatch in registry for {title}")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        source_key = f"nasa-kb-card-{row['id']}"
        studies.append({
            "slug": slug, "title": title, "category": row["program"],
            "description": row["key_phenomenon_and_finding"],
            "methodology": row["hardware_and_rack_details"],
            "conditions": row["conditions"],
            "tags": [row["safety_pillar"]],
            "sources": [{
                "source_key": source_key,
                "title": f"NASA KB card: {title} ({source['source_id']})",
                "url": source["ntrs_portal"],
                "source_type": "other",
                "text_content": cards[row["id"]],
            }],
        })

    return Package.model_validate({"schema_version": 1, "studies": studies})


async def run(directory: Path, dry_run: bool):
    package = load_package(directory)
    try:
        await import_package(package, dry_run=dry_run)
        print(f"{'Validated' if dry_run else 'Imported'} {len(package.studies)} study cards")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.directory, args.dry_run))
