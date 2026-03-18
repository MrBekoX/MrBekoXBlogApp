"""Plan Validator - Validates execution plans for safety and feasibility.

Ensures plans are well-formed, avoid infinite loops, and respect resource limits.
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.agents.planner_agent import Plan, PlanStep, StepType

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of plan validation."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }


class PlanValidator:
    """Validates execution plans before execution.

    Checks:
    1. Plan structure integrity
    2. Tool availability
    3. Loop detection
    4. Resource limits
    5. Step dependencies
    """

    # Maximum allowed steps in a plan
    MAX_STEPS = 6

    # Maximum consecutive same-action steps (loop detection)
    MAX_SAME_ACTION = 2

    # Tools that must end the plan
    TERMINAL_TOOLS = {"final_answer", "synthesize"}

    def __init__(
        self,
        available_tools: list[str] | None = None,
        max_iterations: int = 10,
        max_time_seconds: int = 120,
    ):
        self._available_tools = set(available_tools or [])
        self._max_iterations = max_iterations
        self._max_time_seconds = max_time_seconds

    def validate(self, plan: Plan) -> ValidationResult:
        """Validate a plan for execution safety.

        Args:
            plan: The plan to validate

        Returns:
            ValidationResult with errors, warnings, and suggestions
        """
        errors = []
        warnings = []
        suggestions = []

        # 1. Check plan structure
        if not plan.steps:
            errors.append("Plan has no steps")
            return ValidationResult(False, errors, warnings, suggestions)

        if len(plan.steps) > self.MAX_STEPS:
            warnings.append(f"Plan has {len(plan.steps)} steps, max recommended is {self.MAX_STEPS}")
            suggestions.append("Consider breaking into smaller sub-plans")

        # 2. Check each step
        for i, step in enumerate(plan.steps):
            step_errors = self._validate_step(step, i)
            errors.extend(step_errors)

        # 3. Check for loops (same action repeated)
        loop_warnings = self._detect_loops(plan)
        warnings.extend(loop_warnings)

        # 4. Check for terminal step
        has_terminal = any(
            s.action in self.TERMINAL_TOOLS or s.step_type == StepType.FINAL
            for s in plan.steps
        )
        if not has_terminal:
            warnings.append("Plan has no explicit terminal/final step")
            suggestions.append("Add a final_answer step at the end")

        # 5. Check tool availability
        tool_errors = self._check_tool_availability(plan)
        errors.extend(tool_errors)

        # 6. Check iteration limits
        if plan.max_iterations > self._max_iterations:
            warnings.append(
                f"Plan max_iterations ({plan.max_iterations}) exceeds "
                f"system limit ({self._max_iterations})"
            )

        is_valid = len(errors) == 0

        if not is_valid:
            logger.warning(f"[PlanValidator] Plan validation failed: {errors}")
        elif warnings:
            logger.info(f"[PlanValidator] Plan validated with warnings: {warnings}")

        return ValidationResult(is_valid, errors, warnings, suggestions)

    def _validate_step(self, step: PlanStep, index: int) -> list[str]:
        """Validate a single plan step."""
        errors = []

        # Check action is not empty
        if not step.action:
            errors.append(f"Step {index + 1}: Missing action")

        # Check step number consistency
        if step.step_number != index + 1:
            errors.append(
                f"Step {index + 1}: Step number mismatch "
                f"(expected {index + 1}, got {step.step_number})"
            )

        # Check input hint
        if not step.input_hint and step.step_type != StepType.FINAL:
            errors.append(f"Step {index + 1}: Missing input hint for action step")

        return errors

    def _detect_loops(self, plan: Plan) -> list[str]:
        """Detect potential infinite loops in the plan."""
        warnings = []

        # Check for consecutive same actions
        action_sequence = [s.action for s in plan.steps]

        for i in range(len(action_sequence) - 1):
            if action_sequence[i] == action_sequence[i + 1]:
                warnings.append(
                    f"Consecutive identical actions detected: {action_sequence[i]}"
                )

        # Check for repeating patterns (A -> B -> A -> B)
        if len(action_sequence) >= 4:
            for pattern_len in [2, 3]:
                if len(action_sequence) >= pattern_len * 2:
                    pattern = action_sequence[:pattern_len]
                    next_pattern = action_sequence[pattern_len : pattern_len * 2]
                    if pattern == next_pattern:
                        warnings.append(
                            f"Repeating pattern detected: {' -> '.join(pattern)}"
                        )

        return warnings

    def _check_tool_availability(self, plan: Plan) -> list[str]:
        """Check if all tools in the plan are available."""
        errors = []

        if not self._available_tools:
            # Skip check if no tools registered
            return errors

        for step in plan.steps:
            if step.action not in self.TERMINAL_TOOLS:
                if step.action not in self._available_tools:
                    errors.append(
                        f"Tool '{step.action}' is not available. "
                        f"Available: {', '.join(sorted(self._available_tools))}"
                    )

        return errors

    def validate_step_result(
        self,
        step: PlanStep,
        result: str,
        expected_output: str,
    ) -> tuple[bool, str]:
        """Validate if a step's result matches expectations.

        Args:
            step: The executed step
            result: The actual result
            expected_output: The expected output description

        Returns:
            Tuple of (is_acceptable, feedback)
        """
        # Check for empty result
        if not result or not result.strip():
            return False, "Result is empty"

        # Check for error indicators
        error_indicators = ["error", "failed", "exception", "unable to", "cannot"]
        lower_result = result.lower()
        if any(ind in lower_result for ind in error_indicators):
            # Might still be acceptable if it's informative
            if len(result) > 100:
                # Has some content despite error mention
                return True, "Result has content but mentions issues"
            return False, f"Result indicates failure: {result[:100]}"

        # Check result length (too short might be incomplete)
        if len(result) < 20 and step.step_type != StepType.FINAL:
            return True, "Result is short but may be sufficient"

        return True, "Result appears acceptable"

    def should_continue(
        self,
        plan: Plan,
        current_result: str | None,
        iterations: int,
    ) -> tuple[bool, str]:
        """Determine if the plan execution should continue.

        Args:
            plan: Current plan
            current_result: Result from current step
            iterations: Number of iterations so far

        Returns:
            Tuple of (should_continue, reason)
        """
        # Check iteration limit
        if iterations >= self._max_iterations:
            return False, f"Max iterations ({self._max_iterations}) reached"

        # Check if plan is complete
        if plan.current_step >= len(plan.steps):
            return False, "All steps completed"

        # Check if we have a satisfactory result
        current_step = plan.get_current_step()
        if current_step and current_step.step_type == StepType.FINAL:
            if current_result and len(current_result) > 50:
                return False, "Final answer generated"

        return True, "Continuing execution"

    def sanitize_plan(self, plan: Plan) -> Plan:
        """Create a sanitized version of the plan with fixes applied.

        Args:
            plan: Original plan

        Returns:
            Sanitized plan with automatic fixes
        """
        # Make a copy of steps
        sanitized_steps = []

        for i, step in enumerate(plan.steps):
            # Fix step numbers
            step.step_number = i + 1

            # Ensure final step exists
            if i == len(plan.steps) - 1:
                if step.action not in self.TERMINAL_TOOLS:
                    step.step_type = StepType.FINAL
                    step.action = "final_answer"

            sanitized_steps.append(step)

        # Ensure we don't exceed max steps
        if len(sanitized_steps) > self.MAX_STEPS:
            # Keep first steps and ensure final
            sanitized_steps = sanitized_steps[: self.MAX_STEPS - 1]
            sanitized_steps.append(
                PlanStep(
                    step_number=len(sanitized_steps) + 1,
                    step_type=StepType.FINAL,
                    action="final_answer",
                    description="Provide final answer",
                    input_hint="Synthesize all findings",
                    expected_output="Complete response",
                    status="pending",
                )
            )

        plan.steps = sanitized_steps
        plan.max_iterations = min(plan.max_iterations, self._max_iterations)

        return plan
