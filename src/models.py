from pydantic import BaseModel, Field, field_validator

from __future__ import annotations

from enum import Enum
from typing import Literal

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

class Reference(BaseModel):
    source: str = Field(description="e.g. 'US Prescribing Information, apixaban'")
    section: str = Field(description="e.g. '1 INDICATIONS AND USAGE'")
    url: str | None = None
    citation: str | None = None 

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

class HCPProfile(BaseModel):
    specialty: str
    therapy_area: str
    adoption_stage: Literal["unaware", "aware", "evaluating", "occasional_prescriber", "advocate"] = "aware"
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

