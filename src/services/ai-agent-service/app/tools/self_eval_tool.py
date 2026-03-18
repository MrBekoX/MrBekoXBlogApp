"""Self-Evaluation Tool - Agent self-assessment capabilities.

Enables the agent to evaluate its own outputs for quality and accuracy.
"""

import logging
import re
from typing import Any

from app.domain.interfaces.i_llm_provider import ILLMProvider

logger = logging.getLogger(__name__)


# Evaluation prompts optimized for Gemma3:4b
QUALITY_EVAL_PROMPT = """Evaluate this answer quality (1-5):
Question: {question}
Answer: {answer}

Rate: relevance, accuracy, completeness.
Reply format:
SCORE: X/5
ISSUES: [list any problems]
IMPROVEMENT: [brief suggestion, 10 words max]"""

HALLUCINATION_CHECK_PROMPT = """Check if this answer contains false information:
Source: {source}
Answer: {answer}

Reply ONLY:
- ACCURATE if answer matches source
- HALLUCINATION if answer adds false info
- UNCLEAR if cannot verify

Verdict:"""


class SelfEvalTool:
    """Tool for agent self-evaluation.

    Provides capabilities for:
    - Answer quality assessment
    - Hallucination detection
    - Confidence scoring
    """

    def __init__(
        self,
        llm_provider: ILLMProvider,
    ):
        self._llm = llm_provider

    async def __call__(
        self,
        answer: str,
        question: str = "",
        source: str = "",
    ) -> str:
        """Evaluate an answer for quality.

        Args:
            answer: The answer to evaluate
            question: Original question (for relevance check)
            source: Source material (for accuracy check)

        Returns:
            Evaluation result with score and suggestions
        """
        # Run quality evaluation
        quality_result = await self.evaluate_quality(answer, question)

        # Run hallucination check if source provided
        if source:
            hallucination_result = await self.check_hallucination(answer, source)
            return f"{quality_result}\n\nAccuracy Check: {hallucination_result}"

        return quality_result

    async def evaluate_quality(
        self,
        answer: str,
        question: str = "",
    ) -> str:
        """Evaluate answer quality.

        Args:
            answer: The answer to evaluate
            question: Original question

        Returns:
            Quality evaluation string
        """
        prompt = QUALITY_EVAL_PROMPT.format(
            question=question[:500] if question else "N/A",
            answer=answer[:1000],
        )

        try:
            response = await self._llm.generate_text(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"[SelfEval] Quality evaluation failed: {e}")
            return f"Evaluation error: {e}"

    async def check_hallucination(
        self,
        answer: str,
        source: str,
    ) -> str:
        """Check if answer contains hallucinations.

        Args:
            answer: The answer to check
            source: Source material to verify against

        Returns:
            Hallucination check result
        """
        prompt = HALLUCINATION_CHECK_PROMPT.format(
            source=source[:1000],
            answer=answer[:500],
        )

        try:
            response = await self._llm.generate_text(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"[SelfEval] Hallucination check failed: {e}")
            return f"Check error: {e}"

    async def get_confidence_score(
        self,
        answer: str,
        question: str = "",
        source: str = "",
    ) -> float:
        """Get a numeric confidence score for an answer.

        Args:
            answer: The answer to evaluate
            question: Original question
            source: Source material

        Returns:
            Confidence score between 0 and 1
        """
        evaluation = await self(answer, question, source)

        # Extract score from evaluation
        score_match = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)[/\s]", evaluation)
        if score_match:
            score = float(score_match.group(1))
            return min(score / 5.0, 1.0)  # Normalize to 0-1

        # Check for accuracy indicators
        lower_eval = evaluation.lower()
        if "accurate" in lower_eval:
            return 0.8
        elif "hallucination" in lower_eval:
            return 0.3
        elif "unclear" in lower_eval:
            return 0.5

        # Default moderate confidence
        return 0.6

    async def should_regenerate(
        self,
        answer: str,
        question: str = "",
        source: str = "",
        threshold: float = 0.6,
    ) -> tuple[bool, str]:
        """Determine if answer should be regenerated.

        Args:
            answer: Current answer
            question: Original question
            source: Source material
            threshold: Confidence threshold

        Returns:
            Tuple of (should_regenerate, reason)
        """
        confidence = await self.get_confidence_score(answer, question, source)

        if confidence < threshold:
            return True, f"Confidence {confidence:.2f} below threshold {threshold}"

        return False, f"Confidence {confidence:.2f} acceptable"


class ReplanTrigger:
    """Utility for determining when to trigger replanning.

    Analyzes execution results to decide if replanning is needed.
    """

    # Indicators that suggest replanning is needed
    FAILURE_INDICATORS = [
        "error",
        "failed",
        "unable to",
        "cannot",
        "not available",
        "timeout",
        "no result",
        "empty",
        "null",
        "none",
    ]

    @staticmethod
    def should_replan(
        result: str,
        expected: str,
        iteration: int,
        max_iterations: int,
    ) -> tuple[bool, str]:
        """Determine if replanning is needed.

        Args:
            result: Actual result
            expected: Expected output description
            iteration: Current iteration
            max_iterations: Maximum allowed iterations

        Returns:
            Tuple of (should_replan, reason)
        """
        # Check for explicit failure indicators
        lower_result = result.lower()
        for indicator in ReplanTrigger.FAILURE_INDICATORS:
            if indicator in lower_result:
                return True, f"Failure indicator detected: {indicator}"

        # Check if result is too short (might be incomplete)
        if len(result) < 20:
            return True, "Result too short, possibly incomplete"

        # Check iteration limit
        if iteration >= max_iterations - 1:
            return False, "Near iteration limit, should finalize"

        # Default: no replan needed
        return False, "Result appears acceptable"

    @staticmethod
    def analyze_error(error: str) -> dict[str, Any]:
        """Analyze an error to determine recovery strategy.

        Args:
            error: Error message

        Returns:
            Dict with error analysis
        """
        lower_error = error.lower()

        analysis = {
            "is_recoverable": True,
            "error_type": "unknown",
            "suggested_action": "retry",
        }

        # Categorize error
        if "timeout" in lower_error:
            analysis.update({
                "error_type": "timeout",
                "suggested_action": "retry_with_smaller_request",
            })
        elif "rate limit" in lower_error:
            analysis.update({
                "error_type": "rate_limit",
                "suggested_action": "wait_and_retry",
            })
        elif "not found" in lower_error:
            analysis.update({
                "error_type": "not_found",
                "is_recoverable": False,
                "suggested_action": "use_alternative_source",
            })
        elif "permission" in lower_error or "unauthorized" in lower_error:
            analysis.update({
                "error_type": "permission",
                "is_recoverable": False,
                "suggested_action": "skip_tool",
            })
        elif "connection" in lower_error:
            analysis.update({
                "error_type": "connection",
                "suggested_action": "retry_with_backoff",
            })

        return analysis
