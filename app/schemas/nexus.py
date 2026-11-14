from typing import Literal
from uuid import UUID
from pydantic import BaseModel

RelationType = Literal['supports', 'contradicts', 'complements', 'similar']

class Evidence(BaseModel):
    excerpt: str
    locator: str | None

class Relation(BaseModel):
    id: UUID
    from_study_id: str
    to_study_id: str
    relation_type: RelationType
    explanation: str
    source_id: UUID
    source_url: str
    evidence: Evidence

class Node(BaseModel):
    id: str
    type: Literal['study'] = 'study'
    label: str

class Edge(BaseModel):
    id: UUID
    source: str
    target: str
    type: RelationType
    explanation: str
    source_id: UUID
    source_url: str
    evidence: Evidence

class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    truncated: bool
