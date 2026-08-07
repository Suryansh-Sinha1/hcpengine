from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..models import Channel, ClaimType, HCPProfile, SourceType
from ..rules.models import ComplianceFlag


class GenerateRequest(BaseModel):
    drug: str = Field(min_length=1, description="Drug name, e.g. 'apixaban'")
    profile: HCPProfile
    channel: Channel = Channel.EMAIL
    document_id: str | None = Field(
        default=None,
        description="Ground benefit claims in one document only. None = all sources.",
    )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    drug: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class ClaimOut(BaseModel):
    id: str
    drug: str
    text: str
    claim_type: ClaimType
    source: str
    section: str
    source_type: SourceType
    page: int | None = None
    document_id: str | None = None
    verified: bool
    is_risk_side: bool


class SearchHit(BaseModel):
    claim: ClaimOut
    score: float
    matched_terms: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    status: str
    passed: bool
    drug: str
    channel: Channel
    subject: str | None = None
    body: str | None = None
    cited_claims: list[ClaimOut] = Field(default_factory=list)
    flags: list[ComplianceFlag] = Field(default_factory=list)
    attempts: int = 0
    history: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    claims_loaded: int
    drugs: list[str]
    unverified_claims: int
    active_rules: list[str]


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=2000)

    drug: str = Field(min_length=1)
    profile: HCPProfile
    channel: Channel
    subject: str | None = None
    body: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)


class DecisionOut(BaseModel):
    id: str
    created_at: str
    decision: str
    reviewer: str
    note: str | None
    drug: str
    channel: str
    specialty: str
    therapy_area: str
    adoption_stage: str
    subject: str | None
    body: str
    claim_ids: list[str]
    flags_at_decision: list[ComplianceFlag]
    passed_automated: bool


class IngestResponse(BaseModel):
    document_id: str
    drug: str
    source_name: str
    source_type: SourceType
    claims_extracted: int
    claims: list[ClaimOut]


class DocumentOut(BaseModel):
    document_id: str
    drug: str
    source_name: str
    source_type: SourceType
    claim_count: int
    verified_count: int