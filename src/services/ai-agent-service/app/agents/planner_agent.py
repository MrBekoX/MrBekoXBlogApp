"""Planner Agent - Task decomposition and action plan creation.

Optimized for Gemma3:4b with simple, structured plans (max 3-5 steps).
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from app.domain.interfaces.i_llm_provider import ILLMProvider

if TYPE_CHECKING:
    from app.memory.episodic_memory import EpisodicMemory

logger = logging.getLogger(__name__)


class StepType(Enum):
    """Types of steps in a plan."""

    ACTION = "action"
    FINAL = "final"
    THINKING = "thinking"


class PlanStatus(Enum):
    """Status of a plan."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLANNED = "replanned"


@dataclass
class PlanStep:
    """A single step in the execution plan."""

    step_number: int
    step_type: StepType
    action: str  # tool name or "synthesize"
    description: str
    input_hint: str
    expected_output: str
    status: str = "pending"
    result: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "step_type": self.step_type.value,
            "action": self.action,
            "description": self.description,
            "input_hint": self.input_hint,
            "expected_output": self.expected_output,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class Plan:
    """Execution plan with multiple steps."""

    task: str
    steps: list[PlanStep] = field(default_factory=list)
    success_criteria: str = ""
    max_iterations: int = 5
    status: PlanStatus = PlanStatus.PENDING
    current_step: int = 0
    iterations_used: int = 0
    replan_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "success_criteria": self.success_criteria,
            "max_iterations": self.max_iterations,
            "status": self.status.value,
            "current_step": self.current_step,
            "iterations_used": self.iterations_used,
            "replan_count": self.replan_count,
        }

    def get_current_step(self) -> PlanStep | None:
        """Get the current step to execute."""
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def advance(self) -> bool:
        """Move to the next step. Returns True if more steps remain."""
        self.current_step += 1
        return self.current_step < len(self.steps)

    def mark_step_completed(self, result: str):
        """Mark current step as completed with result."""
        step = self.get_current_step()
        if step:
            step.status = "completed"
            step.result = result

    def mark_step_failed(self, error: str):
        """Mark current step as failed with error."""
        step = self.get_current_step()
        if step:
            step.status = "failed"
            step.error = error


# Gemma3:4b optimized planning prompt - short and structured
PLANNING_PROMPT = """Task: {task}
Tools: {tools}

Create a 2-4 step plan. Format:
1. [ACTION] tool | what to search/get | expected info
2. [ACTION] tool | what next | expected info
3. [FINAL] answer | combine all | final response

Rules:
- Use web_search for current/external info
- Use rag_retrieve for article content
- Use memory_search for past conversations
- Use verify_citation to return confidence + source chunks
- Use related_posts to recommend relevant blog posts
- Use preference_memory to apply saved user preferences
- Use readability_rewriter to adapt complexity/tone
- Use feedback_learning to store user feedback signals
- Use final_answer when ready

Plan:"""

TOOL_SELECTION_PROMPT = """Task step: {step_description}
Available: {tools}

Pick ONE tool. Reply format:
TOOL: tool_name
INPUT: what to search/ask

Response:"""


class PlannerAgent:
    """Creates execution plans optimized for Gemma3:4b.

    Responsibilities:
    1. Analyze incoming task
    2. Decompose into 2-4 simple steps
    3. Select appropriate tool for each step
    4. Define success criteria
    5. Deduplicate consecutive actions
    6. Ensure web_search when user intent includes web search
    """

    # Available tools for planning
    DEFAULT_TOOLS = [
        "web_search",
        "rag_retrieve",
        "memory_search",
        "verify_citation",
        "related_posts",
        "preference_memory",
        "readability_rewriter",
        "feedback_learning",
        "final_answer",
    ]

    # Web search intent patterns
    WEB_SEARCH_INTENT_PATTERNS = [
        r"web('de|de)\s*(ara|bul|arastir)",
        r"internet(ten|ten)\s*ara",
        r"online\s*ara",
        r"google'da\s*ara",
        r"search\s+(on\s+)?(the\s+)?web",
        r"look\s+up\s+online",
        r"find\s+(on\s+)?(the\s+)?internet",
    ]

    def __init__(
        self,
        llm_provider: ILLMProvider,
        available_tools: list[str] | None = None,
        max_plan_steps: int = 4,
        episodic_memory: "EpisodicMemory | None" = None,
    ):
        self._llm = llm_provider
        self._available_tools = available_tools or self.DEFAULT_TOOLS
        self._max_plan_steps = min(max_plan_steps, 5)  # Cap at 5 for Gemma
        self._episodic_memory = episodic_memory

    async def create_plan(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Create an execution plan for the given task.

        Args:
            task: The user's task/query
            context: Additional context (post_id, history, etc.)

        Returns:
            A Plan object with steps to execute
        """
        # Try to get a plan suggestion from episodic memory
        if self._episodic_memory:
            try:
                suggested_plan, confidence = await self._episodic_memory.suggest_plan(task)
                if suggested_plan and confidence >= 0.7:
                    logger.info(
                        f"[Planner] Using suggested plan from episodic memory "
                        f"(confidence: {confidence:.2f})"
                    )
                    return suggested_plan
            except Exception as e:
                logger.warning(f"[Planner] Episodic memory lookup failed: {e}")

        tools_str = ", ".join(self._available_tools)

        # Build prompt with context
        context_str = ""
        if context:
            if context.get("post_id"):
                context_str += f"\nArticle ID: {context['post_id']}"
            if context.get("has_memory"):
                context_str += "\nMemory available: yes"

        full_task = f"{task}{context_str}"

        prompt = PLANNING_PROMPT.format(
            task=full_task,
            tools=tools_str,
        )

        try:
            response = await self._llm.generate_text(prompt)
            plan = self._parse_plan_response(task, response)

            # Apply post-processing: deduplicate and ensure web search
            plan.steps = self._deduplicate_consecutive_steps(plan.steps)
            plan.steps = self._ensure_web_search_if_needed(plan.steps, task)
            # Renumber steps after modifications
            for i, step in enumerate(plan.steps):
                step.step_number = i + 1

            logger.info(
                f"[Planner] Created plan with {len(plan.steps)} steps: "
                f"{[s.action for s in plan.steps]}"
            )
            return plan

        except Exception as e:
            logger.error(f"[Planner] Plan creation failed: {e}")
            # Return a fallback plan
            return self._create_fallback_plan(task)

    def _parse_plan_response(self, task: str, response: str) -> Plan:
        """Parse LLM response into a structured Plan."""
        steps = []

        # Pattern to match plan steps
        # Format: 1. [ACTION] tool | input | expected
        step_pattern = re.compile(
            r"(\d+)\.\s*\[(\w+)\]\s*(\w+)\s*\|\s*([^|]+)\s*\|\s*(.+?)(?=\n\d+\.|$)",
            re.DOTALL,
        )

        matches = step_pattern.findall(response)

        for match in matches:
            step_num, step_type_str, action, input_hint, expected = match
            step_type = StepType.ACTION if step_type_str.upper() == "ACTION" else StepType.FINAL

            # Validate action
            action = action.strip().lower()
            if action not in self._available_tools:
                action = "final_answer"  # Fallback

            steps.append(
                PlanStep(
                    step_number=int(step_num),
                    step_type=step_type,
                    action=action,
                    description=f"Execute {action}",
                    input_hint=input_hint.strip(),
                    expected_output=expected.strip(),
                    status="pending",
                )
            )

        # If parsing failed, create simple fallback
        if not steps:
            steps = [
                PlanStep(
                    step_number=1,
                    step_type=StepType.ACTION,
                    action="rag_retrieve",
                    description="Retrieve relevant content",
                    input_hint=task,
                    expected_output="Relevant article sections",
                    status="pending",
                ),
                PlanStep(
                    step_number=2,
                    step_type=StepType.FINAL,
                    action="final_answer",
                    description="Provide final answer",
                    input_hint="Combine retrieved info",
                    expected_output="Complete answer",
                    status="pending",
                ),
            ]

        # Ensure we have a final step
        if not any(s.step_type == StepType.FINAL for s in steps):
            steps.append(
                PlanStep(
                    step_number=len(steps) + 1,
                    step_type=StepType.FINAL,
                    action="final_answer",
                    description="Provide final answer",
                    input_hint="Synthesize all information",
                    expected_output="Complete response",
                    status="pending",
                )
            )

        return Plan(
            task=task,
            steps=steps[:self._max_plan_steps],  # Limit steps
            success_criteria="Answer addresses the user's question accurately",
            max_iterations=len(steps) + 2,  # Allow some buffer
        )

    def _create_fallback_plan(self, task: str) -> Plan:
        """Create a simple fallback plan when parsing fails."""
        return Plan(
            task=task,
            steps=[
                PlanStep(
                    step_number=1,
                    step_type=StepType.ACTION,
                    action="rag_retrieve",
                    description="Search article for relevant content",
                    input_hint=task,
                    expected_output="Relevant article sections",
                    status="pending",
                ),
                PlanStep(
                    step_number=2,
                    step_type=StepType.FINAL,
                    action="final_answer",
                    description="Provide answer based on findings",
                    input_hint="Synthesize retrieved content",
                    expected_output="Complete answer to user's question",
                    status="pending",
                ),
            ],
            success_criteria="Answer is relevant and accurate",
            max_iterations=3,
        )

    async def replan(
        self,
        original_plan: Plan,
        failed_step: PlanStep,
        observation: str,
        error: str | None = None,
    ) -> Plan:
        """Create a new plan based on failed execution.

        Args:
            original_plan: The original plan that failed
            failed_step: The step that failed
            observation: What was observed from the failure
            error: Error message if any

        Returns:
            A new Plan with adjusted approach
        """
        # Increment replan count
        original_plan.replan_count += 1

        # Don't replan more than 2 times
        if original_plan.replan_count > 2:
            logger.warning("[Planner] Max replan attempts reached, forcing final answer")
            return Plan(
                task=original_plan.task,
                steps=[
                    PlanStep(
                        step_number=1,
                        step_type=StepType.FINAL,
                        action="final_answer",
                        description="Provide best-effort answer",
                        input_hint=f"Based on available information: {observation[:500]}",
                        expected_output="Best possible answer",
                        status="pending",
                    )
                ],
                success_criteria="Provide best-effort response",
                max_iterations=1,
            )

        # Determine alternative action
        alternative_action = self._get_alternative_action(failed_step.action)

        # Create adjusted plan
        new_steps = []
        for i, step in enumerate(original_plan.steps):
            if i < original_plan.current_step:
                # Keep completed steps
                new_steps.append(step)
            elif i == original_plan.current_step:
                # Replace failed step with alternative
                new_steps.append(
                    PlanStep(
                        step_number=i + 1,
                        step_type=step.step_type,
                        action=alternative_action,
                        description=f"Retry with {alternative_action}",
                        input_hint=step.input_hint,
                        expected_output=step.expected_output,
                        status="pending",
                    )
                )
            else:
                # Keep remaining steps
                new_steps.append(
                    PlanStep(
                        step_number=i + 1,
                        step_type=step.step_type,
                        action=step.action,
                        description=step.description,
                        input_hint=step.input_hint,
                        expected_output=step.expected_output,
                        status="pending",
                    )
                )

        logger.info(
            f"[Planner] Replanned: {failed_step.action} -> {alternative_action}"
        )

        return Plan(
            task=original_plan.task,
            steps=new_steps,
            success_criteria=original_plan.success_criteria,
            max_iterations=original_plan.max_iterations,
            replan_count=original_plan.replan_count,
        )

    def _get_alternative_action(self, failed_action: str) -> str:
        """Get an alternative action when one fails."""
        alternatives = {
            "web_search": "rag_retrieve",
            "rag_retrieve": "web_search",
            "memory_search": "rag_retrieve",
            "verify_citation": "rag_retrieve",
            "related_posts": "rag_retrieve",
            "preference_memory": "memory_search",
            "readability_rewriter": "final_answer",
            "feedback_learning": "final_answer",
        }
        return alternatives.get(failed_action, "final_answer")

    def _deduplicate_consecutive_steps(self, steps: list[PlanStep]) -> list[PlanStep]:
        """Remove consecutive duplicate actions to prevent loops.

        Args:
            steps: List of plan steps

        Returns:
            Filtered list with consecutive duplicates removed
        """
        if len(steps) <= 1:
            return steps

        filtered = [steps[0]]
        for i in range(1, len(steps)):
            current_action = steps[i].action
            prev_action = filtered[-1].action

            # Allow same action if it's final_answer (it's the expected end)
            if current_action == "final_answer":
                filtered.append(steps[i])
            # Skip if same as previous (duplicate)
            elif current_action == prev_action:
                logger.warning(
                    f"[Planner] Removed duplicate consecutive action: {current_action}"
                )
            else:
                filtered.append(steps[i])

        return filtered

    def _ensure_web_search_if_needed(
        self, steps: list[PlanStep], task: str
    ) -> list[PlanStep]:
        """Ensure web_search is in plan if user intent includes web search.

        Args:
            steps: List of plan steps
            task: Original task/query

        Returns:
            Modified list with web_search step if needed
        """
        task_lower = task.lower()

        # Check for web search intent
        has_web_intent = any(
            re.search(pattern, task_lower)
            for pattern in self.WEB_SEARCH_INTENT_PATTERNS
        )

        if not has_web_intent:
            return steps

        # Check if web_search is already in the plan
        has_web_step = any(s.action == "web_search" for s in steps)

        if has_web_step:
            return steps

        # Insert web_search before final_answer
        logger.info("[Planner] Web search intent detected, ensuring web_search step")

        new_steps = []
        inserted = False

        for step in steps:
            if step.action == "final_answer" and not inserted:
                # Insert web_search before final_answer
                web_step = PlanStep(
                    step_number=0,  # Will be renumbered
                    step_type=StepType.ACTION,
                    action="web_search",
                    description="Search the web for information",
                    input_hint=task,
                    expected_output="Web search results",
                    status="pending",
                )
                new_steps.append(web_step)
                inserted = True
            new_steps.append(step)

        # If no final_answer was found, add web_search at the end
        if not inserted and new_steps:
            web_step = PlanStep(
                step_number=0,
                step_type=StepType.ACTION,
                action="web_search",
                description="Search the web for information",
                input_hint=task,
                expected_output="Web search results",
                status="pending",
            )
            new_steps.insert(len(new_steps) - 1, web_step)

        return new_steps

    async def assess_complexity(self, query: str) -> str:
        """Assess query complexity to determine routing.

        Returns: 'simple' or 'complex'
        """
        lower = query.lower().strip()

        # Simple heuristics for complexity
        complexity_markers = [
            # Multiple questions
            lower.count("?") > 1,
            # Comparison keywords
            any(
                m in lower
                for m in [
                    "karsilastir",
                    "compare",
                    "fark",
                    "difference",
                    "vs",
                    "versus",
                ]
            ),
            # Multi-step indicators
            any(
                m in lower
                for m in [
                    "ve sonra",
                    "and then",
                    "ayrica",
                    "also",
                    "hem de",
                    "as well as",
                ]
            ),
            # Analysis keywords
            any(
                m in lower
                for m in [
                    "analiz",
                    "analyze",
                    "neden",
                    "why",
                    "nasil",
                    "how does",
                    "acikla",
                    "explain",
                ]
            ),
            # Long queries
            len(lower.split()) > 20,
        ]

        return "complex" if any(complexity_markers) else "simple"
