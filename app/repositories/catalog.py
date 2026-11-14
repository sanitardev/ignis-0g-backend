from fastapi import HTTPException
from sqlalchemy import select, func, case, or_, any_
from app.core.database import session_factory
from app import models as m
from app.schemas import study as s


def summary(row):
    return s.StudySummary(id=row.slug, title=row.title, description=row.description, category=row.category, tags=row.tags, thumbnail_url=row.thumbnail_url)

async def find_study(session, slug):
    row = await session.scalar(select(m.Study).where(m.Study.slug == slug))
    if row is None:
        raise HTTPException(404, ('STUDY_NOT_FOUND', 'Study not found'))
    return row

async def require_study(slug):
    async with session_factory() as session:
        await find_study(session, slug)

async def catalog(q, category, tag, limit, offset):
    conditions = []
    order = []
    q = (q or '').strip()
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        matches = [m.Study.title.ilike(pattern, escape='\\'), func.array_to_string(m.Study.tags, ' ').ilike(pattern, escape='\\'), m.Study.description.ilike(pattern, escape='\\'), select(m.Finding.id).where(m.Finding.study_id == m.Study.id, m.Finding.claim.ilike(pattern, escape='\\')).exists()]
        conditions.append(or_(*matches))
        order.append(case(*[(match, i) for i, match in enumerate(matches)], else_=4))
    if category is not None:
        conditions.append(m.Study.category == category)
    if tag is not None:
        conditions.append(tag == any_(m.Study.tags))
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(m.Study).where(*conditions))
        rows = await session.scalars(select(m.Study).where(*conditions).order_by(*order, m.Study.title, m.Study.slug).limit(limit).offset(offset))
        return s.StudyList(items=[summary(row) for row in rows], total=total, limit=limit, offset=offset)

async def filters():
    async with session_factory() as session:
        categories = list(await session.scalars(select(m.Study.category).distinct().order_by(m.Study.category)))
        tags = list(await session.scalars(select(func.unnest(m.Study.tags)).distinct().order_by(func.unnest(m.Study.tags))))
        return s.CatalogFilters(categories=categories, tags=tags)

async def detail(slug):
    async with session_factory() as session:
        row = await find_study(session, slug)
        async def children(model, schema):
            rows = await session.scalars(select(model).where(model.study_id == row.id).order_by(model.id))
            return [schema.model_validate(item, from_attributes=True) for item in rows]
        sources = await session.scalars(select(m.Source).where(m.Source.study_id == row.id).order_by(m.Source.id))
        sources = [s.Source(id=x.id, study_id=slug, title=x.title, url=x.url, source_type=x.source_type) for x in sources]
        findings = await children(m.Finding, s.Finding)
        return s.StudyDetail(**summary(row).model_dump(), methodology=row.methodology, conditions=row.conditions, sources=sources, findings=findings, media=await children(m.Media, s.Media), datasets=await children(m.Dataset, s.DatasetSummary), safety_implications=[s.SafetyImplication(finding_id=f.id, source_id=f.source_id, text=f.safety_impact) for f in findings if f.safety_impact])

async def datasets(slug, dataset_id=None):
    async with session_factory() as session:
        study = await find_study(session, slug)
        query = select(m.Dataset).where(m.Dataset.study_id == study.id).order_by(m.Dataset.id)
        if dataset_id is not None:
            query = query.where(m.Dataset.id == dataset_id)
        rows = list(await session.scalars(query))
        if dataset_id is not None and not rows:
            raise HTTPException(404, ('DATASET_NOT_FOUND', 'Dataset not found'))
        result = [s.Dataset(**s.DatasetSummary.model_validate(row, from_attributes=True).model_dump(), units=row.units, **row.data) for row in rows]
        return result[0] if dataset_id is not None else result
