from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ClaimType(str, Enum):
    INDICATION = "indication"
    EFFICACY = "efficacy"
    DOSING = "dosing"
    SAFETY = "safety"
    CONTRAINDICATION = "contraindication"
    WARNING = "warning"
    MECHANISM = "mechanism"
    TRIAL_DATA = "trial_data"

    @property
    def is_benefit_side(self) -> bool:
        return self in {
            ClaimType.INDICATION,
            ClaimType.EFFICACY,
            ClaimType.TRIAL_DATA,
            ClaimType.MECHANISM,
        }

    @property
    def is_risk_side(self) -> bool:
        return self in {
            ClaimType.SAFETY,
            ClaimType.CONTRAINDICATION,
            ClaimType.WARNING,
        }


class SourceType(str, Enum):
    """Where a claim came from, which determines what it may be used for.

    Promotional content to physicians must be on-label. A claim extracted from
    a publication may substantiate an on-label statement, but it cannot itself
    license a claim the approved labelling does not make.
    """

    LABEL = "label"
    PUBLICATION = "publication"
    INTERNAL = "internal"

    @property
    def is_promotional_source(self) -> bool:
        return self is SourceType.LABEL


class Reference(BaseModel):
    source: str = Field(description="e.g. 'US Prescribing Information, apixaban'")
    section: str = Field(description="e.g. '1 INDICATIONS AND USAGE'")
    source_type: SourceType = SourceType.LABEL
    url: str | None = None
    citation: str | None = None
    page: int | None = Field(
        default=None, description="Page in the source document, if ingested"
    )
    document_id: str | None = Field(
        default=None, description="Groups claims extracted from one upload"
    )


class Claim(BaseModel):
    id: str
    drug: str
    text: str
    claim_type: ClaimType
    reference: Reference
    verified: bool = Field(default=False)
    specialties: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("text")
    @classmethod
    def _non_trivial(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("Claim text is too short to be meaningful")
        return v.strip()

    def searchable_text(self) -> str:
        return f"{self.text} {self.claim_type.value} {' '.join(self.specialties)}"

    @property
    def is_promotional_source(self) -> bool:
        return self.reference.source_type.is_promotional_source


class RetrievedClaim(BaseModel):
    claim: Claim
    score: float


class HCPProfile(BaseModel):
    specialty: str
    therapy_area: str
    adoption_stage: Literal[
        "unaware", "aware", "evaluating", "occasional_prescriber", "advocate"
    ] = "aware"
    notes: str | None = None


class Channel(str, Enum):
    EMAIL = "email"
    DETAIL_AID = "detail_aid"
    FOLLOW_UP = "follow_up"


class Draft(BaseModel):
    drug: str
    channel: Channel
    subject: str | None = None
    body: str
    claim_ids_used: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _email_requires_subject(self):
        if self.channel is Channel.EMAIL and not self.subject:
            raise ValueError("Email drafts must include a subject line")
        return self