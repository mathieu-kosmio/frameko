"""Modèles Pydantic partagés pour l'API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, HttpUrl


# ── Taxonomie ──────────────────────────────────────────────────────────────


class Domain(BaseModel):
    id: UUID
    slug: str
    label_fr: str
    label_en: str | None = None


class Category(BaseModel):
    id: UUID
    slug: str
    label_fr: str
    label_en: str | None = None
    domain_id: UUID


class Theme(BaseModel):
    id: UUID
    slug: str
    label_fr: str
    label_en: str | None = None
    category_id: UUID


# ── Critères communs ───────────────────────────────────────────────────────


class CommonCriterion(BaseModel):
    id: UUID
    code: str
    label_fr: str
    label_en: str | None = None
    definition: str | None = None
    theme_id: UUID | None = None
    iri: str | None = None
    weight: float = 1.0


# ── Référentiels ───────────────────────────────────────────────────────────


class Framework(BaseModel):
    id: UUID
    slug: str
    title: str
    publisher: str | None = None
    version: str | None = None
    domain_id: UUID | None = None
    type: str | None = None
    jurisdiction: str | None = None
    language: str = "fr"
    status: str = "active"
    iri: str | None = None
    created_at: datetime | None = None


class FrameworkCriterion(BaseModel):
    id: UUID
    framework_id: UUID
    reference: str | None = None
    label: str
    theme_id: UUID | None = None
    level: str | None = None
    iri: str | None = None
    source_excerpt: str | None = None
    is_verbatim_allowed: bool = True


MappingDegree = Literal["equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"]


class Mapping(BaseModel):
    id: UUID
    framework_criterion_id: UUID
    common_criterion_id: UUID
    degree: MappingDegree
    confidence: float = 1.0
    method: str = "manual"
    validated_at: datetime | None = None


# ── Auto-évaluation ────────────────────────────────────────────────────────


AssessmentStatus = Literal["in_progress", "completed", "archived"]
AnswerStatus = Literal["compliant", "partial", "non_compliant", "not_applicable", "pending"]


class AssessmentCreate(BaseModel):
    org_id: UUID
    framework_id: UUID


class AssessmentAnswerUpsert(BaseModel):
    common_criterion_id: UUID
    status: AnswerStatus
    note: str | None = None
    evidence_url: str | None = None


class AssessmentAnswersBatch(BaseModel):
    answers: list[AssessmentAnswerUpsert]


class AssessmentResult(BaseModel):
    assessment_id: UUID
    framework_id: UUID
    score: float
    total_criteria: int
    answered_criteria: int
    compliant: int
    partial: int
    non_compliant: int
    gaps: list[dict]
    cross_coverage: list[dict]


# ── Matching (S2) ──────────────────────────────────────────────────────────


class MatchRequest(BaseModel):
    text: str
    top_k: int = 10
    min_confidence: float = 0.5


class MatchResult(BaseModel):
    common_criterion: CommonCriterion
    similarity: float
    degree: MappingDegree | None = None
    neighbors: list[dict] = []


# ── Ingestion ──────────────────────────────────────────────────────────────


class IngestionJobCreate(BaseModel):
    source_ref: str
    type: Literal["pdf", "spreadsheet", "url", "rdf"]
    framework_slug: str | None = None


class IngestionJob(BaseModel):
    id: UUID
    source_ref: str
    type: str
    status: str
    log: list[dict] = []
    framework_id: UUID | None = None
    created_at: datetime
