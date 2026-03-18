"""Autonomy Guardrails - Safety mechanisms for autonomous agent execution.

Implements hard and soft limits to ensure safe, bounded autonomous operation.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TerminationReason(Enum):
    """Reasons for agent termination."""

    SUCCESS = "success"
    MAX_ITERATIONS = "max_iterations"
    TIMEOUT = "timeout"
    MAX_LLM_CALLS = "max_llm_calls"
    MAX_TOKENS = "max_tokens"
    ERROR = "error"
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    USER_INTERRUPT = "user_interrupt"
    LOOP_DETECTED = "loop_detected"
    GUARDRAIL_TRIGGERED = "guardrail_triggered"


@dataclass
class GuardrailState:
    """Current state tracked by guardrails."""

    iterations: int = 0
    llm_calls: int = 0
    tokens_used: int = 0
    start_time: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)
    last_actions: list[str] = field(default_factory=list)
    last_results: list[str] = field(default_factory=list)  # Track result previews for semantic loop detection
    confidence_scores: list[float] = field(default_factory=list)

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time


@dataclass
class GuardrailResult:
    """Result of guardrail check."""

    should_continue: bool
    reason: TerminationReason
    message: str
    state: GuardrailState
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_continue": self.should_continue,
            "reason": self.reason.value,
            "message": self.message,
            "violations": self.violations,
            "state": {
                "iterations": self.state.iterations,
                "llm_calls": self.state.llm_calls,
                "tokens_used": self.state.tokens_used,
                "elapsed_seconds": self.state.elapsed_seconds(),
            },
        }


class AutonomyGuardrails:
    """Safety mechanisms for autonomous agent execution.

    HARD LIMITS (cannot be overridden):
    - MAX_TOTAL_ITERATIONS: 10
    - MAX_TIME_SECONDS: 120
    - MAX_LLM_CALLS: 15
    - MAX_TOKENS_USED: 8000

    SOFT LIMITS (agent can adjust):
    - DEFAULT_MAX_STEPS: 5
    - CONFIDENCE_THRESHOLD: 0.7
    """

    # Hard limits - cannot be exceeded
    MAX_TOTAL_ITERATIONS: int = 10
    MAX_TIME_SECONDS: int = 120
    MAX_LLM_CALLS: int = 15
    MAX_TOKENS_USED: int = 8000

    # Soft limits - configurable
    DEFAULT_MAX_STEPS: int = 5
    CONFIDENCE_THRESHOLD: float = 0.7
    MAX_CONSECUTIVE_ERRORS: int = 3

    # Loop detection
    MAX_ACTION_REPETITIONS: int = 3
    ACTION_HISTORY_SIZE: int = 10

    def __init__(
        self,
        max_iterations: int | None = None,
        max_time_seconds: int | None = None,
        max_llm_calls: int | None = None,
        max_tokens: int | None = None,
        confidence_threshold: float | None = None,
    ):
        """Initialize guardrails with optional custom limits.

        Hard limits cannot exceed class defaults.
        """
        self._max_iterations = min(
            max_iterations or self.MAX_TOTAL_ITERATIONS,
            self.MAX_TOTAL_ITERATIONS,
        )
        self._max_time = min(
            max_time_seconds or self.MAX_TIME_SECONDS,
            self.MAX_TIME_SECONDS,
        )
        self._max_llm_calls = min(
            max_llm_calls or self.MAX_LLM_CALLS,
            self.MAX_LLM_CALLS,
        )
        self._max_tokens = min(
            max_tokens or self.MAX_TOKENS_USED,
            self.MAX_TOKENS_USED,
        )
        self._confidence_threshold = confidence_threshold or self.CONFIDENCE_THRESHOLD

        self._state = GuardrailState()

    @property
    def state(self) -> GuardrailState:
        return self._state

    def reset(self) -> None:
        """Reset guardrail state for a new execution."""
        self._state = GuardrailState(
            last_actions=[],
            last_results=[],
            errors=[],
            confidence_scores=[],
        )
        logger.debug("[Guardrails] State reset for new execution")

    def record_iteration(self) -> None:
        """Record that an iteration has occurred."""
        self._state.iterations += 1

    def record_llm_call(self, tokens: int = 0) -> None:
        """Record an LLM call and optionally token usage."""
        self._state.llm_calls += 1
        self._state.tokens_used += tokens

    def record_error(self, error: str) -> None:
        """Record an error that occurred."""
        self._state.errors.append(error)

    def record_action(self, action: str, result_preview: str | None = None) -> None:
        """Record an action taken by the agent.

        Args:
            action: The action name/description
            result_preview: Optional preview of the result for semantic loop detection
        """
        self._state.last_actions.append(action)
        # Keep only recent actions
        if len(self._state.last_actions) > self.ACTION_HISTORY_SIZE:
            self._state.last_actions = self._state.last_actions[-self.ACTION_HISTORY_SIZE :]

        # Track result preview for semantic loop detection
        if result_preview:
            self._state.last_results.append(result_preview[:200])  # Truncate to 200 chars
            if len(self._state.last_results) > self.ACTION_HISTORY_SIZE:
                self._state.last_results = self._state.last_results[-self.ACTION_HISTORY_SIZE :]

    def record_confidence(self, confidence: float) -> None:
        """Record a confidence score."""
        self._state.confidence_scores.append(confidence)

    async def check_limits(self) -> GuardrailResult:
        """Check all hard limits.

        Returns:
            GuardrailResult indicating if execution should continue
        """
        violations = []

        # Check iteration limit
        if self._state.iterations >= self._max_iterations:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.MAX_ITERATIONS,
                message=f"Max iterations ({self._max_iterations}) reached",
                state=self._state,
                violations=["iteration_limit"],
            )

        # Check time limit
        elapsed = self._state.elapsed_seconds()
        if elapsed >= self._max_time:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.TIMEOUT,
                message=f"Time limit ({self._max_time}s) exceeded after {elapsed:.1f}s",
                state=self._state,
                violations=["time_limit"],
            )

        # Check LLM call limit
        if self._state.llm_calls >= self._max_llm_calls:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.MAX_LLM_CALLS,
                message=f"Max LLM calls ({self._max_llm_calls}) reached",
                state=self._state,
                violations=["llm_call_limit"],
            )

        # Check token limit
        if self._state.tokens_used >= self._max_tokens:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.MAX_TOKENS,
                message=f"Max tokens ({self._max_tokens}) used",
                state=self._state,
                violations=["token_limit"],
            )

        # Check consecutive errors
        recent_errors = self._state.errors[-self.MAX_CONSECUTIVE_ERRORS :]
        if len(recent_errors) >= self.MAX_CONSECUTIVE_ERRORS:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.ERROR,
                message=f"Too many consecutive errors: {recent_errors}",
                state=self._state,
                violations=["consecutive_errors"],
            )

        return GuardrailResult(
            should_continue=True,
            reason=TerminationReason.SUCCESS,
            message="All limits OK",
            state=self._state,
            violations=violations,
        )

    async def should_continue(
        self,
        has_final_answer: bool = False,
        confidence: float | None = None,
    ) -> GuardrailResult:
        """Determine if autonomous execution should continue.

        Args:
            has_final_answer: Whether a final answer has been generated
            confidence: Current confidence score (0-1)

        Returns:
            GuardrailResult with decision and reason
        """
        # First check hard limits
        limit_result = await self.check_limits()
        if not limit_result.should_continue:
            return limit_result

        # Check for final answer
        if has_final_answer:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.SUCCESS,
                message="Final answer generated",
                state=self._state,
            )

        # Check confidence threshold
        if confidence is not None and confidence >= self._confidence_threshold:
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.CONFIDENCE_THRESHOLD,
                message=f"Confidence threshold ({self._confidence_threshold}) reached: {confidence}",
                state=self._state,
            )

        # Check for loops
        if self._detect_loop():
            return GuardrailResult(
                should_continue=False,
                reason=TerminationReason.LOOP_DETECTED,
                message="Action loop detected",
                state=self._state,
                violations=["action_loop"],
            )

        return GuardrailResult(
            should_continue=True,
            reason=TerminationReason.SUCCESS,
            message="Execution can continue",
            state=self._state,
        )

    def _detect_loop(self) -> bool:
        """Detect if agent is stuck in a loop.

        Checks for:
        1. Same action repeated multiple times
        2. Alternating action pattern (A, B, A, B)
        3. Same result 3+ times (stuck state)
        4. Same error type 3+ times (error loop)
        """
        actions = self._state.last_actions
        results = self._state.last_results
        errors = self._state.errors

        if len(actions) < self.MAX_ACTION_REPETITIONS:
            return False

        # Check for consecutive same actions
        last_n = actions[-self.MAX_ACTION_REPETITIONS :]
        if len(set(last_n)) == 1:
            logger.warning(f"[Guardrails] Loop detected: same action repeated {self.MAX_ACTION_REPETITIONS} times")
            return True

        # Check for alternating pattern (A, B, A, B)
        if len(actions) >= 4:
            if actions[-4] == actions[-2] and actions[-3] == actions[-1]:
                logger.warning("[Guardrails] Alternating loop detected")
                return True

        # Check for semantic result loops (same result 3+ times)
        if len(results) >= 3:
            last_3_results = results[-3:]
            # Normalize and compare
            normalized = [r.strip().lower()[:100] for r in last_3_results]
            if len(set(normalized)) == 1:
                logger.warning("[Guardrails] Stuck state detected: same result 3 times")
                return True

        # Check for error loops (same error type 3+ times)
        if len(errors) >= 3:
            recent_errors = errors[-3:]
            # Extract error type (first word or first 30 chars)
            error_types = [e.split()[0] if e.split() else e[:30] for e in recent_errors]
            if len(set(error_types)) == 1:
                logger.warning(f"[Guardrails] Error loop detected: same error type repeated: {error_types[0]}")
                return True

        # Check for result alternating loop (result A, result B, result A, result B)
        if len(results) >= 4:
            r = [x.strip().lower()[:100] for x in results]
            if r[-4] == r[-2] and r[-3] == r[-1] and r[-4] != r[-3]:
                logger.warning("[Guardrails] Result alternating loop detected")
                return True

        return False

    def get_remaining_budget(self) -> dict[str, Any]:
        """Get remaining execution budget."""
        return {
            "iterations_remaining": self._max_iterations - self._state.iterations,
            "time_remaining": max(0, self._max_time - self._state.elapsed_seconds()),
            "llm_calls_remaining": self._max_llm_calls - self._state.llm_calls,
            "tokens_remaining": self._max_tokens - self._state.tokens_used,
        }

    def get_status(self) -> dict[str, Any]:
        """Get current guardrail status."""
        return {
            "iterations": self._state.iterations,
            "llm_calls": self._state.llm_calls,
            "tokens_used": self._state.tokens_used,
            "elapsed_seconds": round(self._state.elapsed_seconds(), 2),
            "error_count": len(self._state.errors),
            "remaining_budget": self.get_remaining_budget(),
            "limits": {
                "max_iterations": self._max_iterations,
                "max_time_seconds": self._max_time,
                "max_llm_calls": self._max_llm_calls,
                "max_tokens": self._max_tokens,
                "confidence_threshold": self._confidence_threshold,
            },
        }


class GracefulTerminator:
    """Handles graceful termination of autonomous execution.

    Ensures clean shutdown with meaningful final output.
    """

    def __init__(self, guardrails: AutonomyGuardrails):
        self._guardrails = guardrails

    async def terminate(
        self,
        reason: TerminationReason,
        partial_result: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate graceful termination response.

        Args:
            reason: Why termination occurred
            partial_result: Any partial result available
            context: Additional context about execution

        Returns:
            Dict with termination details and best-effort answer
        """
        status = self._guardrails.get_status()

        response = {
            "terminated": True,
            "reason": reason.value,
            "message": self._get_termination_message(reason),
            "partial_result": partial_result,
            "execution_stats": {
                "iterations": status["iterations"],
                "llm_calls": status["llm_calls"],
                "elapsed_seconds": status["elapsed_seconds"],
            },
        }

        # Add context if available
        if context:
            response["context"] = context

        # Log termination
        if reason in [TerminationReason.ERROR, TerminationReason.LOOP_DETECTED]:
            logger.warning(f"[Terminator] Terminated: {reason.value}")
        else:
            logger.info(f"[Terminator] Terminated: {reason.value}")

        return response

    def _get_termination_message(self, reason: TerminationReason) -> str:
        """Get user-friendly termination message."""
        messages = {
            TerminationReason.SUCCESS: "Task completed successfully.",
            TerminationReason.MAX_ITERATIONS: "Maximum processing steps reached. "
            "Here's the best answer I could generate.",
            TerminationReason.TIMEOUT: "Processing time limit reached. "
            "Here's what I found so far.",
            TerminationReason.MAX_LLM_CALLS: "Processing limit reached. "
            "Please try a simpler question.",
            TerminationReason.MAX_TOKENS: "Response size limit reached. "
            "Here's a summarized answer.",
            TerminationReason.ERROR: "An error occurred during processing. "
            "Please try again.",
            TerminationReason.CONFIDENCE_THRESHOLD: "Found a satisfactory answer.",
            TerminationReason.USER_INTERRUPT: "Processing was interrupted.",
            TerminationReason.LOOP_DETECTED: "Detected a processing loop. "
            "Here's the best answer available.",
            TerminationReason.GUARDRAIL_TRIGGERED: "Safety limit triggered. "
            "Processing stopped.",
        }
        return messages.get(reason, "Processing completed.")
