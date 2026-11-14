"""Create catalog tables.

Embedding chunks require a separately agreed vector dimension.
"""
from alembic import op

revision = '0001_catalog'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("\nCREATE TABLE studies (\n\tid UUID NOT NULL, \n\tslug VARCHAR NOT NULL, \n\ttitle TEXT NOT NULL, \n\tdescription TEXT NOT NULL, \n\tmethodology TEXT, \n\tcategory VARCHAR NOT NULL, \n\ttags TEXT[] DEFAULT '{}'::text[] NOT NULL, \n\tconditions JSONB DEFAULT '{}'::jsonb NOT NULL, \n\tthumbnail_url TEXT, \n\tPRIMARY KEY (id), \n\tUNIQUE (slug)\n)\n\n")
    op.execute('CREATE INDEX ix_studies_category ON studies (category)')
    op.execute('CREATE INDEX ix_studies_tags_gin ON studies USING gin (tags)')
    op.execute("\nCREATE TABLE sources (\n\tid UUID NOT NULL, \n\tstudy_id UUID NOT NULL, \n\tsource_key VARCHAR NOT NULL, \n\ttitle TEXT NOT NULL, \n\turl TEXT NOT NULL, \n\tsource_type VARCHAR NOT NULL, \n\ttext_content TEXT, \n\tcontent_hash VARCHAR, \n\tindexed_hash VARCHAR, \n\tPRIMARY KEY (id), \n\tUNIQUE (study_id, source_key), \n\tUNIQUE (id, study_id), \n\tCONSTRAINT ck_sources_type CHECK (source_type IN ('article','report','webpage','dataset','video','other')), \n\tFOREIGN KEY(study_id) REFERENCES studies (id)\n)\n\n")
    op.execute('CREATE INDEX ix_sources_study_id ON sources (study_id)')
    op.execute("\nCREATE TABLE datasets (\n\tid UUID NOT NULL, \n\tstudy_id UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\tdataset_key VARCHAR NOT NULL, \n\ttitle TEXT NOT NULL, \n\tchart_type VARCHAR NOT NULL, \n\tdata JSONB NOT NULL, \n\tunits JSONB NOT NULL, \n\tlocator TEXT, \n\tnotes TEXT, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_id, study_id) REFERENCES sources (id, study_id), \n\tUNIQUE (study_id, dataset_key), \n\tCONSTRAINT ck_datasets_chart_type CHECK (chart_type IN ('line','scatter','bar')), \n\tFOREIGN KEY(study_id) REFERENCES studies (id)\n)\n\n")
    op.execute('CREATE INDEX ix_datasets_source_id ON datasets (source_id)')
    op.execute('CREATE INDEX ix_datasets_study_id ON datasets (study_id)')
    op.execute('\nCREATE TABLE findings (\n\tid UUID NOT NULL, \n\tstudy_id UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\tfinding_key VARCHAR NOT NULL, \n\tclaim TEXT NOT NULL, \n\tevidence TEXT NOT NULL, \n\tlocator TEXT, \n\tsafety_impact TEXT, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_id, study_id) REFERENCES sources (id, study_id), \n\tUNIQUE (study_id, finding_key), \n\tFOREIGN KEY(study_id) REFERENCES studies (id)\n)\n\n')
    op.execute('CREATE INDEX ix_findings_source_id ON findings (source_id)')
    op.execute('CREATE INDEX ix_findings_study_id ON findings (study_id)')
    op.execute("\nCREATE TABLE media (\n\tid UUID NOT NULL, \n\tstudy_id UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\tmedia_key VARCHAR NOT NULL, \n\tmedia_type VARCHAR NOT NULL, \n\turl TEXT NOT NULL, \n\tcaption TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_id, study_id) REFERENCES sources (id, study_id), \n\tUNIQUE (study_id, media_key), \n\tCONSTRAINT ck_media_type CHECK (media_type IN ('image','video','link')), \n\tFOREIGN KEY(study_id) REFERENCES studies (id)\n)\n\n")
    op.execute('CREATE INDEX ix_media_source_id ON media (source_id)')
    op.execute('CREATE INDEX ix_media_study_id ON media (study_id)')
    op.execute("\nCREATE TABLE relations (\n\tid UUID NOT NULL, \n\tfrom_study_id UUID NOT NULL, \n\tto_study_id UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\trelation_type VARCHAR NOT NULL, \n\texplanation TEXT NOT NULL, \n\tevidence JSONB NOT NULL, \n\tverified BOOLEAN DEFAULT false NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (from_study_id, to_study_id, relation_type), \n\tCONSTRAINT ck_relations_distinct_studies CHECK (from_study_id <> to_study_id), \n\tCONSTRAINT ck_relations_type CHECK (relation_type IN ('supports','contradicts','complements','similar')), \n\tFOREIGN KEY(from_study_id) REFERENCES studies (id), \n\tFOREIGN KEY(to_study_id) REFERENCES studies (id), \n\tFOREIGN KEY(source_id) REFERENCES sources (id)\n)\n\n")
    op.execute('CREATE INDEX ix_relations_from_study_id ON relations (from_study_id)')
    op.execute('CREATE INDEX ix_relations_source_id ON relations (source_id)')
    op.execute('CREATE INDEX ix_relations_to_study_id ON relations (to_study_id)')

def downgrade():
    op.execute('DROP TABLE relations')
    op.execute('DROP TABLE media')
    op.execute('DROP TABLE findings')
    op.execute('DROP TABLE datasets')
    op.execute('DROP TABLE sources')
    op.execute('DROP TABLE studies')
