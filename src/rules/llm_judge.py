from __future__ import annotations

import json
import logging
import re

from ..models import Claim, Draft
from .models import ComplianceFlag, Severity

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.1:8b"

JUDGE_SYSTEM = """You are a pharmaceutical regulatory reviewer. You check \
promotional content against an approved claim set.

You will be given APPROVED CLAIMS and DRAFT CONTENT. Find only these four \
categories of problem:

1. UNSUPPORTED - a factual statement in the draft that no approved claim \
supports. Rephrasing an approved claim is acceptable; adding information is not.
2. DISTORTED - a claim whose meaning, strength, or scope has been changed. \
Example: "reduces risk" becoming "eliminates risk", or a claim limited to one \
patient population being stated generally.
3. MISSING_RISK - the draft presents benefits, and risk information exists in \
the approved claims, but the draft body does not actually communicate that risk \
information to the reader.
4. IMPLIED_OFF_LABEL - the draft suggests a use, population, or benefit outside \
the approved claims, even indirectly.

Do NOT report: tone, style, word choice, grammar, length, or formatting. \
Do NOT report a problem you cannot point to specific text for.

Respond with ONLY this JSON object and nothing else:
{"findings": [{"category": "<one of the four>", "severity": "blocker", \
"explanation": "<one sentence for a human reviewer>", "evidence": "<the exact \
text from the draft>"}]}

Use severity "blocker" for UNSUPPORTED, DISTORTED, and IMPLIED_OFF_LABEL. \
Use "warning" for MISSING_RISK.
If you find no problems, respond with {"findings": []}."""

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class LLMJudgeRule:
    rule_id = "LLM_JUDGE"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        on_error: Severity = Severity.WARNING,
        max_severity: Severity = Severity.BLOCKER,
    ) -> None:
        self._model_name = model
        self._on_error = on_error
        self._max_severity = max_severity
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_ollama import ChatOllama

            self._llm = ChatOllama(
                model=self._model_name,
                temperature=0,
                format="json",
            )
        return self._llm

    def check(self, draft: Draft, claims: list[Claim]) -> list[ComplianceFlag]:
        prompt = self._build_prompt(draft, claims)

        try:
            response = self._get_llm().invoke(
                [
                    ("system", JUDGE_SYSTEM),
                    ("human", prompt),
                ]
            )
            raw = response.content
        except Exception:
            logger.exception("LLM judge could not reach model %s", self._model_name)
            return [
                ComplianceFlag(
                    rule_id=self.rule_id,
                    severity=self._on_error,
                    message="Semantic review did not run - the language model was "
                    "unavailable. Deterministic checks completed normally.",
                    suggestion="A human must read this draft against the approved "
                    "claims manually, or retry once the model is available.",
                )
            ]

        return self._parse(raw)

    def _build_prompt(self, draft: Draft, claims: list[Claim]) -> str:
        claim_lines = "\n".join(f"- [{c.id}] {c.text}" for c in claims)
        subject_line = f"SUBJECT: {draft.subject}\n" if draft.subject else ""
        return (
            f"APPROVED CLAIMS:\n{claim_lines}\n\n"
            f"DRAFT CONTENT:\n{subject_line}BODY: {draft.body}"
        )

    def _parse(self, raw: str) -> list[ComplianceFlag]:
        cleaned = _FENCE.sub("", raw).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("LLM judge returned unparseable output: %r", cleaned[:200])
            return [
                ComplianceFlag(
                    rule_id=self.rule_id,
                    severity=self._on_error,
                    message="Semantic review returned malformed output and could "
                    "not be interpreted.",
                    suggestion="Retry, or review this draft manually.",
                )
            ]

        findings = payload.get("findings", []) if isinstance(payload, dict) else []
        if not isinstance(findings, list):
            return []

        flags: list[ComplianceFlag] = []
        for item in findings:
            if not isinstance(item, dict):
                continue
            explanation = str(item.get("explanation", "")).strip()
            if not explanation:
                continue
            category = str(item.get("category", "UNSPECIFIED")).strip()
            flags.append(
                ComplianceFlag(
                    rule_id=self.rule_id,
                    severity=self._coerce_severity(item.get("severity")),
                    message=f"{category}: {explanation}",
                    evidence=self._clean_evidence(item.get("evidence")),
                    suggestion="Confirm against the cited approved claim, or "
                    "remove the statement.",
                )
            )
        return flags

    def _coerce_severity(self, value) -> Severity:
        try:
            severity = Severity(str(value).strip().lower())
        except ValueError:
            severity = Severity.WARNING

        order = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.INFO: 2}
        if order[severity] < order[self._max_severity]:
            return self._max_severity
        return severity

    @staticmethod
    def _clean_evidence(value) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text[:300] if text else None