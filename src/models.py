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