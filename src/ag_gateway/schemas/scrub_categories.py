from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SeverityClass = Literal["pii", "codeword", "secret"]


@dataclass(frozen=True)
class ScrubCategory:
    name: str
    severity: SeverityClass
    patterns: tuple[re.Pattern[str], ...]
    description: str = ""

    @property
    def replacement_strategy(self) -> Literal["tokenize", "redact"]:
        return "tokenize" if self.severity == "pii" else "redact"


class ScrubCatalog:
    """Collection of categories loaded from the bundle's scrub-types.json."""

    def __init__(self, categories: list[ScrubCategory]) -> None:
        self._by_name = {c.name: c for c in categories}

    @classmethod
    def from_bundle(cls, bundle_root: Path) -> "ScrubCatalog":
        path = bundle_root / "schemas" / "shared" / "scrub-types.json"
        if not path.exists():
            raise FileNotFoundError(f"scrub-types not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        cats: list[ScrubCategory] = []
        for entry in doc.get("categories", []):
            cats.append(
                ScrubCategory(
                    name=str(entry["name"]),
                    severity=str(entry["severity"]),  # type: ignore[arg-type]
                    patterns=tuple(re.compile(p) for p in entry.get("patterns", [])),
                    description=str(entry.get("description", "")),
                )
            )
        return cls(cats)

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def get(self, name: str) -> ScrubCategory:
        return self._by_name[name]

    def by_severity(self, severity: SeverityClass) -> list[ScrubCategory]:
        return [c for c in self._by_name.values() if c.severity == severity]
