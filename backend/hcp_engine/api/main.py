from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..generation.generator import DraftGenerator
from ..graph.workflow import build_workflow, run_workflow
from ..kb.loader import ClaimsKB
from ..kb.retriever import TfidfRetriever
from ..models import Claim
from ..rules.engine import default_engine
from .schemas import (
    ClaimOut,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    SearchHit,
    SearchRequest,
)

logger = logging.getLogger(__name__)


def to_claim_out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        drug=claim.drug,
        text=claim.text,
        claim_type=claim.claim_type,
        source=claim.reference.source,
        section=claim.reference.section,
        verified=claim.verified,
        is_risk_side=claim.claim_type.is_risk_side,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading claims from %s", settings.claims_dir)
    kb = ClaimsKB.from_dir(settings.claims_dir)
    retriever = TfidfRetriever(kb)
    generator = DraftGenerator()
    engine = default_engine(
        strict_verification=settings.strict_verification,
        judge_can_block=settings.judge_can_block,
    )
    graph = build_workflow(
        kb, retriever, generator, engine, max_attempts=settings.max_attempts
    )

    app.state.kb = kb
    app.state.retriever = retriever
    app.state.engine = engine
    app.state.graph = graph
    logger.info("Ready: %d claims, rules %s", len(kb), engine.rule_ids)

    yield

    logger.info("Shutting down")


app = FastAPI(
    title="Compliant HCP Content Engine",
    description="Generates promotional content for healthcare professionals, "
    "grounded in an approved claim set and checked for regulatory compliance.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_kb(request: Request) -> ClaimsKB:
    return request.app.state.kb


def get_retriever(request: Request) -> TfidfRetriever:
    return request.app.state.retriever


def get_graph(request: Request):
    return request.app.state.graph


@app.get("/health", response_model=HealthResponse)
def health(request: Request, kb: ClaimsKB = Depends(get_kb)) -> HealthResponse:
    report = kb.integrity_report()
    return HealthResponse(
        status="ok",
        claims_loaded=report["total_claims"],
        drugs=report["drugs"],
        unverified_claims=report["unverified"],
        active_rules=request.app.state.engine.rule_ids,
    )


@app.get("/claims", response_model=list[ClaimOut])
def list_claims(
    drug: str | None = None,
    kb: ClaimsKB = Depends(get_kb),
) -> list[ClaimOut]:
    claims = kb.for_drug(drug) if drug else kb.claims
    if drug and not claims:
        raise HTTPException(status_code=404, detail=f"No claims for drug '{drug}'")
    return [to_claim_out(c) for c in claims]


@app.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: str, kb: ClaimsKB = Depends(get_kb)) -> ClaimOut:
    claim = kb.get(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
    return to_claim_out(claim)


@app.post("/search", response_model=list[SearchHit])
def search_claims(
    req: SearchRequest,
    retriever: TfidfRetriever = Depends(get_retriever),
) -> list[SearchHit]:
    results = retriever.search(req.query, drug=req.drug, top_k=req.top_k)
    return [
        SearchHit(
            claim=to_claim_out(r.claim),
            score=r.score,
            matched_terms=[term for term, _ in retriever.explain(req.query, r.claim.id)],
        )
        for r in results
    ]


@app.post("/generate", response_model=GenerateResponse)
def generate_content(
    req: GenerateRequest,
    kb: ClaimsKB = Depends(get_kb),
    graph=Depends(get_graph),
) -> GenerateResponse:
    if not kb.for_drug(req.drug):
        raise HTTPException(
            status_code=404, detail=f"No approved claims for drug '{req.drug}'"
        )

    try:
        state = run_workflow(graph, req.drug, req.profile, req.channel)
    except Exception as exc:
        logger.exception("Workflow failed")
        raise HTTPException(
            status_code=500, detail=f"Content generation failed: {exc}"
        ) from exc

    draft = state.get("draft")
    report = state.get("report")

    cited: list[ClaimOut] = []
    if draft is not None:
        for claim_id in draft.claim_ids_used:
            claim = kb.get(claim_id)
            if claim is not None:
                cited.append(to_claim_out(claim))

    return GenerateResponse(
        status=state.get("status", "unknown"),
        passed=report.passed if report is not None else False,
        drug=req.drug,
        channel=req.channel,
        subject=draft.subject if draft else None,
        body=draft.body if draft else None,
        cited_claims=cited,
        flags=report.flags if report is not None else [],
        attempts=state.get("attempts", 0),
        history=state.get("history", []),
    )