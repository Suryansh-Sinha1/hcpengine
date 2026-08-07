from __future__ import annotations

import json
import logging
import re

from ..config import settings
from ..models import Channel, Claim, Draft, HCPProfile

logger = logging.getLogger(__name__)


CHANNEL_BRIEF: dict[Channel, str] = {
    Channel.EMAIL: (
        "An email to a physician. 130-180 words total. Structure it exactly:\n"
        "1. Greeting: 'Dear Doctor,'\n"
        "2. An opening line naming why you are writing - the clinical question "
        "or decision this content speaks to.\n"
        "3. Two or three SHORT paragraphs, blank line between each. Lead with "
        "the indication or trial data, then the risk information.\n"
        "4. A closing line offering the full prescribing information.\n"
        "5. Sign off with 'Sincerely,' then the sender name on the next line.\n"
        "Write in continuous prose. Do not use bullet points, headings, or "
        "numbered lists. Do not write one long block - use paragraph breaks."
    ),
    Channel.DETAIL_AID: (
        "Copy for a single detail-aid panel a representative shows in person. "
        "60-100 words. Terse, scannable, clinically precise. No greeting, no "
        "sign-off, no subject line."
    ),
    Channel.FOLLOW_UP: (
        "A brief follow-up message after a prior interaction. 80-120 words. "
        "Open by referencing continuity of conversation without inventing "
        "specifics. Close with a sign-off. No subject line."
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
"eliminates the risk" or "prevents". Do not make comparative claims - "compared \
with other treatments" is never acceptable unless an approved claim says it.
4. Do not use these words or any similar: safest, safe, best, most effective, \
superior, breakthrough, miracle, guaranteed, cure, proven, well tolerated.
5. You MUST communicate the RISK INFORMATION in the body text. Citing it is not \
enough - the reader must actually see it.
6. You may rephrase claims for readability, but must not change their clinical \
meaning, strength, or scope.
7. In claim_ids_used, list ONLY the labels shown in square brackets below - \
C1, C2, C3 and so on. Use nothing else. Do not invent labels, do not use the \
drug name, do not make up identifiers. An empty list is never correct.
8. Do NOT write any label like C1 in the body text. The body is read by a \
physician. Labels belong only in claim_ids_used.

APPROVED CLAIMS - this is the complete set of assertions available to you:
{claims_block}

AUDIENCE: {specialty}, therapy area: {therapy_area}.
{adoption_note}

FORMAT: {channel_brief}

SENDER: {sender_name}, {sender_org}

Respond with ONLY this JSON object:
{{"subject": "<subject line, or null if not applicable>", "body": "<the \
content, with \\n\\n between paragraphs>", "claim_ids_used": ["C1", "C3"]}}"""


REVISION_TEMPLATE = """Your previous draft was rejected by compliance review.

PREVIOUS DRAFT:
{previous_body}

COMPLIANCE FAILURES - fix every one:
{failures}

Write a new draft that fixes these problems. The rules, approved claims, and \
format in your instructions still apply in full."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
_LABEL_IN_BODY = re.compile(r"\s*[\[(]\s*C\d+\s*[\])]")


class GenerationError(RuntimeError):
    """Raised when model output cannot be parsed or cannot be trusted."""


class ModelUnavailableError(GenerationError):
    """The model could not be reached. Retrying will not help."""


def label_claims(claims: list[Claim]) -> list[tuple[str, Claim]]:
    """Assign short labels (C1, C2, ...) for use in the prompt.

    Real claim IDs can run past 40 characters once a document slug is in
    them. A small model will not copy those exactly - it abbreviates and
    invents plausible-looking identifiers instead. Two-character labels are
    trivially copyable, and the model cannot fabricate a valid one because
    the whole space is visible in the prompt.
    """
    ordered = sorted(claims, key=lambda c: (c.claim_type.value, c.id))
    return [(f"C{i}", claim) for i, claim in enumerate(ordered, start=1)]


def render_claims_block(claims: list[Claim]) -> str:
    lines: list[str] = []
    for label, claim in label_claims(claims):
        tag = (
            "RISK INFORMATION"
            if claim.claim_type.is_risk_side
            else claim.claim_type.value.upper()
        )
        lines.append(f"[{label}] ({tag}) {claim.text}")
    return "\n".join(lines)


class DraftGenerator:
    def __init__(
        self, model: str | None = None, *, temperature: float | None = None
    ) -> None:
        self._model_name = model or settings.ollama_model
        self._temperature = (
            temperature
            if temperature is not None
            else settings.generation_temperature
        )
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_ollama import ChatOllama

            self._llm = ChatOllama(
                model=self._model_name,
                temperature=self._temperature,
                format="json",
                num_ctx=settings.ollama_num_ctx,
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

        label_map = {label: claim.id for label, claim in label_claims(claims)}

        system = SYSTEM_TEMPLATE.format(
            claims_block=render_claims_block(claims),
            specialty=profile.specialty,
            therapy_area=profile.therapy_area,
            adoption_note=ADOPTION_BRIEF.get(profile.adoption_stage, ""),
            channel_brief=CHANNEL_BRIEF[channel],
            sender_name=settings.sender_name,
            sender_org=settings.sender_org,
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

        return self._parse(raw, claims, drug, channel, label_map)

    def _parse(
        self,
        raw: str,
        claims: list[Claim],
        drug: str,
        channel: Channel,
        label_map: dict[str, str],
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

        # Rule 8 asks the model to keep labels out of the prose. Strip any
        # that slip through rather than failing the whole draft over cosmetics.
        body = _LABEL_IN_BODY.sub("", body).strip()

        reported = payload.get("claim_ids_used") or []
        if not isinstance(reported, list):
            raise GenerationError("claim_ids_used must be a list")
        reported = [str(cid).strip() for cid in reported]

        if not reported:
            raise GenerationError(
                "Model did not report any claim labels. Content must cite the "
                "approved claims it draws on."
            )

        allowed_ids = {c.id for c in claims}
        resolved: list[str] = []
        unknown: list[str] = []

        for cid in reported:
            if cid in label_map:
                resolved.append(label_map[cid])
            elif cid in allowed_ids:
                resolved.append(cid)
            else:
                unknown.append(cid)

        if unknown:
            raise GenerationError(
                f"Model reported labels that were not offered: {unknown}. "
                f"Valid labels were {sorted(label_map)}."
            )

        # Preserve order, drop duplicates.
        seen: set[str] = set()
        claim_ids = [c for c in resolved if not (c in seen or seen.add(c))]

        subject = payload.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            subject = None

        if channel is Channel.EMAIL and subject is None:
            raise GenerationError("Email content requires a subject line")

        return Draft(
            drug=drug,
            channel=channel,
            subject=subject.strip() if subject else None,
            body=body,
            claim_ids_used=claim_ids,
        )