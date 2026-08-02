from __future__ import annotations

import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from ..generation.generator import DraftGenerator, GenerationError
from ..kb.loader import ClaimsKB
from ..kb.retriever import Retriever, assemble_claim_set
from ..models import Channel, Claim, Draft, HCPProfile
from ..rules.engine import ComplianceEngine
from ..rules.models import ComplianceReport

logger = logging.getLogger(__name__)


class ContentState(TypedDict, total=False):
    drug: str
    profile: HCPProfile
    channel: Channel

    claims: list[Claim]
    draft: Draft | None
    report: ComplianceReport | None

    attempts: int
    max_attempts: int
    status: str
    error: str | None

    history: Annotated[list[str], operator.add]


def build_workflow(
    kb: ClaimsKB,
    retriever: Retriever,
    generator: DraftGenerator,
    engine: ComplianceEngine,
    *,
    max_attempts: int = 3,
):
    def retrieve_node(state: ContentState) -> dict:
        claims = assemble_claim_set(
            retriever, kb, state["profile"], state["drug"]
        )
        return {
            "claims": claims,
            "max_attempts": max_attempts,
            "attempts": 0,
            "history": [f"Assembled {len(claims)} approved claims."],
        }

    def generate_node(state: ContentState) -> dict:
        attempt = state.get("attempts", 0) + 1
        report = state.get("report")
        previous = state.get("draft")

        failures = None
        previous_body = None
        if report is not None and previous is not None:
            failures = [f.message for f in report.blockers]
            previous_body = previous.body

        try:
            draft = generator.generate(
                state["claims"],
                state["profile"],
                state["drug"],
                state.get("channel", Channel.EMAIL),
                previous_body=previous_body,
                failures=failures,
            )
        except GenerationError as exc:
            logger.warning("Generation attempt %d failed: %s", attempt, exc)
            return {
                "draft": None,
                "attempts": attempt,
                "error": str(exc),
                "history": [f"Attempt {attempt}: generation failed - {exc}"],
            }

        label = "Revised draft" if failures else "Initial draft"
        return {
            "draft": draft,
            "attempts": attempt,
            "error": None,
            "history": [f"Attempt {attempt}: {label} produced."],
        }

    def check_node(state: ContentState) -> dict:
        draft = state["draft"]
        report = engine.check(draft, state["claims"])
        return {
            "report": report,
            "history": [f"Compliance check: {report.summary()}"],
        }

    def route_after_generate(state: ContentState) -> str:
        if state.get("draft") is not None:
            return "check"
        if state.get("attempts", 0) >= state.get("max_attempts", max_attempts):
            return "give_up"
        return "retry"

    def route_after_check(state: ContentState) -> str:
        report = state.get("report")
        if report is not None and report.passed:
            return "approve"
        if state.get("attempts", 0) >= state.get("max_attempts", max_attempts):
            return "give_up"
        return "revise"

    def approved_node(state: ContentState) -> dict:
        return {
            "status": "pending_human_review",
            "history": ["Passed automated checks. Awaiting human approval."],
        }

    def blocked_node(state: ContentState) -> dict:
        reason = state.get("error") or "did not pass compliance review"
        return {
            "status": "blocked",
            "history": [
                f"Stopped after {state.get('attempts', 0)} attempts: {reason}"
            ],
        }

    workflow = StateGraph(ContentState)

    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("check", check_node)
    workflow.add_node("approved", approved_node)
    workflow.add_node("blocked", blocked_node)

    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "generate")

    workflow.add_conditional_edges(
        "generate",
        route_after_generate,
        {"check": "check", "retry": "generate", "give_up": "blocked"},
    )

    workflow.add_conditional_edges(
        "check",
        route_after_check,
        {"approve": "approved", "revise": "generate", "give_up": "blocked"},
    )

    workflow.add_edge("approved", END)
    workflow.add_edge("blocked", END)

    return workflow.compile()


def run_workflow(
    app,
    drug: str,
    profile: HCPProfile,
    channel: Channel = Channel.EMAIL,
) -> ContentState:
    return app.invoke(
        {
            "drug": drug,
            "profile": profile,
            "channel": channel,
            "history": [],
        }
    )