from __future__ import annotations

from typing import Protocol

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..models import Claim, ClaimType, HCPProfile, RetrievedClaim
from .loader import ClaimsKB

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

