from __future__ import annotations

from typing import Protocol

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..models import Claim, ClaimType, HCPProfile, RetrievedClaim
from .loader import ClaimsKB


class Retriever(Protocol):
    def search(
        self, query: str, *, drug: str | None = None, top_k: int = 5
    ) -> list[RetrievedClaim]: ...


class TfidfRetriever:
    def __init__(self, kb: ClaimsKB) -> None:
        self.kb = kb
        self._claims = kb.claims
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            stop_words="english",
        )
        corpus = [c.searchable_text() for c in self._claims]
        self._matrix = self._vectorizer.fit_transform(corpus)

    def search(
        self, query: str, *, drug: str | None = None, top_k: int = 5
    ) -> list[RetrievedClaim]:
        q_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self._matrix)[0]

        results: list[RetrievedClaim] = []
        for claim, score in zip(self._claims, scores):
            if drug and claim.drug.lower() != drug.lower():
                continue
            if score <= 0:
                continue
            results.append(RetrievedClaim(claim=claim, score=float(score)))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def explain(self, query: str, claim_id: str) -> list[tuple[str, float]]:
        claim = self.kb.get(claim_id)
        if claim is None:
            return []
        idx = self._claims.index(claim)

        feature_names = self._vectorizer.get_feature_names_out()
        q_vec = self._vectorizer.transform([query]).toarray()[0]
        c_vec = self._matrix[idx].toarray()[0]

        contributions = q_vec * c_vec

        top = contributions.argsort()[::-1]
        return [
            (feature_names[i], float(contributions[i]))
            for i in top[:8]
            if contributions[i] > 0
        ]


def assemble_claim_set(
    retriever: Retriever,
    kb: ClaimsKB,
    profile: HCPProfile,
    drug: str,
    *,
    top_k: int = 4,
    document_id: str | None = None,
    max_risk_claims: int = 4,
) -> list[Claim]:
    """Build the claim set a draft is allowed to use.

    When document_id is given, claims are drawn from that document only - both
    benefit and risk - so the prompt uses one ID scheme. Mixing schemes makes
    the model invent plausible-looking IDs from the other scheme. Risk claims
    fall back to other sources only if the chosen document has none.
    """
    query = f"{profile.therapy_area} {profile.specialty}"
    retrieved = retriever.search(query, drug=drug, top_k=40)

    selected: dict[str, Claim] = {}
    for r in retrieved:
        if document_id and r.claim.reference.document_id != document_id:
            continue
        selected[r.claim.id] = r.claim
        if len(selected) >= top_k:
            break

    mandatory = {ClaimType.WARNING, ClaimType.CONTRAINDICATION}
    pool = [c for c in kb.for_drug(drug) if c.claim_type in mandatory]

    scoped = (
        [c for c in pool if c.reference.document_id == document_id]
        if document_id
        else []
    )
    chosen = scoped or pool

    # Boxed warnings first, then capped - a long claim list is harder for a
    # small model to track, and fair balance needs the most serious risks,
    # not all of them.
    chosen = sorted(
        chosen,
        key=lambda c: 0 if "BOXED WARNING" in c.reference.section.upper() else 1,
    )
    for claim in chosen[:max_risk_claims]:
        selected[claim.id] = claim

    return list(selected.values())