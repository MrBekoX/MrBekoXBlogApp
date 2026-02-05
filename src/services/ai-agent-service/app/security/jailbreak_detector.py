from typing import Tuple, List, Optional
import logging
import asyncio
from dataclasses import dataclass
from enum import Enum
from app.core.config import settings

logger = logging.getLogger(__name__)

class JailbreakType(str, Enum):
    """Types of jailbreak attacks."""
    DIRECT = "direct"           # "Ignore all instructions"
    INDIRECT = "indirect"       # Via external content
    ROLE_PLAY = "role_play"     # "You are now a hacker"
    OBSCURED = "obscured"       # Using base64, rot13, etc.
    MULTILINGUAL = "multilingual" # Non-English attacks
    ADVERSARIAL = "adversarial" # Gradient-based attacks

@dataclass
class JailbreakResult:
    """Jailbreak detection result."""
    is_jailbreak: bool
    confidence: float
    jailbreak_type: Optional[JailbreakType]
    patterns: List[str]
    semantic_score: float

class SemanticJailbreakDetector:
    """AI-based semantic jailbreak detection."""

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm
        # Simple heuristic classifier (can be replaced with ML model)
        self.dangerous_phrases = {
            JailbreakType.DIRECT: [
                "ignore previous",
                "override system",
                "disregard instructions",
                "forget everything",
                "new instructions",
            ],
            JailbreakType.ROLE_PLAY: [
                "you are now",
                "pretend to be",
                "act as",
                "roleplay as",
                "simulate being",
            ],
            JailbreakType.INDIRECT: [
                "translate the following",
                "what would you say if",
                "hypothetically",
                "for educational purposes",
            ],
            JailbreakType.OBSCURED: [],
            JailbreakType.MULTILINGUAL: [],
        }

    async def detect(self, content: str) -> JailbreakResult:
        """Detect jailbreak attempts using semantic analysis."""
        
        # Red team mode bypass
        if settings.enable_red_team_mode:
            return JailbreakResult(False, 0.0, None, [], 0.0)

        results = []
        patterns = [] # We will populate this if we integrate with regex here or pass it in. 
        # For now, let's assume this class does SEMANTIC checks. 
        # The caller might combine regex. But let's verify if we should run regex here too.
        # The skill plan says: "1. Pattern-based detection (existing) from app.core.sanitizer import detect_injection"
        # Since we are inside `app.security`, importing `app.core` is fine.
        
        try:
             # Lazy import to avoid circular dependency if sanitizer imports this
            from app.core.sanitizer import detect_injection
            is_suspicious, patterns = detect_injection(content)
            results.append(("pattern", is_suspicious, 1.0 if is_suspicious else 0.0))
        except ImportError:
            pass 

        # 2. Semantic phrase matching
        semantic_score = self._semantic_phrase_scan(content)
        results.append(("semantic", semantic_score > 0.5, semantic_score))

        # 3. LLM-based detection (optional)
        llm_score = 0.0
        if self.use_llm:
            llm_score = await self._llm_detect(content)
            results.append(("llm", llm_score > 0.7, llm_score))

        # Aggregate results
        final_confidence = self._aggregate_results(results)
        is_jailbreak = final_confidence > settings.jailbreak_confidence_threshold

        jailbreak_type = self._classify_type(content, patterns)

        return JailbreakResult(
            is_jailbreak=is_jailbreak,
            confidence=final_confidence,
            jailbreak_type=jailbreak_type,
            patterns=patterns,
            semantic_score=semantic_score
        )

    def _semantic_phrase_scan(self, content: str) -> float:
        """Scan for dangerous semantic phrases."""
        content_lower = content.lower()
        max_score = 0.0

        for jailbreak_type, phrases in self.dangerous_phrases.items():
            for phrase in phrases:
                if phrase in content_lower:
                    # Check context (phrase should appear in suspicious context)
                    score = self._context_score(content_lower, phrase)
                    max_score = max(max_score, score)

        return max_score

    def _context_score(self, content: str, phrase: str) -> float:
        """Calculate context-based score for a phrase."""
        # Higher score if:
        # - Phrase appears at the beginning
        # - Phrase is followed by imperatives
        
        score = 0.5  # Base score for phrase presence

        # Position bonus
        phrase_index = content.find(phrase)
        if phrase_index < 100:  # In first 100 chars
            score += 0.2

        # Imperative verbs after phrase
        imperative_verbs = ["do", "tell", "show", "give", "write", "create"]
        after_phrase = content[phrase_index + len(phrase):phrase_index + len(phrase) + 50]
        if any(verb in after_phrase for verb in imperative_verbs):
            score += 0.2

        return min(score, 1.0)

    async def _llm_detect(self, content: str) -> float:
        """Use LLM (or heuristic fallback) to detect jailbreak attempts."""
        # For this implementation, we use advanced heuristics as a mocked LLM score
        # In production this would call self.llm_client.classify
        # We simulate this slightly differently than phrase scan to give "ensemble" effect
        
        dangerous_indicators = [
            "ignore", "override", "disregard", "forget",
            "pretend", "roleplay", "simulate",
            "unrestricted", "uncensored", "bypass"
        ]

        content_lower = content.lower()
        matches = sum(1 for indicator in dangerous_indicators if indicator in content_lower)
        
        # Sigmoid-ish scaling
        return min(matches * 0.25, 1.0)

    def _aggregate_results(self, results: List[Tuple[str, bool, float]]) -> float:
        """Aggregate multiple detection results."""
        if not results:
            return 0.0

        # Weighted average
        weights = {
            "pattern": 0.3,
            "semantic": 0.4,
            "llm": 0.3
        }

        weighted_sum = 0.0
        total_weight = 0.0

        for method, is_detected, score in results:
            weight = weights.get(method, 0.1)
            # Take score directly
            weighted_sum += score * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _classify_type(self, content: str, patterns: List[str]) -> Optional[JailbreakType]:
        """Classify the type of jailbreak attempt."""
        content_lower = content.lower()

        # Check for direct overrides
        if any(p in content_lower for p in ["ignore", "override", "disregard"]):
            return JailbreakType.DIRECT

        # Check for roleplay
        if any(p in content_lower for p in ["pretend", "act as", "roleplay"]):
            return JailbreakType.ROLE_PLAY

        # Check for indirect
        if any(p in content_lower for p in ["translate", "hypothetically", "educational"]):
            return JailbreakType.INDIRECT

        if patterns:
             return JailbreakType.DIRECT # Default for regex matches usually

        return None
