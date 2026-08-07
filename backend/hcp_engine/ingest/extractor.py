from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..config import settings
from ..models import Claim, ClaimType, Reference, SourceType

logger = logging.getLogger(__name__)

TYPE_ABBREV: dict[ClaimType, str] = {
    ClaimType.INDICATION: "ind",
    ClaimType.EFFICACY: "eff",
    ClaimType.DOSING: "dos",
    ClaimType.SAFETY: "saf",
    ClaimType.CONTRAINDICATION: "con",
    ClaimType.WARNING: "warn",
    ClaimType.MECHANISM: "mec",
    ClaimType.TRIAL_DATA: "trial",
}

EXTRACTION_SYSTEM = """You extract discrete factual claims about a drug from \
a source document. You are building a candidate list for human review.

RULES:
1. Extract only statements the text actually makes about {drug}. Do not add \
anything from your own knowledge.
2. Each claim must be a single self-contained sentence that stands on its own \
without the surrounding paragraph.
3. Do not extract: author names, funding statements, methodology descriptions, \
references, figure captions, or statements about other drugs.
4. Classify each claim as exactly one of: indication, efficacy, dosing, safety, \
contraindication, warning, mechanism, trial_data.
5. Give the section heading the claim appeared under if the text shows one, \
otherwise use a short description of where it came from.
6. If the passage contains no claims about {drug}, return an empty list.

Respond with ONLY this JSON object:
{{"claims": [{{"text": "<the claim as one sentence>", "claim_type": "<one of \
the eight>", "section": "<section heading or description>"}}]}}"""


class ExtractionError(RuntimeError):
    """Raised when a document cannot be read or produced no usable claims."""


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "document"


class ClaimExtractor:
    """Turns a PDF into candidate claims for human review.

    Everything this produces is verified=False by design. Extraction is the
    labour; approval stays with a person.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or settings.ollama_model
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_ollama import ChatOllama

            self._llm = ChatOllama(
                model=self._model_name,
                temperature=0,
                format="json",
                num_ctx=settings.ollama_num_ctx,
            )
        return self._llm

    # --- text extraction --------------------------------------------------

    @staticmethod
    def read_pages(pdf_path: str | Path) -> list[tuple[int, str]]:
        """Return (page_number, text) for every page with usable text."""
        import pdfplumber

        pages: list[tuple[int, str]] = []
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append((i, text))
        except Exception as exc:
            raise ExtractionError(f"Could not read the PDF: {exc}") from exc

        if not pages:
            raise ExtractionError(
                "No text found. The document may be a scan, which needs OCR."
            )
        return pages

    @staticmethod
    def chunk_pages(
        pages: list[tuple[int, str]], chunk_chars: int, max_chunks: int
    ) -> list[tuple[int, str]]:
        """Group pages into chunks. Returns (first_page_number, text)."""
        chunks: list[tuple[int, str]] = []
        buffer: list[str] = []
        start_page = pages[0][0]
        size = 0

        for page_no, text in pages:
            if size + len(text) > chunk_chars and buffer:
                chunks.append((start_page, "\n\n".join(buffer)))
                if len(chunks) >= max_chunks:
                    return chunks
                buffer, size, start_page = [], 0, page_no
            buffer.append(text)
            size += len(text)

        if buffer and len(chunks) < max_chunks:
            chunks.append((start_page, "\n\n".join(buffer)))
        return chunks

    # --- claim extraction -------------------------------------------------

    def _extract_from_chunk(self, chunk: str, drug: str) -> list[dict]:
        system = EXTRACTION_SYSTEM.format(drug=drug)
        user = f"SOURCE TEXT:\n{chunk}"

        try:
            response = self._get_llm().invoke(
                [("system", system), ("human", user)]
            )
            payload = json.loads(response.content)
        except Exception:
            logger.warning("Extraction failed for one chunk; skipping it")
            return []

        if not isinstance(payload, dict):
            return []
        items = payload.get("claims", [])
        return items if isinstance(items, list) else []

    def extract(
        self,
        pdf_path: str | Path,
        *,
        drug: str,
        source_name: str,
        source_type: SourceType = SourceType.PUBLICATION,
        document_id: str | None = None,
    ) -> list[Claim]:
        doc_id = document_id or slugify(source_name)
        pages = self.read_pages(pdf_path)
        chunks = self.chunk_pages(
            pages, settings.ingest_chunk_chars, settings.ingest_max_chunks
        )
        logger.info("Extracting from %d chunk(s) of %s", len(chunks), source_name)

        claims: list[Claim] = []
        seen: set[str] = set()
        counters: dict[str, int] = {}

        for page_no, chunk in chunks:
            for item in self._extract_from_chunk(chunk, drug):
                claim = self._build_claim(
                    item,
                    drug=drug,
                    doc_id=doc_id,
                    page_no=page_no,
                    source_name=source_name,
                    source_type=source_type,
                    counters=counters,
                    seen=seen,
                )
                if claim is not None:
                    claims.append(claim)

        if not claims:
            raise ExtractionError(
                "No claims could be extracted. The document may not discuss "
                f"'{drug}', or the text may be unreadable."
            )
        return claims

    def _build_claim(
        self,
        item: dict,
        *,
        drug: str,
        doc_id: str,
        page_no: int,
        source_name: str,
        source_type: SourceType,
        counters: dict[str, int],
        seen: set[str],
    ) -> Claim | None:
        if not isinstance(item, dict):
            return None

        text = str(item.get("text", "")).strip()
        if len(text) < 10:
            return None

        fingerprint = text.lower()[:120]
        if fingerprint in seen:
            return None
        seen.add(fingerprint)

        try:
            claim_type = ClaimType(str(item.get("claim_type", "")).strip().lower())
        except ValueError:
            logger.debug("Unknown claim_type %r, skipping", item.get("claim_type"))
            return None

        abbrev = TYPE_ABBREV[claim_type]
        counters[abbrev] = counters.get(abbrev, 0) + 1
        claim_id = f"{doc_id}-{abbrev}-{counters[abbrev]:03d}"

        section = str(item.get("section", "")).strip() or f"Page {page_no}"

        try:
            return Claim(
                id=claim_id,
                drug=drug,
                text=text,
                claim_type=claim_type,
                reference=Reference(
                    source=source_name,
                    section=section[:120],
                    source_type=source_type,
                    page=page_no,
                    document_id=doc_id,
                ),
                verified=False,
            )
        except Exception:
            logger.debug("Claim failed validation, skipping: %r", text[:60])
            return None


def write_claims_file(
    claims: list[Claim], *, drug: str, doc_id: str, claims_dir: Path
) -> Path:
    """Write extracted claims as a KB file. Returns the path written."""
    claims_dir.mkdir(parents=True, exist_ok=True)
    path = claims_dir / f"{doc_id}.json"
    payload = {
        "drug": drug,
        "_comment": (
            "MACHINE-EXTRACTED CANDIDATE CLAIMS. Every entry is verified=false. "
            "Each must be confirmed against the source document by a human "
            "before use."
        ),
        "claims": [c.model_dump(mode="json") for c in claims],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path