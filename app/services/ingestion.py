from hashlib import sha256
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from app import models as m
from app.core.database import session_factory

async def upsert(session, model, keys, values):
    stmt = insert(model).values(**values)
    updates = {k: getattr(stmt.excluded,k) for k in values if k not in keys}
    return await session.scalar(stmt.on_conflict_do_update(index_elements=keys, set_=updates).returning(model.id))

async def import_package(package, *, dry_run=False, factory=None):
    async with (factory or session_factory)() as session:
        async with session.begin():
            # Serialize imports so reference preflight and upserts see one coherent catalog.
            await session.execute(text('SELECT pg_advisory_xact_lock(49371001)'))
            studies = dict((await session.execute(select(m.Study.slug,m.Study.id))).all())
            sources = dict(((slug,key),id_) for slug,key,id_ in (await session.execute(select(m.Study.slug,m.Source.source_key,m.Source.id).join(m.Source,m.Source.study_id==m.Study.id))).all())
            available_studies = set(studies) | {s.slug for s in package.studies}
            available_sources = set(sources) | {(s.slug,x.source_key) for s in package.studies for x in s.sources}
            for study in package.studies:
                for item in [*study.findings,*study.datasets,*study.media]:
                    if (study.slug,item.source_key) not in available_sources:
                        raise ValueError(f'{study.slug}: unknown source_key {item.source_key}')
            for relation in package.relations:
                if not {relation.from_study_id,relation.to_study_id} <= available_studies:
                    raise ValueError('relation references unknown study')
                if (relation.source_study_id,relation.source_key) not in available_sources:
                    raise ValueError('relation references unknown source')
            if dry_run:
                return
            for study in package.studies:
                values = study.model_dump(mode='json',exclude={'sources','findings','datasets','media'})
                studies[study.slug] = await upsert(session,m.Study,['slug'],values)
                for source in study.sources:
                    values = source.model_dump(mode='json')
                    values['study_id'] = studies[study.slug]
                    values['content_hash'] = sha256(source.text_content.encode()).hexdigest() if source.text_content else None
                    sources[study.slug,source.source_key] = await upsert(session,m.Source,['study_id','source_key'],values)
                for collection,model,key in [('findings',m.Finding,'finding_key'),('datasets',m.Dataset,'dataset_key'),('media',m.Media,'media_key')]:
                    for item in getattr(study,collection):
                        values = item.model_dump(mode='json',exclude={'source_key'})
                        values.update(study_id=studies[study.slug],source_id=sources[study.slug,item.source_key])
                        if collection == 'datasets':
                            values['data'] = {k:values.pop(k) for k in ['x_label','y_label','series','provenance']}
                        await upsert(session,model,['study_id',key],values)
            for relation in package.relations:
                values = relation.model_dump(mode='json',exclude={'source_study_id','source_key'})
                values.update(from_study_id=studies[relation.from_study_id],to_study_id=studies[relation.to_study_id],source_id=sources[relation.source_study_id,relation.source_key])
                await upsert(session,m.Relation,['from_study_id','to_study_id','relation_type'],values)
