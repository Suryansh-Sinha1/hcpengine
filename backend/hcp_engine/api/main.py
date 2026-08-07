from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..generation.generator import DraftGenerator
from ..graph.workflow import build_workflow, run_workflow
from ..ingest.extractor import (
    ClaimExtractor,
    ExtractionError,
    slugify,
    write_claims_file,
)
from ..kb.loader import ClaimsKB
from ..kb.retriever import TfidfRetriever
from ..models import Claim, Draft, SourceType
from ..rules.engine import ComplianceEngine, default_engine
from ..store.decisions import DecisionStore
from .schemas import (
    ClaimOut,
    DecisionOut,
    DecisionRequest,
    DocumentOut,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    IngestResponse,
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
        source_type=claim.reference.source_type,
        page=claim.reference.page,
        document_id=claim.reference.document_id,
        verified=claim.verified,
        is_risk_side=claim.claim_type.is_risk_side,
    )


def rebuild_kb_state(app: FastAPI) -> ClaimsKB:
    """Reload the KB from disk and rebuild everything derived from it.

    The TF-IDF matrix and the compiled graph both close over the KB, so a new
    claims file means both must be rebuilt. Cheap at this scale.
    """
    kb = ClaimsKB.from_dir(settings.claims_dir)
    retriever = TfidfRetriever(kb)
    app.state.kb = kb
    app.state.retriever = retriever
    app.state.graph = build_workflow(
        kb,
        retriever,
        app.state.generator,
        app.state.engine,
        max_attempts=settings.max_attempts,
    )
    logger.info("KB rebuilt: %d claims", len(kb))
    return kb


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading claims from %s", settings.claims_dir)
    app.state.generator = DraftGenerator()
    app.state.engine = default_engine(
        strict_verification=settings.strict_verification,
        judge_can_block=settings.judge_can_block,
    )
    app.state.extractor = ClaimExtractor()
    app.state.store = DecisionStore(settings.database_path)

    kb = rebuild_kb_state(app)
    logger.info("Ready: %d claims, rules %s", len(kb), app.state.engine.rule_ids)

    yield

    logger.info("Shutting down")


app = FastAPI(
    title="Compliant HCP Content Engine",
    description="Generates promotional content for healthcare professionals, "
    "grounded in an approved claim set and checked for regulatory compliance.",
    version="0.2.0",
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


def get_engine(request: Request) -> ComplianceEngine:
    return request.app.state.engine


def get_store(request: Request) -> DecisionStore:
    return request.app.state.store


def get_extractor(request: Request) -> ClaimExtractor:
    return request.app.state.extractor


def get_graph(request: Request):
    return request.app.state.graph


@app.get("/health", response_model=HealthResponse)
def health(
    kb: ClaimsKB = Depends(get_kb),
    engine: ComplianceEngine = Depends(get_engine),
) -> HealthResponse:
    report = kb.integrity_report()
    return HealthResponse(
        status="ok",
        claims_loaded=report["total_claims"],
        drugs=report["drugs"],
        unverified_claims=report["unverified"],
        active_rules=engine.rule_ids,
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


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(kb: ClaimsKB = Depends(get_kb)) -> list[DocumentOut]:
    grouped: dict[str, list[Claim]] = {}
    for claim in kb.claims:
        doc_id = claim.reference.document_id or "seed"
        grouped.setdefault(doc_id, []).append(claim)

    return [
        DocumentOut(
            document_id=doc_id,
            drug=claims[0].drug,
            source_name=claims[0].reference.source,
            source_type=claims[0].reference.source_type,
            claim_count=len(claims),
            verified_count=sum(1 for c in claims if c.verified),
        )
        for doc_id, claims in sorted(grouped.items())
    ]


@app.post("/ingest", response_model=IngestResponse, status_code=201)
def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    drug: str = Form(...),
    source_name: str = Form(...),
    source_type: SourceType = Form(SourceType.PUBLICATION),
    extractor: ClaimExtractor = Depends(get_extractor),
) -> IngestResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    doc_id = slugify(source_name)
    tmp_path = Path(tempfile.gettempdir()) / f"hcp-ingest-{doc_id}.pdf"

    try:
        with tmp_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        claims = extractor.extract(
            tmp_path,
            drug=drug.strip().lower(),
            source_name=source_name.strip(),
            source_type=source_type,
            document_id=doc_id,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(
            status_code=500, detail=f"Ingestion failed: {exc}"
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    write_claims_file(
        claims,
        drug=drug.strip().lower(),
        doc_id=doc_id,
        claims_dir=Path(settings.claims_dir),
    )
    rebuild_kb_state(request.app)

    return IngestResponse(
        document_id=doc_id,
        drug=drug.strip().lower(),
        source_name=source_name.strip(),
        source_type=source_type,
        claims_extracted=len(claims),
        claims=[to_claim_out(c) for c in claims],
    )


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
            matched_terms=[
                term for term, _ in retriever.explain(req.query, r.claim.id)
            ],
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


@app.post("/decisions", response_model=DecisionOut, status_code=201)
def record_decision(
    req: DecisionRequest,
    kb: ClaimsKB = Depends(get_kb),
    engine: ComplianceEngine = Depends(get_engine),
    store: DecisionStore = Depends(get_store),
) -> DecisionOut:
    claims = kb.for_drug(req.drug)
    if not claims:
        raise HTTPException(
            status_code=404, detail=f"No approved claims for drug '{req.drug}'"
        )

    try:
        draft = Draft(
            drug=req.drug,
            channel=req.channel,
            subject=req.subject,
            body=req.body,
            claim_ids_used=req.claim_ids,
        )
    except Exception as exc:
        if req.decision == "approved":
            raise HTTPException(
                status_code=422,
                detail=f"Content is malformed and cannot be approved: {exc}",
            ) from exc
        return DecisionOut(
            **store.record(
                {
                    "decision": req.decision,
                    "reviewer": req.reviewer,
                    "note": req.note,
                    "drug": req.drug,
                    "channel": req.channel.value,
                    "specialty": req.profile.specialty,
                    "therapy_area": req.profile.therapy_area,
                    "adoption_stage": req.profile.adoption_stage,
                    "subject": req.subject,
                    "body": req.body,
                    "claim_ids": req.claim_ids,
                    "flags_at_decision": [],
                    "passed_automated": False,
                }
            )
        )

    report = engine.check(draft, claims)

    if req.decision == "approved" and not report.passed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Content cannot be approved: it has "
                f"{len(report.blockers)} blocking compliance issue(s)."
            ),
        )

    return DecisionOut(
        **store.record(
            {
                "decision": req.decision,
                "reviewer": req.reviewer,
                "note": req.note,
                "drug": req.drug,
                "channel": req.channel.value,
                "specialty": req.profile.specialty,
                "therapy_area": req.profile.therapy_area,
                "adoption_stage": req.profile.adoption_stage,
                "subject": req.subject,
                "body": req.body,
                "claim_ids": req.claim_ids,
                "flags_at_decision": [f.model_dump() for f in report.flags],
                "passed_automated": report.passed,
            }
        )
    )


@app.get("/decisions", response_model=list[DecisionOut])
def list_decisions(
    limit: int = 50, store: DecisionStore = Depends(get_store)
) -> list[DecisionOut]:
    return [DecisionOut(**d) for d in store.list_recent(limit)]