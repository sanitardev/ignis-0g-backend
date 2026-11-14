from typing import Literal
from uuid import UUID
from pydantic import BaseModel

class StudySummary(BaseModel):
    id: str
    title: str
    description: str
    category: str
    tags: list[str]
    thumbnail_url: str | None

class Source(BaseModel):
    id: UUID
    study_id: str
    title: str
    url: str
    source_type: Literal['article', 'report', 'webpage', 'dataset', 'video', 'other']

class Finding(BaseModel):
    id: UUID
    source_id: UUID
    claim: str
    evidence: str
    locator: str | None
    safety_impact: str | None

class Media(BaseModel):
    id: UUID
    source_id: UUID
    media_type: Literal['image', 'video', 'link']
    url: str
    caption: str

class DatasetSummary(BaseModel):
    id: UUID
    source_id: UUID
    title: str
    chart_type: Literal['line', 'scatter', 'bar']
    locator: str | None
    notes: str | None

class SafetyImplication(BaseModel):
    finding_id: UUID
    source_id: UUID
    text: str

class StudyDetail(StudySummary):
    methodology: str | None
    conditions: dict
    findings: list[Finding]
    sources: list[Source]
    media: list[Media]
    datasets: list[DatasetSummary]
    safety_implications: list[SafetyImplication]

class StudyList(BaseModel):
    items: list[StudySummary]
    total: int
    limit: int
    offset: int

class CatalogFilters(BaseModel):
    categories: list[str]
    tags: list[str]

class Point(BaseModel):
    x: float | str
    y: float | None

class Series(BaseModel):
    id: str
    label: str
    points: list[Point]

class Units(BaseModel):
    x: str | None
    y: str | None

class Dataset(DatasetSummary):
    x_label: str
    y_label: str
    units: Units
    series: list[Series]
    provenance: Literal['reported', 'digitized', 'derived']
