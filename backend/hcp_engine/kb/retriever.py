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
) -> list[Claim]:
    query = f"{profile.therapy_area} {profile.specialty}"
    retrieved = retriever.search(query, drug=drug, top_k=top_k)
    selected: dict[str, Claim] = {r.claim.id: r.claim for r in retrieved}

    mandatory_types = {ClaimType.WARNING, ClaimType.CONTRAINDICATION}
    for claim in kb.for_drug(drug):
        if claim.claim_type in mandatory_types:
            selected[claim.id] = claim

    return list(selected.values())