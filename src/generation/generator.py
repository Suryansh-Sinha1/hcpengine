from __future__ import annotations

import json
import logging
import re

from ..models import Channel, Claim, Draft, HCPProfile

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:14b-instruct"


CHANNEL_BRIEF: dict[Channel, str] = {
    Channel.EMAIL: (
        "A short email to a physician. 120-180 words. Professional and factual, "
        "not salesy. Include a subject line."
    ),
    Channel.DETAIL_AID: (
        "Copy for a single detail-aid panel a representative shows in person. "
        "60-100 words. Terse, scannable, clinically precise. No subject line."
    ),
    Channel.FOLLOW_UP: (
        "A brief follow-up message after a prior interaction. 80-120 words. "
        "Reference continuity of conversation without inventing specifics."
    ),
}

ADOPTION_BRIEF: dict[str, str] = {
    "unaware": "The reader may not know this product. Lead with the indication.",
    "aware": "The reader knows the product exists but has not evaluated it.",
    "evaluating": "The reader is actively comparing options. Emphasise trial data.",
    "occasional_prescriber": "The reader prescribes occasionally. Focus on dosing.",
    "advocate": "The reader already prescribes regularly. Keep it brief.",
}


SYSTEM_TEMPLATE = """You are a medical copywriter producing promotional content \
for healthcare professionals. You work under strict regulatory constraints.

RULES - these override every other instruction:
1. You may ONLY assert information contained in the APPROVED CLAIMS below. Do \
not add facts from your own knowledge, even if you believe them to be true.
2. Do not state or imply any use, patient population, or benefit that is not in \
the approved claims. Do not broaden a claim's scope.
3. Do not change a claim's strength. "Reduces the risk" must not become \
"eliminates the risk" or "prevents".
4. Do not use these words or any similar: safest, safe, best, most effective, \
superior, breakthrough, miracle, guaranteed, cure, proven, well tolerated.
5. You MUST communicate the RISK INFORMATION in the body text. Citing it is not \
enough - the reader must actually see it.
6. You may rephrase claims for readability, but must not change their clinical \
meaning, strength, or scope.
7. You MUST list the ID of every approved claim you used in claim_ids_used. \
The IDs look like [apx-ind-001]. An empty list is never correct - if you wrote \
any content at all, you used claims. This field is mandatory.

APPROVED CLAIMS - this is the complete set of assertions available to you:
{claims_block}

AUDIENCE: {specialty}, therapy area: {therapy_area}.
{adoption_note}

FORMAT: {channel_brief}

Respond with ONLY this JSON object:
{{"subject": "<subject line, or null if not applicable>", "body": "<the \
content>", "claim_ids_used": ["apx-ind-001", "apx-warn-001"]}}"""


REVISION_TEMPLATE = """Your previous draft was rejected by compliance review.

PREVIOUS DRAFT:
{previous_body}

COMPLIANCE FAILURES - fix every one:
{failures}

Write a new draft that fixes these problems. The rules and approved claims in \
your instructions still apply in full."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class GenerationError(RuntimeError):
    """Raised when model output cannot be parsed or cannot be trusted."""


class ModelUnavailableError(GenerationError):
    """The model could not be reached. Retrying will not help."""


def render_claims_block(claims: list[Claim]) -> str:
    lines: list[str] = []
    for claim in sorted(claims, key=lambda c: c.claim_type.value):
        tag = (
            "RISK INFORMATION"
            if claim.claim_type.is_risk_side
            else claim.claim_type.value.upper()
        )
        lines.append(f"[{claim.id}] ({tag}) {claim.text}")
    return "\n".join(lines)


class DraftGenerator:
    def __init__(self, model: str = DEFAULT_MODEL, *, temperature: float = 0.2) -> None:
        self._model_name = model
        self._temperature = temperature
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_ollama import ChatOllama

            self._llm = ChatOllama(
                model=self._model_name,
                temperature=self._temperature,
                format="json",
            )
        return self._llm

    def generate(
        self,
        claims: list[Claim],
        profile: HCPProfile,
        drug: str,
        channel: Channel = Channel.EMAIL,
        *,
        previous_body: str | None = None,
        failures: list[str] | None = None,
    ) -> Draft:
        if not claims:
            raise GenerationError("Cannot generate content with an empty claim set")

        system = SYSTEM_TEMPLATE.format(
            claims_block=render_claims_block(claims),
            specialty=profile.specialty,
            therapy_area=profile.therapy_area,
            adoption_note=ADOPTION_BRIEF.get(profile.adoption_stage, ""),
            channel_brief=CHANNEL_BRIEF[channel],
        )

        if previous_body and failures:
            user = REVISION_TEMPLATE.format(
                previous_body=previous_body,
                failures="\n".join(f"- {f}" for f in failures),
            )
        else:
            user = (
                f"Write {channel.value.replace('_', ' ')} content about {drug} "
                "for the audience described. Use only the approved claims."
            )

        try:
            response = self._get_llm().invoke([("system", system), ("human", user)])
            raw = response.content
        except Exception as exc:
            raise ModelUnavailableError(f"Language model unavailable: {exc}") from exc

        return self._parse(raw, claims, drug, channel)

    def _parse(
        self, raw: str, claims: list[Claim], drug: str, channel: Channel
    ) -> Draft:
        cleaned = _FENCE.sub("", raw).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise GenerationError(f"Model did not return valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise GenerationError("Model returned JSON that is not an object")

        body = payload.get("body")
        if not isinstance(body, str) or not body.strip():
            raise GenerationError("Model returned no usable body text")

        reported = payload.get("claim_ids_used") or []
        if not isinstance(reported, list):
            raise GenerationError("claim_ids_used must be a list")
        reported = [str(cid) for cid in reported]

        if not reported:
            raise GenerationError(
                "Model did not report any claim IDs. Content must cite the "
                "approved claims it draws on."
            )

        allowed = {c.id for c in claims}
        unknown = [cid for cid in reported if cid not in allowed]
        if unknown:
            raise GenerationError(
                f"Model cited claim IDs that are not in the approved set: {unknown}"
            )

        subject = payload.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            subject = None

        if channel is Channel.EMAIL and subject is None:
            raise GenerationError("Email content requires a subject line")

        return Draft(
            drug=drug,
            channel=channel,
            subject=subject.strip() if subject else None,
            body=body.strip(),
            claim_ids_used=reported,
        )