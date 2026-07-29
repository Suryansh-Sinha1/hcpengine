from __future__ import annotations

import re

from ..models import Claim, ClaimType, Draft
from .models import ComplianceFlag, Severity


BANNED_TERMS: dict[str, str] = {
    "safest": "absolute safety claim",
    "safe": "unqualified safety claim",
    "best": "unsubstantiated superiority claim",
    "most effective": "unsubstantiated superiority claim",
    "superior": "comparative claim requiring head-to-head evidence",
    "breakthrough": "promotional exaggeration",
    "miracle": "promotional exaggeration",
    "guaranteed": "absolute outcome claim",
    "cure": "absolute outcome claim",
    "no side effects": "false safety claim",
    "well tolerated": "safety claim requiring substantiation",
    "proven": "requires explicit evidence citation",
}


class BannedTermRule:
    rule_id = "BANNED_TERM"

    def __init__(self) -> None:
        self._patterns = {
            term: re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            for term in BANNED_TERMS
        }

    def check(self, draft: Draft, claims: list[Claim]) -> list[ComplianceFlag]:
        haystack = f"{draft.subject or ''} {draft.body}"
        flags: list[ComplianceFlag] = []

        for term, reason in BANNED_TERMS.items():
            for match in self._patterns[term].finditer(haystack):
                flags.append(
                    ComplianceFlag(
                        rule_id=self.rule_id,
                        severity=Severity.BLOCKER,
                        message=f"Contains '{match.group()}' - {reason}.",
                        evidence=self._context(haystack, match),
                        suggestion=f"Remove '{match.group()}' or replace it with "
                        "wording taken directly from an approved claim.",
                    )
                )
        return flags

    @staticmethod
    def _context(text: str, match: re.Match, window: int = 40) -> str:
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"


class UnverifiedClaimRule:
    rule_id = "UNVERIFIED_CLAIM"

    def __init__(self, severity: Severity = Severity.WARNING) -> None:
        self.severity = severity

    def check(self, draft: Draft, claims: list[Claim]) -> list[ComplianceFlag]:
        by_id = {c.id: c for c in claims}
        flags: list[ComplianceFlag] = []

        for claim_id in draft.claim_ids_used:
            claim = by_id.get(claim_id)
            if claim is None:
                flags.append(
                    ComplianceFlag(
                        rule_id=self.rule_id,
                        severity=Severity.BLOCKER,
                        message=f"Cites claim '{claim_id}', which is not in the "
                        "approved claim set.",
                        suggestion="Regenerate. The model may have invented this claim.",
                    )
                )
            elif not claim.verified:
                flags.append(
                    ComplianceFlag(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"Claim '{claim_id}' has not been human-verified "
                        f"against {claim.reference.source}.",
                        evidence=claim.text,
                        suggestion="A reviewer must confirm this claim against the "
                        "source document before approval.",
                    )
                )
        return flags


class FairBalanceRule:
    rule_id = "FAIR_BALANCE"

    def check(self, draft: Draft, claims: list[Claim]) -> list[ComplianceFlag]:
        by_id = {c.id: c for c in claims}
        cited = [by_id[cid] for cid in draft.claim_ids_used if cid in by_id]

        benefits = [c for c in cited if c.claim_type.is_benefit_side]
        risks = [c for c in cited if c.claim_type.is_risk_side]

        if not benefits:
            return []

        if not risks:
            return [
                ComplianceFlag(
                    rule_id=self.rule_id,
                    severity=Severity.BLOCKER,
                    message="Content presents benefits but cites no risk "
                    "information. Fair balance is required.",
                    suggestion="Include safety, warning, or contraindication "
                    "claims alongside the benefit claims.",
                )
            ]

        boxed = [c for c in risks if "BOXED WARNING" in c.reference.section.upper()]
        available_boxed = [
            c
            for c in claims
            if c.claim_type is ClaimType.WARNING
            and "BOXED WARNING" in c.reference.section.upper()
        ]
        if available_boxed and not boxed:
            return [
                ComplianceFlag(
                    rule_id=self.rule_id,
                    severity=Severity.BLOCKER,
                    message="This product has boxed warnings, but none are cited "
                    "in the content.",
                    evidence=available_boxed[0].text,
                    suggestion="Boxed warnings must appear in promotional content "
                    "making benefit claims.",
                )
            ]

        return []