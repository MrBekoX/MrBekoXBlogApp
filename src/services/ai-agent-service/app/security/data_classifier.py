"""
Data Classification & PII Detection

Regex-based data classification and PII detection with Turkey-specific patterns.
Provides risk scoring and GDPR relevancy checks without external dependencies.
"""

import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DataClassification(str, Enum):
    """Data classification levels."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class PIIType(str, Enum):
    """PII entity types."""
    TCKN = "TCKN"
    CREDIT_CARD = "CREDIT_CARD"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IBAN = "IBAN"
    IP_ADDRESS = "IP_ADDRESS"
    API_KEY = "API_KEY"
    PERSON = "PERSON"
    URL = "URL"


@dataclass
class PIIEntity:
    """Detected PII entity."""
    pii_type: PIIType
    start: int
    end: int
    confidence: float
    text: str = ""


@dataclass
class ClassificationResult:
    """Data classification result."""
    classification: DataClassification
    pii_entities: List[PIIEntity]
    risk_score: float
    gdpr_relevant: bool
    anonymized_text: str
    entity_count: int = 0


class DataClassifier:
    """
    Data classification and PII detection engine.

    Supports Turkish-specific patterns (TCKN, TR phone, IBAN)
    and general PII patterns (email, credit card, IP, API keys).
    """

    # PII detection patterns with confidence scores
    PII_PATTERNS: Dict[PIIType, tuple] = {
        # Turkish ID number: 11 digits starting with non-zero
        PIIType.TCKN: (
            re.compile(r'\b[1-9]\d{10}\b'),
            0.85,
        ),
        # Credit card: 4 groups of 4 digits
        PIIType.CREDIT_CARD: (
            re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
            0.95,
        ),
        # Email addresses
        PIIType.EMAIL: (
            re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            0.95,
        ),
        # Turkish phone numbers (05XX XXX XX XX)
        PIIType.PHONE: (
            re.compile(r'\b(05\d{2})[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}\b'),
            0.90,
        ),
        # Turkish IBAN (TR followed by 24 digits)
        PIIType.IBAN: (
            re.compile(r'\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b', re.IGNORECASE),
            0.95,
        ),
        # IP addresses
        PIIType.IP_ADDRESS: (
            re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'),
            0.70,
        ),
        # API keys (long alphanumeric strings)
        PIIType.API_KEY: (
            re.compile(r'\b(?:sk|pk|api|key|token)[-_]?[A-Za-z0-9]{32,}\b', re.IGNORECASE),
            0.80,
        ),
    }

    # Risk weights per PII type
    RISK_WEIGHTS: Dict[PIIType, float] = {
        PIIType.CREDIT_CARD: 1.0,
        PIIType.IBAN: 1.0,
        PIIType.TCKN: 1.0,
        PIIType.PERSON: 0.8,
        PIIType.EMAIL: 0.6,
        PIIType.PHONE: 0.6,
        PIIType.API_KEY: 0.7,
        PIIType.IP_ADDRESS: 0.4,
        PIIType.URL: 0.2,
    }

    # GDPR-relevant entity types
    GDPR_ENTITY_TYPES = {
        PIIType.TCKN, PIIType.EMAIL, PIIType.PHONE,
        PIIType.PERSON, PIIType.IP_ADDRESS, PIIType.IBAN,
    }

    def __init__(self) -> None:
        logger.info("DataClassifier initialized")

    def detect_pii(self, text: str) -> List[PIIEntity]:
        """Detect all PII entities in text."""
        entities: List[PIIEntity] = []

        for pii_type, (pattern, base_confidence) in self.PII_PATTERNS.items():
            for match in pattern.finditer(text):
                entities.append(PIIEntity(
                    pii_type=pii_type,
                    start=match.start(),
                    end=match.end(),
                    confidence=base_confidence,
                    text=match.group(),
                ))

        # Sort by start position
        entities.sort(key=lambda e: e.start)
        return entities

    def classify(self, text: str) -> DataClassification:
        """Classify text based on PII content."""
        entities = self.detect_pii(text)
        return self._determine_classification(entities)

    def classify_and_redact(self, text: str) -> ClassificationResult:
        """Classify text and redact all PII entities."""
        entities = self.detect_pii(text)
        classification = self._determine_classification(entities)
        risk_score = self._calculate_risk_score(entities)
        gdpr_relevant = self._is_gdpr_relevant(entities)
        anonymized = self._redact_text(text, entities)

        result = ClassificationResult(
            classification=classification,
            pii_entities=entities,
            risk_score=risk_score,
            gdpr_relevant=gdpr_relevant,
            anonymized_text=anonymized,
            entity_count=len(entities),
        )

        if entities:
            logger.info(
                f"DataClassifier: classification={classification.value}, "
                f"pii_count={len(entities)}, risk={risk_score:.2f}, "
                f"gdpr={gdpr_relevant}"
            )

        return result

    def _determine_classification(self, entities: List[PIIEntity]) -> DataClassification:
        """Determine classification level based on detected entities."""
        if not entities:
            return DataClassification.PUBLIC

        entity_types = {e.pii_type for e in entities}

        # Restricted: financial data
        if entity_types & {PIIType.CREDIT_CARD, PIIType.IBAN}:
            return DataClassification.RESTRICTED

        # Confidential: personal identifiers
        if entity_types & {PIIType.TCKN, PIIType.EMAIL, PIIType.PHONE, PIIType.PERSON}:
            return DataClassification.CONFIDENTIAL

        # Internal: technical data
        if entity_types & {PIIType.IP_ADDRESS, PIIType.API_KEY}:
            return DataClassification.INTERNAL

        return DataClassification.PUBLIC

    def _calculate_risk_score(self, entities: List[PIIEntity]) -> float:
        """Calculate risk score from 0.0 to 1.0."""
        if not entities:
            return 0.0

        max_score = 0.0
        for entity in entities:
            weight = self.RISK_WEIGHTS.get(entity.pii_type, 0.2)
            score = weight * entity.confidence
            max_score = max(max_score, score)

        return min(max_score, 1.0)

    def _is_gdpr_relevant(self, entities: List[PIIEntity]) -> bool:
        """Check if data contains GDPR-relevant PII."""
        return any(e.pii_type in self.GDPR_ENTITY_TYPES for e in entities)

    def _redact_text(self, text: str, entities: List[PIIEntity]) -> str:
        """Redact PII entities from text (reverse order to preserve positions)."""
        result = text
        for entity in reversed(entities):
            placeholder = f"[{entity.pii_type.value}_REDACTED]"
            result = result[:entity.start] + placeholder + result[entity.end:]
        return result
