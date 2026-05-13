from __future__ import annotations

from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine, RecognizerResult

from ag_gateway.schemas.scrub_categories import ScrubCatalog, ScrubCategory


@dataclass(frozen=True)
class Detection:
    """A scrub hit in some text."""

    category: ScrubCategory
    start: int
    end: int
    score: float

    @property
    def span_text(self) -> str:
        return ""

    def with_text(self, original: str) -> "Detection":
        return Detection(
            category=self.category, start=self.start, end=self.end, score=self.score
        )


class ScrubEngine:
    """Presidio analyzer + regex-backstop detector. Returns spans in original-text order."""

    PRESIDIO_MAP = {
        "EMAIL_ADDRESS": "EMAIL",
        "PHONE_NUMBER": "PHONE",
        "US_SSN": "SSN",
        "CREDIT_CARD": "CREDIT_CARD",
        "PERSON": "NAME",
        "LOCATION": "ADDRESS",
        "IP_ADDRESS": "IP_ADDRESS",
        "DATE_TIME": "DOB",
        "IBAN_CODE": "IBAN",
    }

    def __init__(self, catalog: ScrubCatalog, presidio: AnalyzerEngine | None = None) -> None:
        self._catalog = catalog
        self._presidio = presidio or AnalyzerEngine()

    def scan(self, text: str, language: str = "en") -> list[Detection]:
        """Return non-overlapping detections in start order, picking highest-severity on conflict."""
        spans: list[Detection] = []

        # 1) Regex backstop — any category that ships patterns
        for cat in [
            *self._catalog.by_severity("secret"),
            *self._catalog.by_severity("codeword"),
            *self._catalog.by_severity("pii"),
        ]:
            for pat in cat.patterns:
                for m in pat.finditer(text):
                    spans.append(Detection(category=cat, start=m.start(), end=m.end(), score=1.0))

        # 2) Presidio — only for PII categories
        results: list[RecognizerResult] = self._presidio.analyze(text=text, language=language)
        for r in results:
            mapped = self.PRESIDIO_MAP.get(r.entity_type)
            if not mapped or mapped not in self._catalog.names():
                continue
            cat = self._catalog.get(mapped)
            spans.append(Detection(category=cat, start=r.start, end=r.end, score=float(r.score)))

        # 3) Resolve overlaps: prefer higher severity, then higher score
        severity_rank = {"secret": 3, "codeword": 2, "pii": 1}
        spans.sort(
            key=lambda s: (s.start, -severity_rank[s.category.severity], -s.score)
        )

        merged: list[Detection] = []
        for s in spans:
            if merged and s.start < merged[-1].end:
                continue
            merged.append(s)
        return merged
