from sqlalchemy import select, or_
from sqlalchemy.orm import aliased
from app.models import Study, Source, Relation as RelationRow
from app.repositories import catalog
from app.schemas.nexus import Relation, Node, Edge, Graph

async def load_relations(session, study_uuid=None):
    origin, target = aliased(Study), aliased(Study)
    query = select(RelationRow, origin.slug, target.slug, Source.url).join(origin, origin.id == RelationRow.from_study_id).join(target, target.id == RelationRow.to_study_id).join(Source, Source.id == RelationRow.source_id).where(RelationRow.verified.is_(True)).order_by(origin.slug, target.slug, RelationRow.id)
    if study_uuid is not None:
        query = query.where(or_(RelationRow.from_study_id == study_uuid, RelationRow.to_study_id == study_uuid))
    return [Relation(id=r.id, from_study_id=a, to_study_id=b, relation_type=r.relation_type, explanation=r.explanation, source_id=r.source_id, source_url=url, evidence=r.evidence) for r,a,b,url in (await session.execute(query)).all()]

async def relations(slug):
    async with catalog.session_factory() as session:
        study = await catalog.find_study(session, slug)
        return await load_relations(session, study.id)

async def graph(slug=None, depth=1):
    async with catalog.session_factory() as session:
        if slug:
            await catalog.find_study(session, slug)
        studies = dict((await session.execute(select(Study.slug,Study.title).order_by(Study.slug))).all())
        links = await load_relations(session)
    truncated = False
    if slug is None:
        selected = set(list(studies)[:50])
        truncated = len(studies) > 50
    else:
        selected, frontier = {slug}, {slug}
        for _ in range(depth):
            neighbors = set()
            for link in links:
                if link.from_study_id in frontier: neighbors.add(link.to_study_id)
                if link.to_study_id in frontier: neighbors.add(link.from_study_id)
            candidates = sorted(neighbors - selected)
            room = 50 - len(selected)
            truncated |= len(candidates) > room
            frontier = set(candidates[:room])
            selected.update(frontier)
    edges = [Edge(id=r.id, source=r.from_study_id, target=r.to_study_id, type=r.relation_type, explanation=r.explanation, source_id=r.source_id, source_url=r.source_url, evidence=r.evidence) for r in links if r.from_study_id in selected and r.to_study_id in selected]
    return Graph(nodes=[Node(id=id_,label=studies[id_]) for id_ in sorted(selected)],edges=edges,truncated=truncated)
