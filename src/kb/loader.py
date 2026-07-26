from __future__ import annotations
import json
from pathlib import Path
from ..models import Claim

import os
path = os.path.join("data", "claims", "apixaban.json")

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