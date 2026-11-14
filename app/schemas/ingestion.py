"""Versioned local import contract. Scientific verification remains a human task."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[str, StringConstraints(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')]

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Source(Input):
    source_key: Text
    title: Text
    url: HttpUrl
    source_type: Literal['article','report','webpage','dataset','video','other']
    text_content: str | None = None

class Finding(Input):
    finding_key: Text
    source_key: Text
    claim: Text
    evidence: Text
    locator: str | None = None
    safety_impact: str | None = None

class Point(Input):
    x: Annotated[float, Field(strict=True)] | str
    y: Annotated[float, Field(strict=True)] | None

class Series(Input):
    id: Text
    label: Text
    points: list[Point]

class Units(Input):
    x: str | None
    y: str | None

class Dataset(Input):
    dataset_key: Text
    source_key: Text
    title: Text
    chart_type: Literal['line','scatter','bar']
    x_label: Text
    y_label: Text
    units: Units
    series: list[Series]
    provenance: Literal['reported','digitized','derived']
    locator: str | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def check_data(self):
        if (self.provenance != 'reported' or self.units.x is None or self.units.y is None) and not (self.notes or '').strip():
            raise ValueError('notes required for derived/digitized data or unspecified units')
        unique([s.id for s in self.series], 'series id')
        types = set()
        for series in self.series:
            xs = [p.x for p in series.points]
            types.update(type(x) for x in xs)
            if self.chart_type != 'bar' and any(isinstance(x,str) for x in xs):
                raise ValueError('line/scatter x must be numeric')
            if self.chart_type == 'line' and xs != sorted(xs):
                raise ValueError('line points must be sorted by x')
        if len(types) > 1:
            raise ValueError('x type must be uniform across dataset')
        return self

class Media(Input):
    media_key: Text
    source_key: Text
    media_type: Literal['image','video','link']
    url: HttpUrl
    caption: str

class Study(Input):
    slug: Slug
    title: Text
    description: Text
    category: Text
    methodology: str | None = None
    tags: list[str] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)
    thumbnail_url: HttpUrl | None = None
    sources: list[Source] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    datasets: list[Dataset] = Field(default_factory=list)
    media: list[Media] = Field(default_factory=list)

    @model_validator(mode='after')
    def keys(self):
        for collection, key in [('sources','source_key'),('findings','finding_key'),('datasets','dataset_key'),('media','media_key')]:
            unique([getattr(x,key) for x in getattr(self,collection)], key)
        return self

class Evidence(Input):
    excerpt: Text
    locator: str | None = None

class Relation(Input):
    from_study_id: Slug
    to_study_id: Slug
    relation_type: Literal['supports','contradicts','complements','similar']
    source_study_id: Slug
    source_key: Text
    explanation: Text
    evidence: Evidence
    verified: bool = False

    @model_validator(mode='after')
    def endpoints(self):
        if self.from_study_id == self.to_study_id:
            raise ValueError('relation requires different studies')
        if self.source_study_id not in (self.from_study_id, self.to_study_id):
            raise ValueError('relation source must belong to an endpoint')
        return self

def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f'duplicate {label}')

class Package(Input):
    schema_version: Literal[1]
    studies: list[Study]
    relations: list[Relation] = Field(default_factory=list)

    @model_validator(mode='after')
    def keys(self):
        unique([s.slug for s in self.studies], 'study slug')
        unique([(r.from_study_id,r.to_study_id,r.relation_type) for r in self.relations], 'relation')
        return self
