from __future__ import annotations

import json
from pathlib import Path

from ..models import Claim


class ClaimsKB:
    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims
        self._by_id: dict[str, Claim] = {c.id: c for c in claims}
        if len(self._by_id) != len(claims):
            raise ValueError("Duplicate claim IDs found in KB")

    @classmethod
    def from_dir(cls, path: str | Path) -> "ClaimsKB":
        path = Path(path)
        claims: list[Claim] = []
        for f in sorted(path.glob("*.json")):
            payload = json.loads(f.read_text(encoding="utf-8"))
            for raw in payload.get("claims", []):
                claims.append(Claim.model_validate(raw))
        if not claims:
            raise ValueError(f"No claims loaded from {path}")
        return cls(claims)

    def __len__(self) -> int:
        return len(self._claims)

    @property
    def claims(self) -> list[Claim]:
        return list(self._claims)

    def get(self, claim_id: str) -> Claim | None:
        return self._by_id.get(claim_id)

    def for_drug(self, drug: str) -> list[Claim]:
        return [c for c in self._claims if c.drug.lower() == drug.lower()]

    def unverified(self) -> list[Claim]:
        return [c for c in self._claims if not c.verified]

    def integrity_report(self) -> dict:
        risk_side = [c for c in self._claims if c.claim_type.is_risk_side]
        missing_ref = [c.id for c in self._claims if not c.reference.section.strip()]
        return {
            "total_claims": len(self._claims),
            "drugs": sorted({c.drug for c in self._claims}),
            "unverified": len(self.unverified()),
            "risk_side_claims": len(risk_side),
            "claims_missing_reference_section": missing_ref,
        }