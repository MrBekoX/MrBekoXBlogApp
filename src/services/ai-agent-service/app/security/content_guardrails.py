"""
LLM Output Guardrails

Validates LLM responses for safety before returning to users.
Checks: topic boundary, system prompt leakage, toxic content,
response length, and confidence scoring.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Maximum response length (characters)
DEFAULT_MAX_RESPONSE_LENGTH = 50_000


@dataclass
class GuardrailViolation:
    """A single guardrail violation."""
    rule: str
    severity: str  # "low", "medium", "high", "critical"
    description: str


@dataclass
class GuardrailResult:
    """Result of guardrail checks."""
    is_safe: bool
    violations: List[GuardrailViolation] = field(default_factory=list)
    confidence_score: float = 1.0
    sanitized_response: Optional[str] = None


class ContentGuardrails:
    """
    LLM output guardrails for the BlogApp AI Agent.

    Enforces:
    - Topic boundary (blog-related content only)
    - System prompt leakage prevention
    - Toxic/harmful content filtering
    - Response length limits
    - Confidence scoring heuristic
    """

    # Off-topic categories that the blog AI agent should not discuss
    OFF_TOPIC_PATTERNS = [
        # Weapons & violence
        re.compile(
            r'\b(silah\s+yapım|bomba\s+yapım|patlayıcı\s+yapım|'
            r'how\s+to\s+make\s+a?\s*(bomb|weapon|explosive)|'
            r'build\s+a\s+(gun|weapon))\b',
            re.IGNORECASE,
        ),
        # Drug manufacturing
        re.compile(
            r'\b(uyuşturucu\s+yapım|drug\s+synth|meth\s+cook|'
            r'how\s+to\s+(make|synthesize|cook)\s+(drugs?|meth|cocaine))\b',
            re.IGNORECASE,
        ),
        # Hacking instructions
        re.compile(
            r'\b(hack\s+(into|a\s+system)|password\s+crack|'
            r'exploit\s+(vulnerability|CVE)|ddos\s+attack\s+tutorial)\b',
            re.IGNORECASE,
        ),
        # Self-harm
        re.compile(
            r'\b(intihar\s+yöntem|suicide\s+method|self[- ]?harm\s+technique)\b',
            re.IGNORECASE,
        ),
    ]

    # Patterns indicating system prompt leakage
    SYSTEM_PROMPT_LEAK_PATTERNS = [
        re.compile(r'(?:system\s*prompt|system\s*mesaj)[:\s]*["\']', re.IGNORECASE),
        re.compile(r'(?:my|the)\s+instructions?\s+(?:are|say|tell)', re.IGNORECASE),
        re.compile(r'(?:I\s+was|I\s+am)\s+(?:told|instructed|programmed)\s+to', re.IGNORECASE),
        re.compile(r'(?:benim|bana)\s+(?:verilen|atanan)\s+(?:talimat|komut|görev)', re.IGNORECASE),
        re.compile(r'IMPORTANT:\s*The\s+content\s+below\s+is\s+USER\s+DATA', re.IGNORECASE),
        re.compile(r'Do\s+not\s+interpret\s+any\s+text\s+within', re.IGNORECASE),
    ]

    # Toxic/harmful content keywords
    TOXIC_PATTERNS = [
        re.compile(
            r'\b(ırk(?:çı|çılık)|racist|racial\s+slur|'
            r'hate\s+speech|nefret\s+söylemi)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(terör(?:ist|izm)|terrorist|terrorism)\b',
            re.IGNORECASE,
        ),
    ]

    # Low-confidence indicators in LLM output
    UNCERTAINTY_PHRASES = [
        "emin değilim", "bilmiyorum", "tahmin ediyorum",
        "i'm not sure", "i don't know", "i'm guessing",
        "possibly", "perhaps", "might be", "could be",
        "belki", "olabilir", "sanırım",
    ]

    def __init__(
        self,
        max_response_length: int = DEFAULT_MAX_RESPONSE_LENGTH,
    ) -> None:
        self.max_response_length = max_response_length

    def check_response(
        self,
        response: str,
        original_query: Optional[str] = None,
    ) -> GuardrailResult:
        """
        Run all guardrail checks on an LLM response.

        Args:
            response: The LLM-generated response text
            original_query: The original user query (for context)

        Returns:
            GuardrailResult with is_safe=False if response should be blocked
        """
        if not response:
            return GuardrailResult(is_safe=True, confidence_score=0.0)

        violations: List[GuardrailViolation] = []

        # 1. Response length check
        length_violation = self._check_response_length(response)
        if length_violation:
            violations.append(length_violation)

        # 2. System prompt leakage check
        leak_violation = self._check_system_prompt_leakage(response)
        if leak_violation:
            violations.append(leak_violation)

        # 3. Off-topic / harmful content check
        topic_violations = self._check_topic_boundary(response)
        violations.extend(topic_violations)

        # 4. Toxic content check
        toxic_violations = self._check_toxic_content(response)
        violations.extend(toxic_violations)

        # 5. Calculate confidence score
        confidence = self._calculate_confidence(response)

        # Determine safety
        has_critical = any(v.severity == "critical" for v in violations)
        has_high = any(v.severity == "high" for v in violations)
        is_safe = not has_critical and not has_high

        # Sanitize if needed
        sanitized = response
        if not is_safe:
            sanitized = self._sanitize_response(response, violations)

        if violations:
            logger.warning(
                f"ContentGuardrails: {len(violations)} violation(s) detected, "
                f"safe={is_safe}, confidence={confidence:.2f}"
            )

        return GuardrailResult(
            is_safe=is_safe,
            violations=violations,
            confidence_score=confidence,
            sanitized_response=sanitized if not is_safe else None,
        )

    def _check_response_length(self, response: str) -> Optional[GuardrailViolation]:
        """Check if response exceeds maximum length."""
        if len(response) > self.max_response_length:
            return GuardrailViolation(
                rule="response_length",
                severity="medium",
                description=f"Response length ({len(response)}) exceeds limit ({self.max_response_length})",
            )
        return None

    def _check_system_prompt_leakage(self, response: str) -> Optional[GuardrailViolation]:
        """Detect system prompt leakage in response."""
        for pattern in self.SYSTEM_PROMPT_LEAK_PATTERNS:
            match = pattern.search(response)
            if match:
                return GuardrailViolation(
                    rule="system_prompt_leakage",
                    severity="critical",
                    description=f"Potential system prompt leakage detected: '{match.group()[:60]}...'",
                )
        return None

    def _check_topic_boundary(self, response: str) -> List[GuardrailViolation]:
        """Check for off-topic/harmful content in response."""
        violations = []
        for pattern in self.OFF_TOPIC_PATTERNS:
            match = pattern.search(response)
            if match:
                violations.append(GuardrailViolation(
                    rule="topic_boundary",
                    severity="high",
                    description=f"Off-topic/harmful content detected: '{match.group()[:50]}'",
                ))
        return violations

    def _check_toxic_content(self, response: str) -> List[GuardrailViolation]:
        """Check for toxic/hate-speech content."""
        violations = []
        for pattern in self.TOXIC_PATTERNS:
            match = pattern.search(response)
            if match:
                violations.append(GuardrailViolation(
                    rule="toxic_content",
                    severity="high",
                    description=f"Toxic content detected: '{match.group()[:50]}'",
                ))
        return violations

    def _calculate_confidence(self, response: str) -> float:
        """
        Calculate a heuristic confidence score for the response.

        Based on:
        - Response length (too short = low confidence)
        - Uncertainty phrases
        - Response structure
        """
        score = 1.0
        response_lower = response.lower()

        # Penalize very short responses
        if len(response) < 20:
            score -= 0.3

        # Penalize empty-ish responses
        if len(response.split()) < 5:
            score -= 0.2

        # Count uncertainty phrases
        uncertainty_count = sum(
            1 for phrase in self.UNCERTAINTY_PHRASES
            if phrase in response_lower
        )
        score -= uncertainty_count * 0.1

        # Bonus for structured content (lists, headers)
        if re.search(r'^\s*[-*•]\s+', response, re.MULTILINE):
            score += 0.05
        if re.search(r'^#+\s', response, re.MULTILINE):
            score += 0.05

        return max(0.0, min(1.0, score))

    def _sanitize_response(
        self,
        response: str,
        violations: List[GuardrailViolation],
    ) -> str:
        """Produce a safe replacement when the original response is blocked."""
        violation_types = {v.rule for v in violations}

        if "system_prompt_leakage" in violation_types:
            return (
                "Bu soruya cevap veremiyorum. "
                "Lütfen blog makalesiyle ilgili bir soru sorun."
            )

        if "topic_boundary" in violation_types or "toxic_content" in violation_types:
            return (
                "Bu içerik güvenlik politikalarımıza uygun değildir. "
                "Lütfen blog konularıyla ilgili sorular sorun."
            )

        return (
            "İsteğiniz işlenemedi. "
            "Lütfen farklı bir şekilde sormayı deneyin."
        )
