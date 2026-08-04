from __future__ import annotations

import logging

from ..models import Claim, Draft
from .deterministic import BannedTermRule, FairBalanceRule, UnverifiedClaimRule
from .llm_judge import LLMJudgeRule
from .models import ComplianceFlag, ComplianceReport, Rule, Severity

logger = logging.getLogger(__name__)


class ComplianceEngine:
    def __init__(self, rules: list[Rule]) -> None:
        if not rules:
            raise ValueError("ComplianceEngine requires at least one rule")
        self._rules = rules

    @property
    def rule_ids(self) -> list[str]:
        return [r.rule_id for r in self._rules]

    def check(self, draft: Draft, claims: list[Claim]) -> ComplianceReport:
        flags: list[ComplianceFlag] = []

        for rule in self._rules:
            try:
                flags.extend(rule.check(draft, claims))
            except Exception:
                logger.exception("Rule %s raised during check", rule.rule_id)
                flags.append(
                    ComplianceFlag(
                        rule_id=rule.rule_id,
                        severity=Severity.BLOCKER,
                        message=f"Rule '{rule.rule_id}' failed to run. Content "
                        "cannot be approved until this is resolved.",
                        suggestion="This is a system error, not a content problem. "
                        "Report it to the development team.",
                    )
                )

        flags.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.rule_id))
        return ComplianceReport(flags=flags)


_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.BLOCKER: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


def default_engine(
    *,
    strict_verification: bool = False,
    use_llm_judge: bool = True,
    judge_can_block: bool = False,
    model: str | None = None,
) -> ComplianceEngine:
    rules: list[Rule] = [
        BannedTermRule(),
        UnverifiedClaimRule(
            severity=Severity.BLOCKER if strict_verification else Severity.WARNING
        ),
        FairBalanceRule(),
    ]

    if use_llm_judge:
        judge_ceiling = Severity.BLOCKER if judge_can_block else Severity.WARNING
        rules.append(LLMJudgeRule(model, max_severity=judge_ceiling))

    return ComplianceEngine(rules)