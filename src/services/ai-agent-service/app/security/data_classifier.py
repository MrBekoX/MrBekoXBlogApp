from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import logging
import re

# Presidio imports
# We use try-except to allow loading even if dependencies are missing (for dev environments without heavy libs)
try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import RecognizerResult
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False
    logging.warning("Presidio not found. Data classification will be limited.")

logger = logging.getLogger(__name__)

class DataClassification(str, Enum):
    """Data classification levels."""
    PUBLIC = "public"           # No sensitive data
    INTERNAL = "internal"       # Internal business data
    CONFIDENTIAL = "confidential"  # Contains PII
    RESTRICTED = "restricted"   # Highly sensitive

@dataclass
class ClassificationResult:
    """Classification result."""
    classification: DataClassification
    pii_entities: List[Dict]
    risk_score: float
    gdpr_relevant: bool
    anonymized_text: str

class DataClassifier:
    """Data classification and PII detection."""

    def __init__(self):
        self.enabled = PRESIDIO_AVAILABLE
        if self.enabled:
            # Initialize engines
            # Note: This might take time to load models
            self.analyzer = AnalyzerEngine() 
            self.anonymizer = AnonymizerEngine()
            
            # Register custom recognizers
            self._add_custom_recognizers()
    
    @staticmethod
    def _validate_tckn(number_str: str) -> bool:
        """Validate Turkish ID number using checksum algorithm."""
        if len(number_str) != 11 or number_str[0] == '0':
            return False
        digits = [int(d) for d in number_str]
        # 10th digit check
        odd_sum = sum(digits[0:9:2])   # 1st, 3rd, 5th, 7th, 9th
        even_sum = sum(digits[1:8:2])  # 2nd, 4th, 6th, 8th
        check10 = (odd_sum * 7 - even_sum) % 10
        if check10 != digits[9]:
            return False
        # 11th digit check
        check11 = sum(digits[0:10]) % 10
        return check11 == digits[10]

    def _add_custom_recognizers(self):
        """Add custom recognizers for TR context."""
        # 1. TCKN (Turkish ID)
        tckn_pattern = r"\b[1-9]\d{10}\b"
        tckn_recognizer = PatternRecognizer(
            supported_entity="TCKN",
            name="Turkish ID Number",
            patterns=[{"name": "TCKN", "regex": tckn_pattern, "score": 0.9}],
            context=["TCKN", "Kimlik No", "TC No", "T.C."]
        )
        self.analyzer.registry.add_recognizer(tckn_recognizer)

        # 2. TR Phone
        tr_phone_pattern = r"\b(05\d{2})[-\s]?(\d{3})[-\s]?(\d{2})[-\s]?(\d{2})\b"
        tr_phone_recognizer = PatternRecognizer(
            supported_entity="TR_PHONE",
            name="Turkish Phone Number",
            patterns=[{"name": "TR Phone", "regex": tr_phone_pattern, "score": 0.85}],
            context=["telefon", "GSM", "Cep", "tel"]
        )
        self.analyzer.registry.add_recognizer(tr_phone_recognizer)

    def classify_and_redact(
        self,
        text: str,
        language: str = "en" # Default to EN model as presidio usually uses en_core_web_lg for detection even if content is mixed
    ) -> ClassificationResult:
        """Classify data and redact PII."""
        if not self.enabled or not text:
             return ClassificationResult(
                 DataClassification.PUBLIC, [], 0.0, False, text or ""
             )

        # map language 'tr' to 'en' for presidio if explicit TR model not loaded, 
        # or rely on regex mostly for TR specific entities.
        # Presidio's NLP engine usually needs correct code. 'en' works for general entities.
        analyze_lang = "en" 
        
        try:
            results = self.analyzer.analyze(
                text=text,
                entities=[
                    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", 
                    "CREDIT_CARD", "IP_ADDRESS", "LOCATION", "DATE_TIME", "URL",
                    "TCKN", "TR_PHONE"
                ],
                language=analyze_lang
            )
        except Exception as e:
            logger.error(f"Presidio analysis failed: {e}")
            return ClassificationResult(DataClassification.PUBLIC, [], 0.0, False, text)

        # Post-filter: validate TCKN matches with checksum to reduce false positives
        results = [
            r for r in results
            if r.entity_type != "TCKN" or self._validate_tckn(text[r.start:r.end])
        ]

        # Classification
        classification = self._classify(results)
        risk_score = self._calculate_risk_score(results)
        gdpr_relevant = self._is_gdpr_relevant(results)

        # Anonymize
        anonymized_result = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results
        )
        
        # Extract entities for reporting
        pii_entities = [
            {
                "type": r.entity_type,
                "start": r.start,
                "end": r.end,
                "confidence": r.score,
                "text": text[r.start:r.end]
            }
            for r in results
        ]

        return ClassificationResult(
            classification=classification,
            pii_entities=pii_entities,
            risk_score=risk_score,
            gdpr_relevant=gdpr_relevant,
            anonymized_text=anonymized_result.text
        )

    def _classify(self, results: List) -> DataClassification:
        if not results:
            return DataClassification.PUBLIC
        
        entity_types = {r.entity_type for r in results}
        
        if "CREDIT_CARD" in entity_types or "IBAN_CODE" in entity_types:
            return DataClassification.RESTRICTED
            
        if any(t in entity_types for t in ["PERSON", "TCKN", "EMAIL_ADDRESS", "PHONE_NUMBER", "TR_PHONE"]):
            return DataClassification.CONFIDENTIAL
            
        if "LOCATION" in entity_types or "IP_ADDRESS" in entity_types:
            return DataClassification.INTERNAL
            
        return DataClassification.PUBLIC

    def _calculate_risk_score(self, results: List) -> float:
        if not results:
            return 0.0
            
        weights = {
            "CREDIT_CARD": 1.0, "IBAN_CODE": 1.0, "TCKN": 1.0,
            "PERSON": 0.8, "EMAIL_ADDRESS": 0.7, "PHONE_NUMBER": 0.7, "TR_PHONE": 0.7,
            "IP_ADDRESS": 0.5, "LOCATION": 0.4
        }
        
        max_score = 0.0
        for r in results:
            w = weights.get(r.entity_type, 0.1)
            # Use presidio score * weight
            max_score = max(max_score, w * r.score)
            
        return min(max_score, 1.0)

    def _is_gdpr_relevant(self, results: List) -> bool:
        gdpr_entities = {"PERSON", "EMAIL_ADDRESS", "TCKN", "TR_PHONE", "PHONE_NUMBER", "IP_ADDRESS"}
        return any(r.entity_type in gdpr_entities for r in results)

# Singleton
data_classifier = DataClassifier()
