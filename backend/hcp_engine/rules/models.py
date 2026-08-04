from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field

from ..models import Claim, Draft


class Severity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class ComplianceFlag(BaseModel):
    rule_id: str = Field(description="Which rule fired, e.g. 'SUPERLATIVE'")
    severity: Severity
    message: str = Field(description="Plain-English explanation for the reviewer")
    evidence: str | None = Field(
        default=None, description="The exact offending text, for highlighting"
    )
    suggestion: str | None = Field(
        default=None, description="How to fix it, if we can say"
    )


class ComplianceReport(BaseModel):
    flags: list[ComplianceFlag] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.severity is Severity.BLOCKER for f in self.flags)

    @property
    def blockers(self) -> list[ComplianceFlag]:
        return [f for f in self.flags if f.severity is Severity.BLOCKER]

    def summary(self) -> str:
        if not self.flags:
            return "Passed with no findings."
        counts: dict[str, int] = {}
        for f in self.flags:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
        parts = ", ".join(f"{n} {sev}" for sev, n in sorted(counts.items()))
        return f"{'Passed' if self.passed else 'Blocked'} - {parts}"


class Rule(Protocol):
    rule_id: str

    def check(self, draft: Draft, claims: list[Claim]) -> list[ComplianceFlag]: ...