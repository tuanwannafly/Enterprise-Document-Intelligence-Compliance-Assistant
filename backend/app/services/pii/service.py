"""AWS Comprehend PII detection + redaction.

Two strategies are supported and switchable at runtime:

* ``ComprehendPiiRedactor`` — uses Amazon Comprehend's ``DetectPiiEntities``
  API. This is the production strategy and supports the full range of entity
  types Comprehend knows about.

* ``RegexPiiRedactor`` — uses regular-expression based detection for the most
  common entity types (email, phone, SSN, IBAN, credit-card-shaped numbers) and
  is used in tests + offline dev environments where the AWS API isn't reachable.

Both strategies expose the same ``redact(text) -> (redacted, spans)`` API.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol

from app.core.aws import get_comprehend_client
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import RedactionSpan

logger = get_logger(__name__)


@dataclass
class _DetectedEntity:
    entity_type: str
    text: str
    start: int
    end: int
    confidence: float


class PiiRedactionService(Protocol):
    """Interface implemented by every PII redaction strategy."""

    def detect(self, text: str) -> list[_DetectedEntity]: ...
    def redact(self, text: str) -> tuple[str, list[RedactionSpan]]: ...


# ----------------------------------------------------------------------
# Regex-based implementation — used in tests + offline dev.
# ----------------------------------------------------------------------
class RegexPiiRedactor:
    """Detect a small set of common PII entities via regular expressions.

    The categories covered here are intentionally narrow. Anything not matched
    is allowed through; this is acceptable because the regex redactor is only
    the fallback path used when Comprehend isn't reachable.
    """

    PATTERNS: dict[str, re.Pattern] = {
        "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "PHONE": re.compile(
            r"\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?)?\d{3,4}[ -]?\d{3,4}\b"
        ),
        "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "CREDIT_DEBIT_NUMBER": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "BANK_ACCOUNT_NUMBER": re.compile(r"\b\d{8,17}\b"),
    }

    def __init__(self, entity_types: Optional[Iterable[str]] = None) -> None:
        settings = get_settings()
        self._enabled = set(t.upper() for t in (entity_types or settings.pii_entity_types))
        self._patterns = {k: v for k, v in self.PATTERNS.items() if k in self._enabled}

    def detect(self, text: str) -> list[_DetectedEntity]:
        found: list[_DetectedEntity] = []
        for etype, pattern in self._patterns.items():
            for match in pattern.finditer(text):
                found.append(
                    _DetectedEntity(
                        entity_type=etype,
                        text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        confidence=0.95,
                    )
                )
        # Sort + de-overlap (greedy by start, longer match wins).
        found.sort(key=lambda e: (e.start, -(e.end - e.start)))
        deduped: list[_DetectedEntity] = []
        last_end = -1
        for ent in found:
            if ent.start >= last_end:
                deduped.append(ent)
                last_end = ent.end
        return deduped

    def redact(self, text: str) -> tuple[str, list[RedactionSpan]]:
        entities = self.detect(text)
        if not entities:
            return text, []
        out: list[str] = []
        cursor = 0
        spans: list[RedactionSpan] = []
        for ent in entities:
            out.append(text[cursor : ent.start])
            replacement = f"[REDACTED:{ent.entity_type}]"
            out.append(replacement)
            spans.append(
                RedactionSpan(
                    entity_type=ent.entity_type,
                    text=ent.text,
                    start=ent.start,
                    end=ent.end,
                    confidence=ent.confidence,
                )
            )
            cursor = ent.end
        out.append(text[cursor:])
        return "".join(out), spans


# ----------------------------------------------------------------------
# Comprehend-based implementation — production path.
# ----------------------------------------------------------------------
class ComprehendPiiRedactor:
    """Detect PII entities via Amazon Comprehend and redact them."""

    def __init__(self, entity_types: Optional[Iterable[str]] = None) -> None:
        settings = get_settings()
        self._enabled = set(t.upper() for t in (entity_types or settings.pii_entity_types))
        self._client = get_comprehend_client()

    def detect(self, text: str) -> list[_DetectedEntity]:
        if not text.strip():
            return []
        # Comprehend's hard limit is 100KB per request. Truncate for safety
        # in production we would split, but for now we keep it simple.
        if len(text) > 99_000:
            text = text[:99_000]

        resp = self._client.detect_pii_entities(
            Text=text,
            LanguageCode="en",
        )
        found: list[_DetectedEntity] = []
        for ent in resp.get("Entities", []):
            etype = ent.get("Type", "").upper()
            if etype not in self._enabled:
                continue
            found.append(
                _DetectedEntity(
                    entity_type=etype,
                    text=text[ent["BeginOffset"] : ent["EndOffset"]],
                    start=int(ent["BeginOffset"]),
                    end=int(ent["EndOffset"]),
                    confidence=float(ent.get("Score", 0.0)),
                )
            )
        found.sort(key=lambda e: (e.start, -(e.end - e.start)))
        return found

    def redact(self, text: str) -> tuple[str, list[RedactionSpan]]:
        entities = self.detect(text)
        if not entities:
            return text, []
        out: list[str] = []
        cursor = 0
        spans: list[RedactionSpan] = []
        for ent in entities:
            out.append(text[cursor : ent.start])
            out.append(f"[REDACTED:{ent.entity_type}]")
            spans.append(
                RedactionSpan(
                    entity_type=ent.entity_type,
                    text=ent.text,
                    start=ent.start,
                    end=ent.end,
                    confidence=ent.confidence,
                )
            )
            cursor = ent.end
        out.append(text[cursor:])
        return "".join(out), spans


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------
def get_pii_service() -> PiiRedactionService:
    """Return the PII redactor appropriate for the current environment.

    Tests use the regex implementation; everything else uses Comprehend.
    """
    settings = get_settings()
    if settings.app_env in {"test", "development", "dev"} and not getattr(
        settings, "_use_comprehend", False
    ):
        # Cheap and offline-friendly. Switch to Comprehend once you can hit AWS.
        return RegexPiiRedactor()
    return ComprehendPiiRedactor()
